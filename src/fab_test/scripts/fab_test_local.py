"""fab-test's `local` bundle: the no-cloud analyzer subset for a .pbip checkout.

Extracted from fab_test.py (Fab-Test Module Split epic). Pure move -- no
behavior change; `fab-test local --dry-run`'s plan output and `doctor
--local`'s readiness report stay exactly as they were.
"""

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from fab_test import __version__ as _FAB_TEST_VERSION

from ._cli_utils import narrate
from ._pbip_discovery import discover_pbip_projects as _discover_pbip_projects
from ._run_manifest import RunManifest
from .fab_test_execution import _manifest_target, _run_analyzer
from .fab_test_registry import (
    ANALYZER_REGISTRY as _ANALYZER_REGISTRY,
)
from .fab_test_registry import (
    check_readiness as _check_readiness,
)
from .fab_test_telemetry import _close_telemetry, _detect_origin, _open_telemetry

# pql_lint is excluded while it is hidden from the advertised surface
# (see HIDDEN_ANALYZERS): a bundle should not run what the CLI does not
# offer. It remains fully invocable on its own.
_LOCAL_ANALYZERS = ("bpa", "pbir", "pql_test")


def _pql_lint_path() -> str | None:
    """Resolved location of the ``pqlint`` package if usable, else ``None``.

    Unlike pql-test, pqlint is not a pinned fab-test dependency, so a
    fresh install genuinely may not have it -- the case this check exists
    to catch (mirrors invoke_pqlint.py's own resolution fallback).
    """
    on_path = shutil.which("pqlint")
    if on_path:
        return on_path
    spec = importlib.util.find_spec("pqlint")
    return spec.origin if spec else None


def _local_readiness(name: str, args: argparse.Namespace) -> dict[str, Any]:
    """Return a readiness dict for one of the `_LOCAL_ANALYZERS`.

    Always has the same four keys as `check_readiness` (ready, reason,
    resolved_path, remediation) so a JSON consumer never has to branch on
    which analyzer it's reading. pql_test is always ready (a pinned
    fab-test dependency); pql_lint needs its own presence check since
    pqlint is not bundled; bpa/pbir reuse the existing bootstrapped-tool
    readiness probe.
    """
    if name == "pql_lint":
        path = _pql_lint_path()
        if path:
            return {"ready": True, "reason": "pqlint available", "resolved_path": path, "remediation": None}
        return {
            "ready": False,
            "reason": "pqlint not found on PATH or importable",
            "resolved_path": None,
            "remediation": "pip install pqlint",
        }
    if name == "pql_test":
        return {
            "ready": True,
            "reason": "pql-test is a fab-test dependency",
            "resolved_path": None,
            "remediation": None,
        }
    return _check_readiness(name, args)


def _project_matches_glob(project: Any, glob: str) -> bool:
    """Whether a discovered PbipProject has the folder `glob` matches."""
    suffix = glob.lstrip("*")
    if suffix == ".SemanticModel":
        return project.semantic_model_path is not None
    if suffix == ".Report":
        return project.report_path is not None
    return False


def _build_local_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Build the `fab-test local --dry-run` plan.

    Never spawns a subprocess or touches Desktop detection: it only
    discovers projects on disk and checks each analyzer's readiness, the
    same primitives `doctor`/`list` already use.
    """
    artifact_dir = Path(args.artifact_dir)
    projects = _discover_pbip_projects(artifact_dir)

    plan_analyzers = []
    for name in _LOCAL_ANALYZERS:
        readiness = _local_readiness(name, args)
        if not readiness["ready"]:
            plan_analyzers.append({
                "analyzer": name,
                "status": "skipped",
                "reason": readiness["reason"],
                "remediation": readiness["remediation"],
            })
            continue
        glob, _description = _ANALYZER_REGISTRY[name]
        matching = [p.name for p in projects if _project_matches_glob(p, glob)]
        plan_analyzers.append({"analyzer": name, "status": "would_run", "projects": matching})

    return {
        "analyzer": "local",
        "dry_run": True,
        "projects": [p.name for p in projects],
        "analyzers": plan_analyzers,
    }


def _narrate_local_plan(plan: dict[str, Any], output_format: str) -> None:
    """Print the fab-test local --dry-run plan as human-readable narration."""
    projects = plan["projects"]
    narrate(
        f"\nfab-test local — dry run, {len(projects)} project(s): "
        f"{', '.join(projects) if projects else '(none)'}",
        output_format=output_format,
    )
    for entry in plan["analyzers"]:
        if entry["status"] == "skipped":
            hint = f" ({entry['remediation']})" if entry["remediation"] else ""
            narrate(
                f"  ⏭ {entry['analyzer']}: skipped -- {entry['reason']}{hint}",
                output_format=output_format,
            )
        else:
            names = ", ".join(entry["projects"]) if entry["projects"] else "(no matching project)"
            narrate(f"  ▶ {entry['analyzer']}: would run against {names}", output_format=output_format)


def _run_local(args: argparse.Namespace) -> int:
    """Run every analyzer in `_LOCAL_ANALYZERS` against every discovered project.

    An analyzer whose prerequisite is absent is skipped with a remediation
    hint rather than failing the run (vision §2.7: platform gaps degrade to
    skips). Never requires a workspace ID, service-principal credential, or
    Fabric network call -- the `local` subparser doesn't even expose those
    flags.
    """
    output_format = getattr(args, "output_format", "text")
    output_dir = Path(args.output_dir)

    if getattr(args, "dry_run", False):
        plan = _build_local_plan(args)
        _narrate_local_plan(plan, output_format)
        if output_format == "json":
            print(json.dumps(plan, indent=2))
        return 0

    manifest = RunManifest(
        _FAB_TEST_VERSION, sys.argv, origin=_detect_origin(), target=_manifest_target(args)
    )
    telemetry = _open_telemetry(args)

    results: list[dict[str, Any]] = []
    for name in _LOCAL_ANALYZERS:
        readiness = _local_readiness(name, args)
        if not readiness["ready"]:
            hint = f" ({readiness['remediation']})" if readiness["remediation"] else ""
            narrate(
                f"  ⏭ fab-test local: {name} skipped -- {readiness['reason']}{hint}",
                output_format=output_format,
            )
            results.append({"analyzer": name, "status": "skipped", "reason": readiness["reason"]})
            continue
        code = _run_analyzer(name, args, output_dir, manifest, telemetry)
        results.append({"analyzer": name, "status": "ran", "exit_code": code})

    exit_code = 1 if any(r.get("exit_code", 0) != 0 for r in results) else 0
    # Flushed before the manifest is written so run.json can record whether
    # this run's telemetry landed.
    manifest.telemetry_error = _close_telemetry(telemetry, args)
    manifest.write(output_dir, exit_code)
    if output_format == "json":
        print(json.dumps({"analyzer": "local", "results": results, "exit_code": exit_code}, indent=2))
    return exit_code
