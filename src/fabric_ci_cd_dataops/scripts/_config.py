"""Load fab-test.yml, the optional config-file front door (Config Consolidation §1).

fab-test.yml is entirely optional: no file means an empty configuration and
behavior identical to a repository with no config at all. Nothing in the
codebase depends on the returned dict yet -- later tasks in this epic merge
it with `[tool.fab-test]`, validate its keys, and route every setting
through one precedence resolver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_FILENAME = "fab-test.yml"


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
