"""Dataset-targeted Playwright runs: the reports built on one dataset.

`fab-test playwright --dataset-id X` with no report named used to fall into
batch discovery -- every local report under `--artifact-dir`, each one
force-rebound to dataset X. Naming a dataset without naming a report now
means "the reports that depend on it", resolved live, one synthetic
`NAME.Report` target per dependent so each still gets its own subprocess,
envelope, and summary row (Playwright Dataset Target epic).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._cli_utils import narrate
from ._credentials import configured_workspace
from ._target import target_from_args

# `args` attributes build_playwright_command reads back, both keyed by each
# synthetic target's stem: the workspace the report lives in (dependents of
# one dataset can live in more than one workspace), and the report's real
# display name when that differs from the stem -- two distinct reports (
# different IDs, different workspaces) can share a display name, and the
# stem is disambiguated for the synthetic Path while --artifact still needs
# the real name to resolve.
REPORT_WORKSPACES_ATTR = "playwright_report_workspaces"
REPORT_NAMES_ATTR = "playwright_report_names"


class DatasetTargetExit(Exception):
    """Stop the analyzer run with ``code``; the message is already printed."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def dataset_target_requested(args: argparse.Namespace) -> bool:
    """True when `--dataset-id` was given and nothing else names what to run.

    Keyed off the CLI flag only: `PLAYWRIGHT_DATASET_ID` in a `.env` belongs
    to the single-report static config and must not switch modes.
    """
    return bool(
        getattr(args, "dataset_id", "")
        and not getattr(args, "impact_manifest", None)
        and target_from_args(args) is None
    )


def refuse_dataset_workspace_without_dataset_id(args: argparse.Namespace) -> None:
    """Refuse a batch run left ambiguous by `--dataset-workspace-id` alone.

    `_dataset_override_for_command` applies an explicit
    `--dataset-workspace-id` unconditionally, to every artifact discovery
    finds -- with no `--dataset-id` to say *which* dataset it names the
    workspace of, and no `--artifact`/target/`--impact-manifest` naming one
    report either, that would force every locally discovered report onto
    that workspace instead, commonly one the caller's service principal has
    no access to at all. Raises before any artifact runs; a single-report
    override (`--artifact`, a target, or `--impact-manifest`) is unaffected.

    Raises:
        DatasetTargetExit: 2, always, when called for an ambiguous batch.
    """
    if (
        not getattr(args, "dataset_workspace_id", "")
        or getattr(args, "dataset_id", "")
        or getattr(args, "impact_manifest", None)
        or target_from_args(args) is not None
    ):
        return
    workspace_id = args.dataset_workspace_id
    print(
        f"  ✗ fab-test playwright: --dataset-workspace-id {workspace_id} with no --dataset-id "
        "would force every locally discovered report onto that workspace's dataset instead of "
        "targeting one. Pass --dataset-id too (to test that dataset's own reports), or --artifact "
        "NAME / a target (to override one report's dataset workspace).",
        file=sys.stderr,
    )
    raise DatasetTargetExit(2)


def _lookup_workspaces(args: argparse.Namespace) -> list[str]:
    """The dataset's workspace, then the report workspace the run itself would
    target, deduplicated."""
    candidates = [
        getattr(args, "dataset_workspace_id", "") or "",
        configured_workspace(args, playwright=True),
    ]
    return list(dict.fromkeys(c for c in candidates if c))


def resolve_dataset_targets(args: argparse.Namespace) -> list[Path]:
    """Return one synthetic ``NAME.Report`` target per dependent report.

    An empty return means "found the dataset, nothing depends on it" --
    the caller's normal empty-discovery path already narrates and, under
    ``--format json``, emits the one JSON payload a caller expects; a
    second one printed from here would break `fab-test all --format json`.

    Raises:
        DatasetTargetExit: 2 when no workspace names where to look, 1 when
            the lookup fails.
    """
    dataset_id = args.dataset_id
    output_format = getattr(args, "output_format", "text")
    workspaces = _lookup_workspaces(args)
    if not workspaces:
        print(
            f"  ✗ fab-test playwright: --dataset-id {dataset_id} names no workspace to find "
            "its reports in. Pass --dataset-workspace-id (the dataset's workspace) or "
            "--workspace-id / FABRIC_WORKSPACE_ID / PLAYWRIGHT_WORKSPACE_ID (the reports' workspace).",
            file=sys.stderr,
        )
        raise DatasetTargetExit(2)

    from .playwright_validation.fabric_service_client import (
        FabricServiceClientError,
        build_fabric_service_client,
    )
    from .playwright_validation.resolver import ServiceResolutionError, resolve_workspace_id

    reports: dict[str, tuple[str, str]] = {}  # report id -> (name, workspace id)
    try:
        client = build_fabric_service_client(env_file=getattr(args, "playwright_env_file", None))
        # Two candidates (a dataset workspace and a report workspace) can
        # resolve to the same GUID; re-dedupe after resolution so that
        # workspace's dependents are listed once, not twice.
        workspaces = list(dict.fromkeys(resolve_workspace_id(client, ws) for ws in workspaces))
        for workspace_id in workspaces:
            for dep in client.get_dependent_reports(workspace_id, dataset_id):
                reports.setdefault(
                    dep["id"], (dep.get("displayName") or dep["id"], dep.get("workspaceId") or workspace_id)
                )
    except (FabricServiceClientError, ServiceResolutionError) as exc:
        print(
            f"  ✗ fab-test playwright: could not list reports on dataset {dataset_id}: {exc}",
            file=sys.stderr,
        )
        raise DatasetTargetExit(1) from exc

    if not reports:
        narrate(
            f"  ⚠ fab-test playwright: no reports depend on dataset {dataset_id} "
            f"in workspace(s) {', '.join(workspaces)}",
            output_format=output_format,
        )
        return []

    report_workspaces, report_names = _disambiguate_stems(reports)
    setattr(args, REPORT_WORKSPACES_ATTR, report_workspaces)
    setattr(args, REPORT_NAMES_ATTR, report_names)
    # Both dicts were built in the same order, keyed by stem -- either one's
    # keys give the stems in that same order.
    stems = list(report_workspaces)
    narrate(
        f"  fab-test playwright: {len(stems)} report(s) on dataset {dataset_id}: " + ", ".join(stems),
        output_format=output_format,
    )
    return [Path(f"{stem}.Report") for stem in stems]


def _disambiguate_stems(
    reports: dict[str, tuple[str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Turn ``report id -> (name, workspace id)`` into unique filesystem stems,
    returned as ``(stem -> workspace id, stem -> real display name)``.

    A display name is usually unique across a dataset's dependents, so the
    common case keeps the name as its own stem. Two different report IDs
    sharing a name (different workspaces) each get the workspace ID appended
    instead, so neither is silently dropped -- ``--artifact`` still gets the
    real, undisambiguated name via the second dict. Fabric does not forbid
    two items sharing both a name and a workspace either, so a report ID
    suffix is the last resort for that narrower collision.
    """
    by_name: dict[str, list[str]] = {}
    for report_id, (name, _workspace_id) in reports.items():
        by_name.setdefault(name, []).append(report_id)

    report_workspaces: dict[str, str] = {}
    report_names: dict[str, str] = {}
    for report_id, (name, workspace_id) in reports.items():
        stem = name if len(by_name[name]) == 1 else f"{name} ({workspace_id})"
        if stem in report_workspaces:
            stem = f"{stem} [{report_id}]"
        report_workspaces[stem] = workspace_id
        report_names[stem] = name
    return report_workspaces, report_names
