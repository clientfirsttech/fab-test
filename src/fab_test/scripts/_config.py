"""Load fab-test.yml, the optional config-file front door (Config Consolidation §1).

fab-test.yml is entirely optional: no file means an empty configuration and
behavior identical to a repository with no config at all. Nothing in the
codebase depends on the returned dict yet -- later tasks in this epic merge
it with `[tool.fab-test]`, validate its keys, and route every setting
through one precedence resolver.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = "fab-test.yml"

# The ladder ANALYZER_VERBOSITY, -q, -v and -vv all name. Ordered quietest first.
VERBOSITY_LEVELS = ("summary", "default", "verbose", "debug")

# Every setting fab-test currently reads from a config file, and its
# expected Python type. Keep in sync with the argparse defaults and
# _resolve_timeout/_apply_environment_default in fab_test.py -- task 11
# formalizes this as a JSON schema and asserts the two can't drift.
_VALID_KEYS: dict[str, type] = {
    "artifact_dir": str,
    "output_dir": str,
    "jobs": int,
    "format": str,
    "timeout": int,
    # One rung of VERBOSITY_LEVELS, applied when no -q/-v flag is passed
    # (Terse CLI Output). ANALYZER_VERBOSITY still wins over the file.
    "verbosity": str,
    "environment": str,
    # Default workspace for targets that name an artifact but not a
    # workspace (Artifact Targeting and Auth §3). A display name or a GUID;
    # a positional WORKSPACE.Workspace/... target overrides it.
    "workspace": str,
    # Generate a readable HTML report beside each envelope (Human-Readable
    # Reports §5). Opt-in: false unless asked for.
    "report": bool,
    # Open the produced report/index in the default browser after the run
    # (Open Report Flag epic §1). Opt-in, implies `report`, suppressed
    # under CI.
    "open_report": bool,
    # Effective-identity user for RLS embed tokens (Playwright Generation
    # Parity §3). Falls back from PLAYWRIGHT_USER_NAME, which still wins:
    # a caller that no longer supplies the variable per run declares the
    # UPN once here instead.
    "playwright_user_name": str,
    "playwright_config": str,
    # Rule overlays (Config Consolidation §6-7): {"bpa": {...}, "pbir": {...}}.
    # Nested disable/severity/extend keys are validated by _rule_overlay.py
    # itself at use time, not here.
    "rules": dict,
    # Where telemetry goes (Eventhouse Shipping §1): {"eventhouse": {...}}.
    # Validated below rather than at use time, unlike rules: a mistyped
    # destination is not a finding that looks wrong, it is telemetry that
    # silently lands nowhere.
    "telemetry": dict,
}


class ConfigError(Exception):
    """Raised when fab-test.yml can't be loaded: a missing --config path,
    malformed YAML, or a non-mapping top level.
    """


def discover_config_path(repo_root: Path, explicit_path: str | None = None) -> Path | None:
    """Return the config file to load, or None when there isn't one.

    ``explicit_path`` (--config) always wins over discovery, even if the
    path doesn't exist -- load_config raises ConfigError for that case
    rather than silently falling back to discovery.
    """
    if explicit_path:
        return Path(explicit_path)
    candidate = repo_root / CONFIG_FILENAME
    return candidate if candidate.exists() else None


def load_pyproject_config(path: Path) -> dict[str, Any]:
    """Load the ``[tool.fab-test]`` table from ``pyproject.toml``, if present."""
    if not path.exists():
        return {}
    import tomllib

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    config = data.get("tool", {}).get("fab-test", {})
    return config if isinstance(config, dict) else {}


def merged_file_config(
    repo_root: Path, pyproject_path: Path, explicit_path: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Merge fab-test.yml over ``[tool.fab-test]``, fab-test.yml winning per key.

    Returns ``(merged_config, warnings)``. A warning names both sources
    exactly once when both are present, since the caller (not this module)
    decides how to narrate it.
    """
    pyproject_config = load_pyproject_config(pyproject_path)
    yaml_config = load_config(repo_root, explicit_path)
    for config, owner in (
        (pyproject_config, pyproject_path),
        (yaml_config, discover_config_path(repo_root, explicit_path)),
    ):
        if owner and isinstance(config.get("playwright_config"), str) and config["playwright_config"]:
            config["playwright_config"] = str((owner.parent / config["playwright_config"]).resolve())
    warnings = []
    if pyproject_config and yaml_config:
        warnings.append(
            f"both {pyproject_path.name}'s [tool.fab-test] and {CONFIG_FILENAME} are "
            f"present; {CONFIG_FILENAME} wins for any overlapping key"
        )
    return {**pyproject_config, **yaml_config}, warnings


