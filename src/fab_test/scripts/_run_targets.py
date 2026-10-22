"""Target resolution for ``fab-test`` runs: which workspace and artifacts a
run is aimed at, and the target recorded in ``run.json``.

Split out of ``fab_test_execution.py`` (Core Module Split), which keeps the
per-artifact process loop, preflight and the dry-run plan that consume these.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from ._credentials import configured_workspace
from ._fab_test_context import RESULTS_ROOT
from ._playwright_changed import changed_since_requested, resolve_changed_reports
from ._playwright_dataset_target import (
    dataset_target_requested,
    dataset_workspace_only_requested,
    resolve_dataset_targets,
    resolve_dataset_workspace_artifact,
    resolve_dataset_workspace_targets,
    resolve_workspace_reports,
    workspace_reports_requested,
)
from ._scan import find_rdl_files as _find_rdl_files
from ._service_export import (
    ServiceExportError,
    build_service_client,
    export_for_analyzer,
    is_service_run,
)
from ._target import target_from_args
from .fab_test_registry import (
    discover_artifacts as _discover,
)
from .fab_test_registry import (
    is_repository_scoped as _is_repository_scoped,
)
from .playwright_validation.resolver import resolve_workspace_id


def _manifest_target(args: argparse.Namespace) -> dict[str, Any] | None:
    """Return the resolved target as a plain dict for `run.json`, or None."""
    target = getattr(args, "resolved_target", None)
    if target is None:
        return None
    manifest = target.as_dict(getattr(args, "workspace_id", "") or "")
    mode = getattr(args, "resolved_mode", None)
    if manifest["workspace"] is None and mode is not None and mode.mode == "service":
        # `--workspace NAME --artifact X`: the target is a bare name, and the
        # workspace came from the flag.
        manifest["workspace"] = mode.workspace
    return manifest


def _resolve_workspace_target(args: argparse.Namespace) -> int | None:
    """Turn a workspace *name* into the ID the analyzers accept.

    Returns an exit code on failure, or None when there is nothing to do
    -- which is the overwhelmingly common case, so the Fabric client is
    imported and built only when a workspace was actually named. A GUID
    short-circuits inside `resolve_workspace_id` without a round trip.
    """
    target = _target_of(args)
    if target is not None and target.workspace:
        name = target.workspace
    elif not getattr(args, "workspace_id", ""):
        name = (getattr(args, "file_config", None) or {}).get("workspace", "")
    else:
        # --workspace stores its value in workspace_id, which may be a display name.
        name = args.workspace_id
    if not name:
        return None

    from .playwright_validation.resolver import _GUID_PATTERN
    if _GUID_PATTERN.match(name.strip()):
        # Already an ID: skip building a client for nothing.
        args.workspace_id = name.strip()
        return None
    return _lookup_workspace_id(args, name)


def _lookup_workspace_id(args: argparse.Namespace, name: str) -> int | None:
    """Resolve a display name into args.workspace_id; an exit code on failure, else None."""
    from .playwright_validation.fabric_service_client import build_fabric_service_client, credential_failure_detail
    from .playwright_validation.resolver import AmbiguousWorkspaceError, ServiceResolutionError, WorkspaceNotFoundError

    try:
        if getattr(args, "interactive", False):
            client = build_service_client(args)
        else:
            client = build_fabric_service_client(env_file=getattr(args, "playwright_env_file", None))
            args._service_client = client
        args.workspace_id = resolve_workspace_id(client, name)
    except ServiceExportError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return exc.code
    except AmbiguousWorkspaceError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 2
    except WorkspaceNotFoundError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 1
    except ServiceResolutionError as exc:
        detail = "".join(f"\n    {line}" for line in credential_failure_detail(exc, getattr(args, "verbose", 0) or 0))
        print(f"  ✗ fab-test: could not resolve workspace '{name}': {exc}{detail}", file=sys.stderr)
        return 1
    return None


# One definition, shared with fab_test_summary, so a second discovery pass
# cannot drift back to reading args.artifact directly -- which it did, and
# which crashed `fab-test all --artifact X`.
_target_of = target_from_args


def _playwright_remote_target(args: argparse.Namespace) -> Path | None:
    """A playwright target named explicitly, with an environment to resolve it
    against, but no matching local folder.

    Playwright never reads report content from disk for either report type --
    the local folder under ``--artifact-dir`` is purely a naming anchor for
    the "discover everything" batch case. A caller who named a specific
    report (``--artifact NAME`` or ``WORKSPACE.Workspace/NAME.Type``) and an
    environment has stated an intent to resolve it live via ``resolve_report``,
    which a paginated (RDL) report especially needs: this repo's
    ``fabric-artifacts/`` tree only ever holds PBIR-format interactive
    reports, so an RDL report can never have a local folder to be found by at
    all. A real filesystem path (``./src/Sales.Report``) is left alone --
    naming a specific location and finding nothing there is a real miss, not
    a signal to resolve remotely.
    """
    target = _target_of(args)
    if target is None or target.scope not in ("path", "workspace"):
        return None
    if target.scope == "path" and target.path is not None:
        return None
    environment = getattr(args, "environment", "") or os.getenv("FABRIC_ENVIRONMENT", "")
    workspace = configured_workspace(args, playwright=False)
    if not environment and not workspace:
        return None
    return Path(target.name)


def _discover_rdl_files(args: argparse.Namespace, output_dir: Path) -> list[Path]:
    """Return local ``.rdl`` files matching the current target, if any.

    A paginated report is a flat ``NAME.rdl`` file, not a folder with a
    Fabric type suffix -- ``discover_artifacts``/`scan` cannot find it, since
    they only ever match directory names. Narrowed the same way
    `discover_artifacts` narrows a directory match: a target naming a
    different type finds nothing, and a target naming a name filters to it.
    """
    target = _target_of(args)
    if target is not None and target.type is not None and target.type != "PaginatedReport":
        return []
    files = _find_rdl_files(Path(args.artifact_dir), excluded_paths=[output_dir])
    if target is None or target.name is None:
        return files
    return [f for f in files if f.stem == target.name]


def _playwright_service_resolved_target(args: argparse.Namespace) -> list[Path] | None:
    """Return a service-resolved target list for one of playwright's
    non-local modes, or ``None`` when none apply and ordinary discovery
    should decide instead.

    Covers `--changed-since` and an impact manifest, `--dataset-id` (that
    dataset's dependents), and `--dataset-workspace-id` alone (every dataset
    in that workspace) -- split out of `_discover_for` so its own early
    returns don't count against that function's return-count budget.
    """
    if getattr(args, "impact_manifest", None):
        return [Path(".")]
    if changed_since_requested(args):
        return resolve_changed_reports(args)
    if workspace_reports_requested(args):
        return resolve_workspace_reports(args)
    if dataset_target_requested(args):
        return resolve_dataset_targets(args)
    if dataset_workspace_only_requested(args):
        return resolve_dataset_workspace_targets(args)
    return None


def _discover_for(name: str, args: argparse.Namespace, glob: str) -> list[Path]:
    """Return the artifacts ``name`` will run against.

    Two analyzers do not discover at all: a repository-scoped one runs once
    against the repo metadata, and impact-manifest- or dataset-driven
    Playwright validates a service-resolved set whatever exists locally.
    """
    if _is_repository_scoped(name):
        return [Path(".")]
    if is_service_run(name, args):
        return export_for_analyzer(name, args, Path(getattr(args, "output_dir", RESULTS_ROOT)))
    if name == "playwright":
        resolved = _playwright_service_resolved_target(args)
        if resolved is not None:
            return resolved
    output_dir = Path(getattr(args, "output_dir", RESULTS_ROOT))
    discovered = _discover(Path(args.artifact_dir), glob, _target_of(args), output_dir=output_dir)
    if name == "playwright":
        # playwright's own registered glob only ever covers *.Report, so a
        # paginated report -- a flat .rdl file, never discovered by the
        # directory-suffix scan above -- needs its own lookup or a batch run
        # (no --artifact) would never find one at all.
        discovered = discovered + _discover_rdl_files(args, output_dir)
        if not discovered:
            remote = _playwright_remote_target(args)
            if remote is not None:
                return [remote]
            # Last resort: --dataset-workspace-id with a bare name and no
            # local match -- resolve it against Fabric to tell a report
            # from a dataset (Playwright Dataset Target epic).
            dataset_remote = resolve_dataset_workspace_artifact(args)
            if dataset_remote is not None:
                return dataset_remote
    return discovered
