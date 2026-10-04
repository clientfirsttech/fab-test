"""Registry helpers for the data-agent analyzer."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from ._analyzer_tool_bootstrap import probe_executable


def data_agent_explicit_path(args: argparse.Namespace | None) -> str | None:
    """Return the explicit promptfoo path, if one was supplied."""
    return getattr(args, "promptfoo_path", None) if args is not None else None


def build_data_agent_command(artifact: Path, args: argparse.Namespace, output_dir: Path) -> list[str]:
    """Build the promptfoo-backed Data Agent command for ``artifact``."""
    promptfoo_path = getattr(args, "_resolved_tool_path", None) or data_agent_explicit_path(args) or os.getenv(
        "PROMPTFOO_PATH", ""
    )
    output = output_dir / "data_agent" / artifact.stem / "envelope.json"
    cmd = [
        sys.executable,
        "-m",
        "fab_test.scripts.invoke_data_agent",
        "--artifact-path",
        str(artifact),
        "--artifact-name",
        artifact.stem,
        "--workspace-id",
        getattr(args, "workspace_id", "") or os.getenv("FABRIC_WORKSPACE_ID", ""),
        "--output-path",
        str(output),
    ]
    if promptfoo_path:
        cmd += ["--promptfoo-path", str(promptfoo_path)]
    env_file = getattr(args, "data_agent_env_file", None)
    if env_file:
        cmd += ["--env-file", str(env_file)]
    return cmd


def data_agent_readiness(
    args: argparse.Namespace | None,
    analyzers_json: Path,
    repo_root: Path,
    cloud_readiness,
) -> dict[str, Any]:
    """Combine promptfoo tool readiness with service-principal readiness."""
    tool = probe_executable(
        "data_agent",
        analyzers_json,
        repo_root,
        explicit_path=data_agent_explicit_path(args),
    )
    if not tool["ready"]:
        return tool
    cloud = cloud_readiness("data_agent", args)
    cloud["resolved_path"] = tool.get("resolved_path")
    if cloud["ready"]:
        cloud["reason"] = f"{tool['reason']}; {cloud['reason']}"
    return cloud