_RULE_OVERLAY_ANALYZERS = ("bpa", "pbir", "rdl")
_RULE_OVERLAY_KEYS: dict[str, type] = {"disable": list, "severity": dict, "extend": str}


def _validate_rule_overlay(analyzer: str, overlay: Any) -> None:
    """Validate one `rules.<analyzer>` overlay's keys, types, and item shapes."""
    path = f"rules.{analyzer}"
    if not isinstance(overlay, dict):
        raise ConfigError(f"config key '{path}' must be of type dict, got {type(overlay).__name__}")
    for key, value in overlay.items():
        key_path = f"{path}.{key}"
        if key not in _RULE_OVERLAY_KEYS:
            suggestion = difflib.get_close_matches(key, _RULE_OVERLAY_KEYS, n=1)
            hint = f" (did you mean '{suggestion[0]}'?)" if suggestion else ""
            raise ConfigError(f"unknown config key '{key_path}'{hint}")
        expected_type = _RULE_OVERLAY_KEYS[key]
        if not isinstance(value, expected_type):
            raise ConfigError(
                f"config key '{key_path}' must be of type {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
        if key == "disable" and not all(isinstance(item, str) for item in value):
            raise ConfigError(f"config key '{key_path}' must be a list of rule ID strings")
        if key == "severity" and not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise ConfigError(
                f"config key '{key_path}' must map rule ID strings to severity label strings"
            )


_EVENTHOUSE_KEYS: dict[str, type] = {"uri": str, "database": str}
_LAKEHOUSE_KEYS: dict[str, type] = {"workspace": str, "lakehouse": str}
_TELEMETRY_SECTIONS: dict[str, dict[str, type]] = {
    "eventhouse": _EVENTHOUSE_KEYS,
    "lakehouse": _LAKEHOUSE_KEYS,
}


def _validate_telemetry(telemetry: Any) -> None:
    """Validate the `telemetry` block's keys and value types.

    `eventhouse.table` is deliberately not a key: the table follows from
    which analyzer ran, so accepting one here would only let the config and
    the derivation disagree. `eventhouse` and `lakehouse` are independent,
    optional destinations -- either, both, or neither may be present.
    """
    if not isinstance(telemetry, dict):
        raise ConfigError(
            f"config key 'telemetry' must be of type dict, got {type(telemetry).__name__}"
        )
    for section, block in telemetry.items():
        if section not in _TELEMETRY_SECTIONS:
            raise ConfigError(_unknown_key(f"telemetry.{section}", _TELEMETRY_SECTIONS))
        if not isinstance(block, dict):
            raise ConfigError(
                f"config key 'telemetry.{section}' must be of type dict, "
                f"got {type(block).__name__}"
            )
        section_keys = _TELEMETRY_SECTIONS[section]
        for key, value in block.items():
            path = f"telemetry.{section}.{key}"
            if key not in section_keys:
                raise ConfigError(_unknown_key(path, section_keys))
            if not isinstance(value, section_keys[key]):
                raise ConfigError(
                    f"config key '{path}' must be of type {section_keys[key].__name__}, "
                    f"got {type(value).__name__}"
                )


def _unknown_key(path: str, valid: Any) -> str:
    """Return the 'unknown config key' message, suggesting the closest valid name."""
    leaf = path.rsplit(".", 1)[-1]
    suggestion = difflib.get_close_matches(leaf, valid, n=1)
    hint = f" (did you mean '{suggestion[0]}'?)" if suggestion else ""
    return f"unknown config key '{path}'{hint}"


def _validate_verbosity(level: str) -> None:
    """Refuse a verbosity that is not a rung of the ladder, naming the rungs."""
    if level not in VERBOSITY_LEVELS:
        raise ConfigError(
            f"config key 'verbosity' must be one of {', '.join(VERBOSITY_LEVELS)}, got '{level}'"
        )


def validate_config(config: dict[str, Any]) -> None:
    """Validate a merged config dict's keys and value types.

    Raises ConfigError naming the offending key -- with the closest valid
    key when one is close enough, or the expected type for a type
    mismatch. A single pass over a handful of keys; adds no measurable
    startup cost for a valid config. `rules.<analyzer>.*` overlays are
    validated recursively; rule-ID existence against the actual upstream
    ruleset is `_rule_overlay.py`'s job at use time, not this structural
    check.
    """
    for key, value in config.items():
        if key not in _VALID_KEYS:
            suggestion = difflib.get_close_matches(key, _VALID_KEYS, n=1)
            hint = f" (did you mean '{suggestion[0]}'?)" if suggestion else ""
            raise ConfigError(f"unknown config key '{key}'{hint}")
        expected_type = _VALID_KEYS[key]
        if not isinstance(value, expected_type):
            raise ConfigError(
                f"config key '{key}' must be of type {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )

    if "verbosity" in config:
        _validate_verbosity(config["verbosity"])

    if "telemetry" in config:
        _validate_telemetry(config["telemetry"])

    rules = config.get("rules")
    if isinstance(rules, dict):
        for analyzer, overlay in rules.items():
            if analyzer not in _RULE_OVERLAY_ANALYZERS:
                suggestion = difflib.get_close_matches(analyzer, _RULE_OVERLAY_ANALYZERS, n=1)
                hint = f" (did you mean '{suggestion[0]}'?)" if suggestion else ""
                raise ConfigError(f"unknown config key 'rules.{analyzer}'{hint}")
            _validate_rule_overlay(analyzer, overlay)


def load_config(repo_root: Path, explicit_path: str | None = None) -> dict[str, Any]:
    """Load and parse the config file into a plain dict.

    Returns an empty dict when no config file exists at all -- the common
    case, and behavior identical to today. Raises ConfigError naming the
    file for a missing --config path, malformed YAML, or a non-mapping
    top level.
    """
    path = discover_config_path(repo_root, explicit_path)
    if path is None:
        return {}
    if not path.exists():
        raise ConfigError(f"--config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"malformed YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path} must contain a YAML mapping at the top level, got {type(data).__name__}"
        )
    return data


def resolve_setting(
    key: str,
    *,
    cli_value: Any,
    env_var: str | None,
    file_config: dict[str, Any],
    packaged_default: Any,
    cast: type | None = None,
) -> tuple[Any, str]:
    """Resolve one setting: CLI flag > environment variable > config file > packaged default.

    ``cli_value`` must be ``None`` when the flag wasn't explicitly passed --
    the caller's argparse default should be ``None`` precisely so this can
    be told apart from "explicitly set to the packaged default". Returns
    ``(value, origin)``; origin is one of ``"flag"``, ``"env:NAME"``,
    ``"fab-test.yml:KEY"``, or ``"default"``. A malformed env var (fails
    ``cast``) falls through to the config file / packaged default rather
    than raising.
    """
    if cli_value is not None:
        return cli_value, "flag"
    if env_var:
        raw = os.environ.get(env_var, "")
        if raw:
            if cast is None:
                return raw, f"env:{env_var}"
            try:
                return cast(raw), f"env:{env_var}"
            except ValueError:
                pass
    if key in file_config:
        return file_config[key], f"{CONFIG_FILENAME}:{key}"
    return packaged_default, "default"


def verbosity_level(raw: str) -> str:
    """Normalize a verbosity name, or raise ValueError so a bad env var falls through."""
    level = raw.strip().lower()
    if level not in VERBOSITY_LEVELS:
        raise ValueError(raw)
    return level


def apply_verbosity_default(args: Any, file_config: dict[str, Any]) -> None:
    """Fill -q/-v from ANALYZER_VERBOSITY or fab-test.yml when no flag was passed.

    Precedence is flag > ANALYZER_VERBOSITY > fab-test.yml > default, like every
    other setting. The result is written back as the flag it stands for, so the
    parent's narration and the analyzer subprocesses read one value. A
    subcommand without the flags (doctor, config, ...) is left alone.
    """
    if not hasattr(args, "quiet") or args.quiet or args.verbose:
        return
    level, _origin = resolve_setting(
        "verbosity",
        cli_value=None,
        env_var="ANALYZER_VERBOSITY",
        file_config=file_config,
        packaged_default="default",
        cast=verbosity_level,
    )
    args.quiet = level == "summary"
    args.verbose = {"verbose": 1, "debug": 2}.get(level, 0)
