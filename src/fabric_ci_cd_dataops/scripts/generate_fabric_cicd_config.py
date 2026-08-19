#!/usr/bin/env python3
"""
Generate a fabric-cicd deployment config for a specific environment.

Reads `.github/metadata/environments.yml`, resolves the workspace ID
from the environment block, and writes a minimal config that `fabric-cicd`
can consume directly.

Usage:
    python scripts/generate_fabric_cicd_config.py \
        --environment <name> \
        [--workspace-id <id>] \
        [--output <path>] \
        [--terse]

Exit codes:
    0  Config generated successfully
    1  Error during generation
"""
import argparse
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required to load environments.yml", file=sys.stderr)
    sys.exit(1)

from ._cli_utils import terse_print


def load_config(repo_root: Path) -> dict:
    config_path = repo_root / ".github" / "metadata" / "environments.yml"
    if not config_path.exists():
        print(f"Error: environments.yml not found at {config_path}", file=sys.stderr)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def build_environment_config(config: dict, environment: str, workspace_id: str) -> dict:
    defaults = config.get("defaults", {})
    env_block = config.get("environments", {}).get(environment)
    if not env_block:
        print(f"Error: Environment '{environment}' not found in environments.yml", file=sys.stderr)
        sys.exit(1)

    merged = dict(defaults)
    merged.update(env_block)

    if not workspace_id:
        workspace_id = merged.get("workspace_id", "")

    if not workspace_id:
        print(f"Error: workspace_id is empty for environment '{environment}'", file=sys.stderr)
        print("Set it in environments.yml or via the FABRIC_WORKSPACE_ID secret.", file=sys.stderr)
        sys.exit(1)

    merged["workspace_id"] = workspace_id

    # Remove non-fabric-cicd keys before writing the deployment config
    for key in [
        "description",
        "allowed_branches",
        "promotion_target",
        "previous_environment",
        "requires_validation",
        "requires_security_scan",
        "requires_ai_validation",
        "allows_rollback",
        "deployment_window",
        "approval_required",
    ]:
        merged.pop(key, None)

    return merged


def main():
    parser = argparse.ArgumentParser(description="Generate fabric-cicd config for an environment")
    parser.add_argument("--environment", required=True, help="Target environment (testbed, dev, test, prod)")
    parser.add_argument("--workspace-id", default=os.getenv("FABRIC_WORKSPACE_ID", ""), help="Fabric workspace ID")
    parser.add_argument("--output", default="fabric-cicd-env-config.yml", help="Output config file path")
    parser.add_argument(
        "--terse",
        action="store_true",
        help=(
            "Emit machine-readable one-line summaries (OK/ERROR prefix). "
            "Suppresses decorative output; retains actionable context for agents."
        ),
    )
    args = parser.parse_args()
    terse = args.terse

    repo_root = Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve()
    config = load_config(repo_root)
    env_config = build_environment_config(config, args.environment, args.workspace_id)

    with open(args.output, "w") as f:
        yaml.safe_dump(env_config, f, default_flow_style=False, sort_keys=False)

    terse_print(
        terse, "OK", "generate_config",
        f"{args.output} generated for {args.environment} (workspace={env_config['workspace_id']})",
    )
    if not terse:
        print(f"Generated fabric-cicd config: {args.output}")
        print(f"Environment: {args.environment}")
        print(f"Workspace ID: {env_config['workspace_id']}")


if __name__ == "__main__":
    main()
