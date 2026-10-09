"""`fab-test playwright --workspace WS --changed-since REF`: only the reports a change touches.

Git says which Fabric artifacts changed since REF; Fabric says which
deployed reports in WS are built on those models or are those reports.
Only those run. It is a service run -- the reports under test are the
deployed ones -- so it needs `--workspace`, and Git only when it is used.

Each affected report becomes a synthetic ``NAME.Report`` target carrying its
workspace and display name on ``args``, exactly like a standalone
`--workspace` run, so the rest of Playwright runs them unchanged.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn

from ._cli_utils import narrate
from ._playwright_dataset_target import (
    REPORT_NAMES_ATTR,
    REPORT_TYPES_ATTR,
    REPORT_WORKSPACES_ATTR,
    DatasetTargetExit,
    _disambiguate_stems,
)
from .detect_changes import ChangeDetectionError, changed_artifacts_since
from .playwright_validation.fabric_service_client import (
    FabricServiceClientError,
    build_fabric_service_client,
)


def changed_since_requested(args: argparse.Namespace) -> bool:
    """True when `--changed-since` names a ref to compare against."""
    return bool(getattr(args, "changed_since", ""))


def _refuse(message: str, code: int) -> NoReturn:
    print(f"  ✗ fab-test playwright: {message}", file=sys.stderr)
    raise DatasetTargetExit(code)


def resolve_changed_reports(args: argparse.Namespace) -> list[Path]:
    """Return one target per deployed report affected by changes since ``--changed-since``.

    Raises:
        DatasetTargetExit: 0 when nothing changed or nothing deployed is
            affected, 2 without `--workspace` or for a ref Git cannot
            resolve (both before any network call), 1 when Fabric fails.
    """
    from .playwright_validation.impact import build_impact_manifest
    from .playwright_validation.resolver import ServiceResolutionError, resolve_workspace_id

    ref = args.changed_since
    output_format = getattr(args, "output_format", "text")
    if getattr(getattr(args, "resolved_mode", None), "mode", "") != "service":
        _refuse("--changed-since tests the deployed reports in a workspace; name it with --workspace", 2)
    try:
        artifacts = changed_artifacts_since(Path(getattr(args, "artifact_dir", ".")), ref)
    except ChangeDetectionError as exc:
        _refuse(str(exc), 2)
    if not artifacts:
        narrate(f"  fab-test playwright: no Fabric artifacts changed since {ref}; nothing to test",
                output_format=output_format)
        raise DatasetTargetExit(0)

    try:
        client = build_fabric_service_client(env_file=getattr(args, "playwright_env_file", None))
        workspace_id = resolve_workspace_id(client, args.workspace_id)
        manifest = build_impact_manifest(
            artifacts, getattr(args, "environment", ""), client, workspace_id_override=workspace_id
        )
    except (FabricServiceClientError, ServiceResolutionError) as exc:
        _refuse(f"could not find the reports affected by changes since {ref}: {exc}", 1)
    # Two folders can share a name (fixtures in different directories); say it once.
    for skipped in dict.fromkeys(manifest.skipped):
        narrate(f"  ⏭ {skipped}", output_format=output_format)
    if not manifest.reports:
        narrate(
            f"  fab-test playwright: {len(artifacts)} artifact(s) changed since {ref}, but no deployed "
            f"report in workspace {args.workspace_id} uses them; nothing to test",
            output_format=output_format,
        )
        raise DatasetTargetExit(0)

    reports = {entry.report_id: (entry.report_name, entry.workspace_id) for entry in manifest.reports}
    types = {entry.report_id: entry.report_type for entry in manifest.reports}
    report_workspaces, report_names = _disambiguate_stems(reports)
    setattr(args, REPORT_WORKSPACES_ATTR, report_workspaces)
    setattr(args, REPORT_NAMES_ATTR, report_names)
    # One stem per report ID, in the same order.
    setattr(args, REPORT_TYPES_ATTR, {
        stem: types[report_id] for stem, report_id in zip(report_workspaces, reports, strict=True)
    })
    narrate(
        f"  fab-test playwright: {len(report_workspaces)} report(s) affected by changes since {ref}: "
        + ", ".join(report_workspaces),
        output_format=output_format,
    )
    return [Path(f"{stem}.Report") for stem in report_workspaces]
