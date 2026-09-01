#!/usr/bin/env python3
"""Manual validation script for Fabric service client dependency discovery.

Usage:
    python scripts/validate_fabric_service_client.py \
        --semantic-model "Sales Model" \
        --env dev \
        --format json

This script proves the dependency API contract against a live Fabric tenant
before the integration is wired into ``fab-test``. It is safe to run by hand
and should never be invoked automatically in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .playwright_validation.fabric_service_client import (
    FabricServiceClientError,
    build_fabric_service_client,
)
from .playwright_validation.resolver import (
    ResolvedReport,
    ServiceResolutionError,
    resolve_environment,
    resolve_semantic_model_dependents,
)


def _repo_root() -> Path:
    """Return the repository root."""
    workspace = __import__("os").getenv("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    return Path.cwd().resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Validate Fabric service client dependency discovery against a live "
            "Fabric tenant."
        )
    )
    parser.add_argument(
        "--semantic-model",
        required=True,
        help="Name of the deployed semantic model.",
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
        "--workspace-id",
        default="",
        help="Explicit workspace ID override.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args(argv)


def _emit_text(reports: list[ResolvedReport]) -> None:
    """Print dependent reports as human-readable text."""
    if not reports:
        print("No dependent reports found in scope.")
        return
    print(f"Dependent reports ({len(reports)}):")
    for report in reports:
        print(
            f"  - {report.report_name} "
            f"(report={report.report_id}, workspace={report.workspace_id}, "
            f"semantic_model={report.semantic_model_id})"
        )


def _emit_json(reports: list[ResolvedReport]) -> None:
    """Print dependent reports as JSON."""
    data: dict[str, Any] = {
        "total": len(reports),
        "reports": [
            {
                "workspace_id": report.workspace_id,
                "report_id": report.report_id,
                "report_name": report.report_name,
                "semantic_model_id": report.semantic_model_id,
                "environment": report.environment,
            }
            for report in reports
        ],
    }
    print(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    """Entry point for manual validation."""
    args = parse_args(argv)

    try:
        client = build_fabric_service_client(
            env_file=args.env_file,
        )
        resolved_env = resolve_environment(
            args.env,
            workspace_id_override=args.workspace_id,
        )
    except (ServiceResolutionError, FabricServiceClientError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    print(
        f"Resolved environment: {resolved_env.environment} "
        f"(workspace={resolved_env.workspace_id})"
    )
    print(f"Semantic model: {args.semantic_model}")

    try:
        reports = resolve_semantic_model_dependents(
            args.semantic_model,
            resolved_env,
            client,
        )
    except ServiceResolutionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        _emit_json(reports)
    else:
        _emit_text(reports)

    return 0


if __name__ == "__main__":
    sys.exit(main())
