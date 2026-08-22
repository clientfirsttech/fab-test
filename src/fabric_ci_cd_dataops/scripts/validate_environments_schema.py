#!/usr/bin/env python3
"""
Validate the environments.yml schema.

Performs structural validation of `environments.yml` -- from
`.fab-test/metadata/` or `.github/metadata/` -- to catch
configuration errors early — before they surface as cryptic deployment failures.

Checks:
  - Required top-level keys: defaults, environments, promotion_chain
  - defaults block: repository_directory, item_type_in_scope
  - Each environment: description, workspace_id, allowed_branches, promotion_target,
    requires_validation, requires_security_scan, requires_ai_validation
  - promotion_chain matches the set of declared environments
  - Deployment window fields when present (prod)

Usage:
    python scripts/validate_environments_schema.py [--file PATH] [--terse]

Exit codes:
    0  All checks passed
    1  One or more schema violations found
"""

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR yaml_import: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from ._cli_utils import terse_print
from ._metadata import MetadataNotFoundError, resolve_environments_yml

# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = ["defaults", "environments", "promotion_chain"]
REQUIRED_DEFAULTS = ["repository_directory", "item_type_in_scope"]
REQUIRED_ENV_KEYS = [
    "description",
    "workspace_id",
    "allowed_branches",
    "promotion_target",
    "requires_validation",
    "requires_security_scan",
    "requires_ai_validation",
]
OPTIONAL_ENV_KEYS = [
    "previous_environment",
    "allows_rollback",
    "deployment_window",
    "approval_required",
]
DEPLOYMENT_WINDOW_KEYS = ["enabled", "allowed_days", "allowed_hours_utc"]


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

class ValidationError:
    """Single schema violation."""

    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message

    def terse(self) -> str:
        return f"ERROR {self.path}: {self.message}"

    def verbose(self) -> str:
        return f"  ❌  [{self.path}] {self.message}"


def validate(config: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []

    # --- Top-level keys ---
    errors.extend(
        ValidationError("root", f"Missing required key '{key}'")
        for key in REQUIRED_TOP_LEVEL
        if key not in config
    )

    if errors:
        # Cannot proceed without structure
        return errors

    # --- defaults block ---
    defaults = config.get("defaults", {})
    if not isinstance(defaults, dict):
        errors.append(ValidationError("defaults", "Must be a mapping"))
    else:
        errors.extend(
            ValidationError(f"defaults.{key}", "Missing required key")
            for key in REQUIRED_DEFAULTS
            if key not in defaults
        )

    # --- environments block ---
    environments = config.get("environments", {})
    if not isinstance(environments, dict) or not environments:
        errors.append(ValidationError("environments", "Must be a non-empty mapping"))
        return errors

    for env_name, env_block in environments.items():
        prefix = f"environments.{env_name}"

        if not isinstance(env_block, dict):
            errors.append(ValidationError(prefix, "Must be a mapping"))
            continue

        errors.extend(
            ValidationError(f"{prefix}.{key}", "Missing required key")
            for key in REQUIRED_ENV_KEYS
            if key not in env_block
        )

        # allowed_branches must be a list
        if "allowed_branches" in env_block:
            if not isinstance(env_block["allowed_branches"], list):
                errors.append(ValidationError(f"{prefix}.allowed_branches", "Must be a list"))
            elif not env_block["allowed_branches"]:
                errors.append(ValidationError(f"{prefix}.allowed_branches", "Must not be empty"))

        # boolean fields
        errors.extend(
            ValidationError(f"{prefix}.{bool_key}", "Must be a boolean")
            for bool_key in ("requires_validation", "requires_security_scan", "requires_ai_validation")
            if bool_key in env_block and not isinstance(env_block[bool_key], bool)
        )

        # deployment_window — optional but validated when present
        dw = env_block.get("deployment_window")
        if dw is not None:
            if not isinstance(dw, dict):
                errors.append(ValidationError(f"{prefix}.deployment_window", "Must be a mapping"))
            else:
                errors.extend(
                    ValidationError(
                        f"{prefix}.deployment_window.{dw_key}",
                        "Missing required deployment_window key",
                    )
                    for dw_key in DEPLOYMENT_WINDOW_KEYS
                    if dw_key not in dw
                )

    # --- promotion_chain ---
    chain = config.get("promotion_chain", [])
    if not isinstance(chain, list) or not chain:
        errors.append(ValidationError("promotion_chain", "Must be a non-empty list"))
    else:
        declared_envs = set(environments.keys())
        chain_set = set(chain)
        extra = chain_set - declared_envs
        missing = declared_envs - chain_set
        if extra:
            errors.append(
                ValidationError(
                    "promotion_chain",
                    f"References environment(s) not declared in 'environments': {sorted(extra)}",
                )
            )
        if missing:
            errors.append(
                ValidationError(
                    "promotion_chain",
                    f"Declared environment(s) not listed in 'promotion_chain': {sorted(missing)}",
                )
            )

    return errors


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _resolve_config_path(explicit: str | None, terse: bool) -> Path:
    """Return the environments.yml to validate, or exit 1 saying where it looked.

    Extracted from `main` rather than inlined: `main` was already one branch
    under the complexity ceiling that `tests/test_complexity_budget.py`
    ratchets, and the layer search adds two.
    """
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
        msg = f"File not found: {path}"
        terse_print(terse, "ERROR", "file_not_found", msg)
        if not terse:
            print(f"❌  {msg}", file=sys.stderr)
        sys.exit(1)
    try:
        return resolve_environments_yml().path
    except MetadataNotFoundError as exc:
        terse_print(terse, "ERROR", "file_not_found", str(exc))
        if not terse:
            print(f"❌  {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate environments.yml schema",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit 0 = valid, Exit 1 = schema violations found.",
    )
    parser.add_argument(
        "--file",
        default=None,
        help=(
            "Path to environments.yml (default: the first of .fab-test/metadata/ "
            "or .github/metadata/)"
        ),
    )
    parser.add_argument(
        "--terse",
        action="store_true",
        help=(
            "Emit machine-readable one-line summaries (ERROR/OK prefix). "
            "Suppresses decorative output; retains actionable context for agents."
        ),
    )
    args = parser.parse_args()

    config_path = _resolve_config_path(args.file, args.terse)

    with open(config_path) as f:
        try:
            config = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            msg = f"YAML parse error: {exc}"
            terse_print(args.terse, "ERROR", "yaml_parse", msg)
            if not args.terse:
                print(f"❌  {msg}", file=sys.stderr)
            sys.exit(1)

    errors = validate(config)

    if args.terse:
        env_count = len(config.get("environments", {}))
        chain_len = len(config.get("promotion_chain", []))
        if errors:
            print(f"FAIL environments_schema: {len(errors)} violation(s) in {config_path}")
            for err in errors:
                print(err.terse())
        else:
            print(
                f"OK environments_schema: {config_path} valid "
                f"({env_count} environments, chain_length={chain_len})"
            )
    else:
        print(f"\n🔍 Validating: {config_path}\n")
        if errors:
            print(f"{'─' * 60}")
            print(f"Schema violations found: {len(errors)}")
            print(f"{'─' * 60}")
            for err in errors:
                print(err.verbose())
            print(f"{'─' * 60}\n")
        else:
            env_count = len(config.get("environments", {}))
            chain = config.get("promotion_chain", [])
            print("  ✅  environments.yml is valid")
            print(f"      Environments : {env_count} ({', '.join(config.get('environments', {}).keys())})")
            print(f"      Chain        : {' → '.join(chain)}")
            print()

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
