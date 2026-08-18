#!/usr/bin/env python3
"""CLI command to discover dependent reports for a semantic model.

Usage:
    python scripts/invoke_playwright_dependencies.py \
        --semantic-model SalesModel \
        --env dev \
        --output manifest.json

The command resolves the environment and semantic model from service metadata,
queries the Fabric dependency API, and emits the dependent reports as text or
JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .playwright_validation.config import PlaywrightValidationConfig, load_config
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
    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    return Path.cwd().resolve()


def _resolve_client(
    args: argparse.Namespace,
) -> tuple[Any, PlaywrightValidationConfig]:
    """Load credentials and build a Fabric service client."""
    config = load_config(args.env_file, required=False)
    client = build_fabric_service_client(
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
        cloud=config.cloud,
        env_file=args.env_file,
    )
    return client, config


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Discover reports that depend on a deployed semantic model."
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
        "--output",
        help="Path to write JSON manifest. If omitted, prints to stdout.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--workspace-id",
        default="",
        help="Explicit workspace ID override.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for dependency discovery."""
    args = parse_args(argv)

    try:
        client, config = _resolve_client(args)
    except (ServiceResolutionError, FabricServiceClientError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    try:
        resolved_env = resolve_environment(
            args.env,
            workspace_id_override=args.workspace_id or config.workspace_id,
        )
    except ServiceResolutionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    try:
        reports = resolve_semantic_model_dependents(
            args.semantic_model,
            resolved_env,
            client,
        )
    except ServiceResolutionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
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
                },
                fh,
                indent=2,
            )
        print(f"Wrote dependency manifest to {output_path}")
    elif args.format == "json":
        _emit_json(reports)
    else:
        _emit_text(reports)

    return 0


if __name__ == "__main__":
    sys.exit(main())
