#!/usr/bin/env python3
"""
Validate the unified environments.yml metadata file.

Enforces the schema contract every consumer of `environments.yml` relies on
(the schema validator, `playwright_validation`'s workspace resolver).

Usage:
    python scripts/validate_environments_yaml.py [--path PATH]

Exit codes:
    0 - environments.yml is valid
    1 - schema violation or I/O error
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._metadata import MetadataNotFoundError, resolve_environments_yml

# Ensure UTF-8 output on Windows where the default pipe encoding is cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    import yaml
except ImportError:  # pragma: no cover - exercised via pytest, not unit-tested
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

REQUIRED_TOP_LEVEL_KEYS = {"defaults", "environments"}
REQUIRED_ENVIRONMENT_KEYS = {
    "description",
    "workspace_id",
    "allowed_branches",
    "promotion_target",
}
OPTIONAL_ENVIRONMENT_KEYS = {
    "previous_environment",
    "requires_validation",
    "requires_security_scan",
    "requires_ai_validation",
    "allows_rollback",
    "deployment_window",
    "approval_required",
}
ALLOWED_ENVIRONMENT_KEYS = REQUIRED_ENVIRONMENT_KEYS | OPTIONAL_ENVIRONMENT_KEYS

REQUIRED_DEPLOYMENT_WINDOW_KEYS = {"enabled"}
OPTIONAL_DEPLOYMENT_WINDOW_KEYS = {"allowed_days", "allowed_hours_utc"}
ALLOWED_DEPLOYMENT_WINDOW_KEYS = REQUIRED_DEPLOYMENT_WINDOW_KEYS | OPTIONAL_DEPLOYMENT_WINDOW_KEYS


def _error(message: str) -> None:
    print(f"❌ {message}", file=sys.stderr)


def _info(message: str) -> None:
    print(f"✅ {message}")


def _validate_top_level_keys(config: dict) -> list[str]:
    """Check the required/allowed set of top-level keys."""
    errors: list[str] = []
    missing_top = REQUIRED_TOP_LEVEL_KEYS - config.keys()
    if missing_top:
        errors.append(f"Missing top-level keys: {sorted(missing_top)}")
    extra_top = config.keys() - REQUIRED_TOP_LEVEL_KEYS - {"promotion_chain"}
    if extra_top:
        errors.append(f"Unexpected top-level keys: {sorted(extra_top)}")
    return errors


def _validate_deployment_window(env_name: str, deployment_window: object) -> list[str]:
    """Check one environment's optional ``deployment_window`` block."""
    if not isinstance(deployment_window, dict):
        return [f"Environment '{env_name}' deployment_window must be a mapping"]

    errors: list[str] = []
    missing_dw = REQUIRED_DEPLOYMENT_WINDOW_KEYS - deployment_window.keys()
    if missing_dw:
        errors.append(
            f"Environment '{env_name}' deployment_window missing keys: {sorted(missing_dw)}"
        )
    extra_dw = deployment_window.keys() - ALLOWED_DEPLOYMENT_WINDOW_KEYS
    if extra_dw:
        errors.append(
            f"Environment '{env_name}' deployment_window unexpected keys: {sorted(extra_dw)}"
        )
    return errors


def _validate_environment_block(env_name: str, env_block: object) -> list[str]:
    """Check one environment's required/allowed keys and nested blocks."""
    if not isinstance(env_block, dict):
        return [f"Environment '{env_name}' must be a mapping"]

    errors: list[str] = []
    missing_env = REQUIRED_ENVIRONMENT_KEYS - env_block.keys()
    if missing_env:
        errors.append(f"Environment '{env_name}' missing required keys: {sorted(missing_env)}")

    extra_env = env_block.keys() - ALLOWED_ENVIRONMENT_KEYS
    if extra_env:
        errors.append(f"Environment '{env_name}' has unexpected keys: {sorted(extra_env)}")

    if not isinstance(env_block.get("allowed_branches", []), list):
        errors.append(f"Environment '{env_name}' allowed_branches must be a list")

    deployment_window = env_block.get("deployment_window")
    if deployment_window is not None:
        errors += _validate_deployment_window(env_name, deployment_window)
    return errors


def _validate_environments(environments: object) -> list[str]:
    """Check the ``environments`` mapping and each of its entries."""
    if environments is None:
        return []
    if not isinstance(environments, dict) or not environments:
        return ["'environments' must be a non-empty mapping"]

    errors: list[str] = []
    for env_name, env_block in environments.items():
        errors += _validate_environment_block(env_name, env_block)
    return errors


def _validate_promotion_chain(promotion_chain: object, environments: object) -> list[str]:
    """Check ``promotion_chain`` shape and that it matches ``environments``."""
    if promotion_chain is None:
        return []
    if not isinstance(promotion_chain, list):
        return ["'promotion_chain' must be a list"]
    if not isinstance(environments, dict):
        return []

    errors: list[str] = []
    env_names = set(environments.keys())
    chain_names = set(promotion_chain)
    missing_in_chain = env_names - chain_names
    if missing_in_chain:
        errors.append(f"Environments missing from promotion_chain: {sorted(missing_in_chain)}")
    unknown_in_chain = chain_names - env_names
    if unknown_in_chain:
        errors.append(f"Unknown environments in promotion_chain: {sorted(unknown_in_chain)}")
    return errors


def validate_environments_yaml(path: Path) -> list[str]:
    """
    Validate environments.yml at the given path.

    Returns a list of error messages. An empty list indicates the file is valid.
    """
    if not path.exists():
        return [f"File not found: {path}"]

    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return [f"Invalid YAML in {path}: {exc}"]

    if not isinstance(config, dict):
        return [f"Top level of {path} must be a mapping, got {type(config).__name__}"]

    environments = config.get("environments")
    return (
        _validate_top_level_keys(config)
        + _validate_environments(environments)
        + _validate_promotion_chain(config.get("promotion_chain"), environments)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate environments.yml schema"
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help=(
            "Path to environments.yml (default: the first of .fab-test/metadata/ "
            "or .github/metadata/)"
        ),
    )
    args = parser.parse_args(argv)

    path = args.path
    if path is None:
        try:
            path = resolve_environments_yml().path
        except MetadataNotFoundError as exc:
            _error(str(exc))
            return 1

    errors = validate_environments_yaml(path)
    if errors:
        _error(f"Validation failed for {path}")
        for error in errors:
            _error(error)
        return 1

    _info(f"{path} is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
