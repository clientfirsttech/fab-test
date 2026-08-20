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
    "environment": str,
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
    warnings = []
    if pyproject_config and yaml_config:
        warnings.append(
            f"both {pyproject_path.name}'s [tool.fab-test] and {CONFIG_FILENAME} are "
            f"present; {CONFIG_FILENAME} wins for any overlapping key"
        )
    return {**pyproject_config, **yaml_config}, warnings


def validate_config(config: dict[str, Any]) -> None:
    """Validate a merged config dict's keys and value types.

    Raises ConfigError naming the offending key -- with the closest valid
    key when one is close enough, or the expected type for a type
    mismatch. A single pass over a handful of keys; adds no measurable
    startup cost for a valid config.
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
