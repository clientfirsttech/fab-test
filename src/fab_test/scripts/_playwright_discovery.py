"""Playwright-specific discovery helpers for fab-test execution."""

from __future__ import annotations

from pathlib import Path


def resolve_playwright_artifacts(
    args,
    discovered: list[Path],
    output_dir: Path,
    resolve_service_target,
    discover_rdl_files,
    resolve_remote_target,
    resolve_dataset_workspace_artifact,
) -> list[Path]:
    """Return the effective Playwright artifact list for this invocation."""
    resolved = resolve_service_target(args)
    if resolved is not None:
        return resolved
    discovered = discovered + discover_rdl_files(args, output_dir)
    if discovered:
        return discovered
    remote = resolve_remote_target(args)
    if remote is not None:
        return [remote]
    dataset_remote = resolve_dataset_workspace_artifact(args)
    if dataset_remote is not None:
        return dataset_remote
    return discovered
