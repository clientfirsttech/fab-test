"""Dataset-targeted Playwright runs: the reports built on one dataset, or on
every dataset in a workspace.

`fab-test playwright --dataset-id X` with no report named used to fall into
batch discovery -- every local report under `--artifact-dir`, each one
force-rebound to dataset X. Naming a dataset without naming a report now
means "the reports that depend on it", resolved live, one synthetic
`NAME.Report` target per dependent so each still gets its own subprocess,
envelope, and summary row (Playwright Dataset Target epic).

`--dataset-workspace-id` alone -- no `--dataset-id`, no report named -- used
to refuse outright, and `--dataset-workspace-id` with a bare `--artifact`
that had no local match fell into ordinary discovery with no way to resolve
the workspace, reporting "no *.Report artifacts found" even though the
service principal could see the report fine. Both are real behavior now:
a lone `--dataset-workspace-id` means "every dataset in this workspace",
and pairing it with `--artifact NAME` refines to that one report or that
one dataset's reports, whichever `NAME` turns out to be (Playwright Dataset
Target epic, live use against a real workspace).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ._cli_utils import narrate
from ._credentials import configured_workspace
from ._target import target_from_args

# `args` attributes build_playwright_command reads back, all keyed by each
# synthetic target's stem: the workspace the report lives in and its real
# display name (dependents of one dataset can live in more than one
# workspace, and two distinct reports -- different IDs, different
# workspaces -- can share a display name, so the stem is disambiguated for
# the synthetic Path while --artifact still needs the real name to
# resolve), and -- only when a single run can span more than one dataset,
# i.e. "every dataset in a workspace" -- the dataset each report is bound to.
REPORT_WORKSPACES_ATTR = "playwright_report_workspaces"
REPORT_NAMES_ATTR = "playwright_report_names"
REPORT_DATASETS_ATTR = "playwright_report_datasets"


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


def _resolve_target_workspace(args: argparse.Namespace) -> str:
    """Best-known workspace for the two workspace-only modes below.

    In order: `--dataset-workspace-id`, then `--workspace-id` /
    `FABRIC_WORKSPACE_ID` / `workspace:` in fab-test.yml (`configured_workspace`),
    then `--env` resolved through `environments.yml` -- the same fallback
    chain every other workspace-consuming flag already honors, so `--env`
    alone is enough to drive either mode. Does not raise: a resolution
    failure here just means "no workspace known", for the caller to report.
    """
    workspace = getattr(args, "dataset_workspace_id", "") or configured_workspace(args, playwright=True)
    if workspace:
        return workspace
    environment = getattr(args, "environment", "") or os.getenv("FABRIC_ENVIRONMENT", "")
    if not environment:
        return ""

    from .playwright_validation.resolver import ServiceResolutionError, resolve_environment

    try:
        return resolve_environment(environment).workspace_id
    except ServiceResolutionError:
        return ""


def dataset_workspace_only_requested(args: argparse.Namespace) -> bool:
    """True when `--dataset-workspace-id` is given and nothing else narrows
    the run to one dataset or one report -- every semantic model in that
    workspace gets its own dependents run.

    Keyed off the literal `--dataset-workspace-id` flag, not `--env`: a
    plain `fab-test playwright --env dev` batch run with nothing local to
    discover must not be silently reinterpreted as "every dataset in this
    workspace" -- that would hijack an ordinary, long-working invocation.
    """
    return bool(
        getattr(args, "dataset_workspace_id", "")
        and not getattr(args, "dataset_id", "")
        and not getattr(args, "impact_manifest", None)
        and target_from_args(args) is None
    )


def resolve_dataset_workspace_targets(args: argparse.Namespace) -> list[Path]:
    """Return one synthetic ``NAME.Report`` target per report dependent on
    *any* semantic model in the named workspace.

    Mirrors `resolve_dataset_targets` below, but for every dataset in the
    workspace at once rather than one named by `--dataset-id` -- each
    dependent report is tagged with its own dataset's ID (`REPORT_DATASETS_ATTR`),
    since two reports in this list can be bound to two different datasets.

    Raises:
        DatasetTargetExit: 2 when no workspace names where to look, 1 when
            a lookup fails.
    """
    output_format = getattr(args, "output_format", "text")
    workspace_id = _resolve_target_workspace(args)
    if not workspace_id:
        print(
            "  ✗ fab-test playwright: --dataset-workspace-id names no workspace to find its "
            "semantic models in. Pass --dataset-workspace-id, --workspace-id / "
            "FABRIC_WORKSPACE_ID, or --env (resolved via environments.yml).",
            file=sys.stderr,
        )
        raise DatasetTargetExit(2)

    from .playwright_validation.fabric_service_client import (
        FabricServiceClientError,
        build_fabric_service_client,
    )
    from .playwright_validation.resolver import ServiceResolutionError, resolve_workspace_id

    try:
        client = build_fabric_service_client(env_file=getattr(args, "playwright_env_file", None))
        workspace_id = resolve_workspace_id(client, workspace_id)
        models = client.list_items(workspace_id, "SemanticModel")
    except (FabricServiceClientError, ServiceResolutionError) as exc:
        print(
            f"  ✗ fab-test playwright: could not list semantic models in workspace {workspace_id}: {exc}",
            file=sys.stderr,
        )
        raise DatasetTargetExit(1) from exc

    if not models:
        narrate(
            f"  ⚠ fab-test playwright: no semantic models found in workspace {workspace_id}",
            output_format=output_format,
        )
        return []

    reports: dict[str, tuple[str, str, str]] = {}  # report id -> (name, workspace id, dataset id)
    try:
        for model in models:
            model_id = model.get("id", "")
            for dep in client.get_dependent_reports(workspace_id, model_id):
                reports.setdefault(
                    dep["id"],
                    (dep.get("displayName") or dep["id"], dep.get("workspaceId") or workspace_id, model_id),
                )
    except FabricServiceClientError as exc:
        print(
            f"  ✗ fab-test playwright: could not list dependent reports in workspace {workspace_id}: {exc}",
            file=sys.stderr,
        )
        raise DatasetTargetExit(1) from exc

    if not reports:
        narrate(
            f"  ⚠ fab-test playwright: {len(models)} semantic model(s) in workspace {workspace_id}, "
            "none with dependent reports",
            output_format=output_format,
        )
        return []

    report_workspaces, report_names, report_datasets = _disambiguate_stems_with_dataset(reports)
    setattr(args, REPORT_WORKSPACES_ATTR, report_workspaces)
    setattr(args, REPORT_NAMES_ATTR, report_names)
    setattr(args, REPORT_DATASETS_ATTR, report_datasets)
    stems = list(report_workspaces)
    narrate(
        f"  fab-test playwright: {len(models)} semantic model(s), {len(stems)} report(s) in "
        f"workspace {workspace_id}: " + ", ".join(stems),
        output_format=output_format,
    )
    return [Path(f"{stem}.Report") for stem in stems]


def dataset_workspace_artifact_requested(args: argparse.Namespace) -> bool:
    """True when `--dataset-workspace-id` is given with a bare artifact/target
    and no `--dataset-id` -- eligible for `resolve_dataset_workspace_artifact`'s
    Fabric-side report-vs-dataset disambiguation.

    Mirrors `_playwright_remote_target`'s own guard: a real filesystem path
    (`./src/Sales.Report`) is left alone, since naming a specific location
    and finding nothing there is a real miss, not a signal to look remotely.
    """
    target = target_from_args(args)
    if target is None or target.scope not in ("path", "workspace"):
        return False
    if target.scope == "path" and target.path is not None:
        return False
    return bool(
        getattr(args, "dataset_workspace_id", "")
        and not getattr(args, "dataset_id", "")
        and not getattr(args, "impact_manifest", None)
    )


def resolve_dataset_workspace_artifact(args: argparse.Namespace) -> list[Path] | None:
    """Last-resort fallback for `--dataset-workspace-id` with a bare artifact/target,
    once local discovery under `--artifact-dir` has already found nothing and
    `_playwright_remote_target` has no other workspace to resolve it with.

    Resolves the named artifact against Fabric to tell a report from a
    dataset: a dataset's dependent reports run (mirroring `--dataset-id`
    mode, the dataset named by display name instead); a name that is not a
    dataset resolves as a normal single-report target, with the workspace
    stashed on ``args`` as a fallback so the subprocess needs nothing else.

    Returns:
        The resolved target list, or ``None`` when this mode does not apply
        at all -- the caller's ordinary empty-discovery narration still fires.

    Raises:
        DatasetTargetExit: 1 when resolving the name against Fabric fails.
    """
    if not dataset_workspace_artifact_requested(args):
        return None
    target = target_from_args(args)
    name = target.name
    workspace_id = _resolve_target_workspace(args)
    if not workspace_id:
        return None

    from .playwright_validation.fabric_service_client import (
        FabricServiceClientError,
        build_fabric_service_client,
    )
    from .playwright_validation.resolver import (
        ItemNotFoundError,
        ResolvedEnvironment,
        ServiceResolutionError,
        resolve_item,
        resolve_workspace_id,
    )

    try:
        client = build_fabric_service_client(env_file=getattr(args, "playwright_env_file", None))
        workspace_id = resolve_workspace_id(client, workspace_id)
        resolved_env = ResolvedEnvironment(environment="", workspace_id=workspace_id)
        dataset = resolve_item(name, "SemanticModel", resolved_env, client)
    except ItemNotFoundError:
        if not getattr(args, "workspace_id", ""):
            args.workspace_id = workspace_id
        return [Path(name)]
    except (FabricServiceClientError, ServiceResolutionError) as exc:
        print(
            f"  ✗ fab-test playwright: could not resolve '{name}' in workspace {workspace_id}: {exc}",
            file=sys.stderr,
        )
        raise DatasetTargetExit(1) from exc

    args.dataset_id = dataset.item_id
    if not getattr(args, "dataset_workspace_id", ""):
        args.dataset_workspace_id = workspace_id
    return resolve_dataset_targets(args)


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


def _disambiguate_stems_with_dataset(
    reports: dict[str, tuple[str, str, str]],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Same disambiguation as `_disambiguate_stems`, carrying each stem's own
    dataset ID too.

    Kept as a sibling rather than folded into `_disambiguate_stems`: only
    "every dataset in a workspace" mode needs a per-report dataset override
    -- single-dataset mode already has one shared `args.dataset_id` for the
    whole run, and giving every report its own entry there would be a
    distinction without a difference.
    """
    by_name: dict[str, list[str]] = {}
    for report_id, (name, _workspace_id, _dataset_id) in reports.items():
        by_name.setdefault(name, []).append(report_id)

    report_workspaces: dict[str, str] = {}
    report_names: dict[str, str] = {}
    report_datasets: dict[str, str] = {}
    for report_id, (name, workspace_id, dataset_id) in reports.items():
        stem = name if len(by_name[name]) == 1 else f"{name} ({workspace_id})"
        if stem in report_workspaces:
            stem = f"{stem} [{report_id}]"
        report_workspaces[stem] = workspace_id
        report_names[stem] = name
        report_datasets[stem] = dataset_id
    return report_workspaces, report_names, report_datasets
