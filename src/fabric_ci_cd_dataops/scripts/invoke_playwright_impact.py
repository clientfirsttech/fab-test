#!/usr/bin/env python3
"""CLI command to build an impacted-report manifest from changed artifacts.

Usage:
    python scripts/invoke_playwright_impact.py \
        --changed-artifacts changed-artifacts.json \
        --env dev \
        --output analyzer-results/playwright/impact-manifest.json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .playwright_validation.config import load_config
from .playwright_validation.fabric_service_client import (
    FabricServiceClientError,
    build_fabric_service_client,
)
from .playwright_validation.impact import build_impact_manifest
from .playwright_validation.resolver import ServiceResolutionError


def _repo_root() -> Path:
    """Return the repository root."""
    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    return Path.cwd().resolve()





def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build an impacted-report manifest from changed artifacts."
    )
    parser.add_argument(
        "--changed-artifacts",
        required=True,
        help="Path to changed-artifacts.json from detect_changes.py.",
    )
    parser.add_argument(
        "--env",
        required=True,
        help="Target environment label (e.g. dev, test, prod).",
    )
    parser.add_argument(
        "--env-file",
        help="Path to .env file with service principal credentials.",
    )
    parser.add_argument(
        "--output",
        help="Path for the JSON impact manifest.",
    )
    parser.add_argument(
        "--workspace-id",
        default="",
        help="Explicit workspace ID override.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for impact manifest generation."""
    args = parse_args(argv)

    try:
        config = load_config(args.env_file, required=False)
        client = build_fabric_service_client(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            cloud=config.cloud,
            env_file=args.env_file,
        )
        manifest = build_impact_manifest(
            Path(args.changed_artifacts).resolve(),
            args.env,
            client,
            workspace_id_override=args.workspace_id or config.workspace_id,
        )
    except (ServiceResolutionError, FabricServiceClientError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if manifest.reports:
        print(
            f"Impact manifest: {len(manifest.reports)} report(s) to validate."
        )
    else:
        print("No impacted reports in scope.")

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = (
            _repo_root()
            / "analyzer-results"
            / "playwright"
            / "impact-manifest.json"
        )

    manifest.write(output_path)
    print(f"Wrote impact manifest to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
