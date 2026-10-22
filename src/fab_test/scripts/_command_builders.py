"""Command builders for ``fab-test``: turn an artifact path and parsed args
into the subprocess command list for each analyzer.

Split out of ``fab_test_registry.py`` (Core Module Split), which keeps the
registry tables, scopes and discovery these builders read.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from ._desktop import (
    DesktopMatchError,
    detect_desktop_instances,
    match_instance_to_artifact,
)
from ._report_html import resolve_report
from ._rule_overlay import apply_overlay, apply_pbir_overlay, apply_rdl_overlay
from .fab_test_registry import (
    _DEFAULT_A11Y_PATH,
    _DEFAULT_BPA_RULES,
    _DEFAULT_INSPECTOR_PATH,
    _DEFAULT_PBIR_RULES,
    _DEFAULT_RDL_RULES,
    _DEFAULT_TE_PATH,
    _env,
    _script_module,
    discover_pbip_sources,
)
from .playwright_validation.execution_config import forward_execution_flags
from .playwright_validation.rdl_datasource import (
    parse_rdl_power_bi_datasource,
    parse_rdl_report_parameters,
)


def _write_resolved_rules(resolved: Any, output_dir: Path, subdir: str) -> Path:
    """Write an overlay-resolved ruleset under the run output directory and
    return its path, so it's traceable from the envelope's rules_file field.
    """
    resolved_path = output_dir / subdir / "_resolved-rules.json"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(json.dumps(resolved, indent=2), encoding="utf-8")
    return resolved_path


def _resolve_bpa_rules_path(args: argparse.Namespace, output_dir: Path) -> Path:
    """Resolve the BPA rules file: overlay-applied unless --bpa-rules-path
    was passed explicitly, in which case it's used verbatim.
    """
    explicit = getattr(args, "bpa_rules_path", _DEFAULT_BPA_RULES)
    if explicit != _DEFAULT_BPA_RULES:
        return Path(explicit)
    overlay = getattr(args, "file_config", {}).get("rules", {}).get("bpa", {})
    if not overlay:
        return Path(_DEFAULT_BPA_RULES)
    resolved = apply_overlay(Path(_DEFAULT_BPA_RULES), overlay)
    return _write_resolved_rules(resolved, output_dir, "bpa")


def _resolve_pbir_rules_path(args: argparse.Namespace, output_dir: Path) -> Path:
    """Resolve the PBIR Inspector rules file: overlay-applied unless
    --rules-path was passed explicitly, in which case it's used verbatim.
    """
    explicit = getattr(args, "rules_path", _DEFAULT_PBIR_RULES)
    if explicit != _DEFAULT_PBIR_RULES:
        return Path(explicit)
    overlay = getattr(args, "file_config", {}).get("rules", {}).get("pbir", {})
    if not overlay:
        return Path(_DEFAULT_PBIR_RULES)
    resolved = apply_pbir_overlay(Path(_DEFAULT_PBIR_RULES), overlay)
    return _write_resolved_rules(resolved, output_dir, "pbir")


def _resolve_rdl_rules_path(args: argparse.Namespace, output_dir: Path) -> Path:
    """Resolve the RDL rules file: overlay-applied unless --rules-path was
    passed explicitly, in which case it's used verbatim.
    """
    explicit = getattr(args, "rdl_rules_path", _DEFAULT_RDL_RULES)
    if explicit != _DEFAULT_RDL_RULES:
        return Path(explicit)
    overlay = getattr(args, "file_config", {}).get("rules", {}).get("rdl", {})
    if not overlay:
        return Path(_DEFAULT_RDL_RULES)
    resolved = apply_rdl_overlay(Path(_DEFAULT_RDL_RULES), overlay)
    return _write_resolved_rules(resolved, output_dir, "rdl")


def build_rdl_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build fab-test's own RDL static-analysis command for ``artifact``.

    No external tool to resolve -- pure Python on the standard library, so
    there is no ``--tool-path`` flag and nothing for ``resolve_tool`` to do.
    ``--report``/``--open-report`` need no flag either: the wrapper's
    ``attach_report`` reads ``ANALYZER_REPORT``, the same env var every
    other in-process report already goes through.
    """
    rules_path = _resolve_rdl_rules_path(args, output_dir)
    output = output_dir / "rdl" / artifact.stem / "envelope.json"
    return [
        sys.executable,
        "-m",
        _script_module("invoke_rdl_lint"),
        "--artifact-path",
        str(artifact),
        "--rules-path",
        str(rules_path),
        "--output-path",
        str(output),
    ]


def build_bpa_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build the Tabular Editor BPA command for ``artifact``."""
    te_path = getattr(args, "_resolved_tool_path", None) or (
        getattr(args, "tabular_editor_path", None) or _env("TABULAR_EDITOR_PATH", _DEFAULT_TE_PATH)
    )
    rules_path = _resolve_bpa_rules_path(args, output_dir)
    output = output_dir / "bpa" / artifact.stem / "envelope.json"
    return [
        sys.executable,
        "-m",
        _script_module("invoke_tabular_editor_bpa"),
        "--tmdl-path",
        str(artifact),
        "--bpa-rules-path",
        str(rules_path),
        "--tabular-editor-path",
        str(te_path),
        "--output-path",
        str(output),
    ]


def build_pbir_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build the PBIR Inspector command for ``artifact``."""
    inspector = getattr(args, "_resolved_tool_path", None) or (
        getattr(args, "inspector_path", None) or _env("PBIR_INSPECTOR_PATH", _DEFAULT_INSPECTOR_PATH)
    )
    rules_path = _resolve_pbir_rules_path(args, output_dir)
    output = output_dir / "pbir" / artifact.stem / "envelope.json"
    command = [
        sys.executable,
        "-m",
        _script_module("invoke_pbir_inspector"),
        "--artifact-path",
        str(artifact),
        "--rules-path",
        str(rules_path),
        "--inspector-path",
        str(inspector),
        "--output-path",
        str(output),
    ]
    # JSON is always requested -- the envelope's findings are parsed out of
    # it, so it is load-bearing rather than a display choice. HTML is the
    # only part --report gates, which puts pbir on the same footing as bpa
    # and pql_test: JSON envelope by default, a readable page on request.
    # PBIR Inspector's own page is richer than anything rendered from the
    # envelope, so attach_report stands aside once this one exists.
    if resolve_report(args):
        command.append("--emit-html")
    return command


def build_a11y_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build the pbir-a11y command for ``artifact``.

    Node resolution lives in the wrapper itself (``invoke_pbir_a11y.py``),
    not here -- the resolved path this builder passes is always the CLI
    entry point (``dist/cli.js``), the same shape ``resolve_executable``
    already hands every other bootstrapped analyzer.
    """
    a11y_path = getattr(args, "_resolved_tool_path", None) or (
        getattr(args, "a11y_path", None) or _env("PBIR_A11Y_PATH", _DEFAULT_A11Y_PATH)
    )
    output = output_dir / "a11y" / artifact.stem / "envelope.json"
    command = [
        sys.executable,
        "-m",
        _script_module("invoke_pbir_a11y"),
        "--artifact-path",
        str(artifact),
        "--a11y-path",
        str(a11y_path),
        "--output-path",
        str(output),
    ]
    fail_on = getattr(args, "fail_on", None)
    if fail_on:
        command += ["--fail-on", fail_on]
    return command


def bound_desktop_instance(artifact: Path):
    """Return the (port, model_name) of a Desktop instance with this artifact's
    .pbip open, or None when there's no pairing or no unambiguous match.

    Public because `fab-test`'s preflight calls it too: a ``local/`` target
    states the Desktop binding outright, so failing to find one is a
    missing prerequisite to report rather than a silent fallback.
    """
    pbip_path = discover_pbip_sources(artifact.parent).get(artifact.resolve())
    if pbip_path is None:
        return None
    instances = detect_desktop_instances()
    if not instances:
        return None
    try:
        instance = match_instance_to_artifact(instances, pbip_path)
    except DesktopMatchError:
        return None
    return instance.port, pbip_path.stem


def build_pql_test_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build the pql-test command for ``artifact``.

    When no workspace is supplied, invoked against the artifact's own paired
    .pbip: if exactly one running Power BI Desktop instance has that file
    open, its port and model name are added so the envelope can record what
    it bound to. Desktop detection is skipped entirely once a workspace ID
    is supplied -- that's the remote XMLA path.

    A ``local/`` target overrides that: it says Desktop outright, so an
    ambient FABRIC_WORKSPACE_ID does not quietly turn the run remote. The
    caller stated the scope, and honoring it is the whole point of saying
    so rather than relying on a variable being unset.
    """
    output = output_dir / "pql_test" / artifact.stem / "envelope.json"
    cmd = [
        sys.executable,
        "-m",
        _script_module("invoke_pql_test"),
        "--artifact-path",
        str(artifact),
        "--artifact-name",
        artifact.stem,
        "--output-path",
        str(output),
    ]
    target = getattr(args, "resolved_target", None)
    if target is not None and target.scope == "desktop":
        workspace_id = ""
    else:
        workspace_id = getattr(args, "workspace_id", "") or _env("FABRIC_WORKSPACE_ID")
    environment = getattr(args, "environment", "") or _env("FABRIC_ENVIRONMENT")
    if workspace_id:
        cmd += ["--workspace-id", workspace_id]
    if environment:
        cmd += ["--env", environment]
    if not workspace_id:
        bound = bound_desktop_instance(artifact)
        if bound is not None:
            port, model_name = bound
            cmd += ["--desktop-port", str(port), "--desktop-model-name", model_name]
    return cmd


def build_pql_lint_command(
    artifact: Path,
    args: argparse.Namespace,  # noqa: ARG001 - uniform builder signature
    output_dir: Path,
) -> list[str]:
    """Build the pqlint command for ``artifact``."""
    output = output_dir / "pql_lint" / artifact.stem / "envelope.json"
    return [
        sys.executable,
        "-m",
        _script_module("invoke_pqlint"),
        "--artifact-path",
        str(artifact),
        "--output-path",
        str(output),
    ]


def playwright_test_cases_dir(output_dir: Path, artifact: Path) -> Path:
    """Return the per-artifact directory `invoke_playwright.py` writes its
    generated test-case list into.

    A single source of truth for this path: `build_playwright_command`
    passes it explicitly via `--test-cases-dir` so the child always writes
    there (rather than the package's shared unversioned default, which two
    concurrent artifacts under `--jobs` would collide on), and
    `fab_test_execution.py`'s case-count-scaled timeout polls the same path
    to learn how many cases were generated, without duplicating the string.
    """
    return output_dir / "playwright" / artifact.stem / "test-cases"


_LOCAL_SUFFIX_TO_REPORT_TYPE = {
    ".Report": "report",
    # A paginated report is a flat NAME.rdl file, not a folder with a
    # PaginatedReport suffix -- that convention doesn't exist in practice
    # (Paginated Report RDL Data Source Resolution epic).
    ".rdl": "paginated",
}


def _report_type_for_command(artifact: Path, args: argparse.Namespace) -> str:
    """Return the report type to force on the subprocess, or "" to let it
    auto-detect.

    An explicit ``--report-type`` always wins. Otherwise, a real local
    folder's own suffix names its type definitively -- no need to make the
    subprocess ask Fabric something the outer CLI already knows just by
    having found the folder. A synthetic remote target (no local folder
    matched; see ``_playwright_remote_target``) has no such suffix, so it
    is left for the subprocess to auto-detect, exactly like a bare
    ``--artifact NAME`` always has.
    """
    explicit = getattr(args, "report_type", "") or (getattr(args, "playwright_report_types", None) or {}).get(
        artifact.stem, ""
    )
    if explicit:
        return explicit
    return _LOCAL_SUFFIX_TO_REPORT_TYPE.get(artifact.suffix, "")


def _dataset_override_for_command(artifact: Path, args: argparse.Namespace) -> tuple[str, str]:
    """Return ``(dataset_id, dataset_workspace_id)`` to force on the
    subprocess, or ``("", "")`` for either half to let it resolve normally.

    A per-report dataset ID wins first: "every dataset in a workspace" mode
    (`--dataset-workspace-id` alone) can span more than one dataset in a
    single run, so `args.dataset_id` alone cannot describe which dataset
    *this* report is bound to -- see `playwright_report_datasets` in
    `_playwright_dataset_target.py`. Otherwise explicit
    ``--dataset-id``/``--dataset-workspace-id`` win. Otherwise, a discovered
    ``.rdl`` file's own ``PBIDATASET`` data source already names the dataset
    it queries and the workspace that dataset lives in -- the caller should
    never have to already know and supply a GUID fab-test can read directly
    out of a file already checked into the repository. The workspace half is
    passed through as whatever the ``.rdl`` file recorded (a display name,
    not necessarily a GUID); ``--dataset-workspace-id`` already resolves
    either transparently on the subprocess side.
    """
    per_report_dataset = (getattr(args, "playwright_report_datasets", None) or {}).get(artifact.stem)
    dataset_id = per_report_dataset or getattr(args, "dataset_id", "") or ""
    dataset_workspace_id = getattr(args, "dataset_workspace_id", "") or ""
    if dataset_id or dataset_workspace_id or artifact.suffix != ".rdl":
        return dataset_id, dataset_workspace_id
    parsed = parse_rdl_power_bi_datasource(artifact)
    if parsed is None:
        return "", ""
    return parsed.dataset_id, parsed.workspace_name


def _report_parameters_for_command(artifact: Path, args: argparse.Namespace) -> str:
    """Return the JSON-encoded report parameters to force on the subprocess,
    or "" when there is nothing to derive.

    Only a local ``.rdl`` file has a ``<ReportParameters>`` block to read --
    a report resolved remotely by name has no local file, and its parameters
    (if any) are left for the subprocess to discover on its own some other
    way, exactly like dataset/workspace overrides above.
    """
    if getattr(args, "report_parameters", "") or artifact.suffix != ".rdl":
        return getattr(args, "report_parameters", "") or ""
    parameters = parse_rdl_report_parameters(artifact)
    if not parameters:
        return ""
    return json.dumps([dataclasses.asdict(parameter) for parameter in parameters])


def build_playwright_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build the Playwright validation command for ``artifact``."""
    output = output_dir / "playwright" / artifact.stem / "envelope.json"
    # A dataset-targeted run disambiguates two dependent reports that share a
    # display name (different IDs, different workspaces) by giving the
    # synthetic Path its own unique stem; the real name Fabric knows the
    # report by still has to reach --artifact for it to resolve at all.
    report_name = (getattr(args, "playwright_report_names", None) or {}).get(artifact.stem, artifact.stem)
    cmd = [
        sys.executable,
        "-m",
        _script_module("invoke_playwright"),
        "--output-path",
        str(output),
        "--artifact",
        report_name,
        "--test-cases-dir",
        str(playwright_test_cases_dir(output_dir, artifact)),
    ]
    env_file = getattr(args, "playwright_env_file", None)
    if env_file:
        cmd += ["--env-file", str(env_file)]
    env = getattr(args, "environment", "") or __import__("os").getenv("FABRIC_ENVIRONMENT", "")
    if env:
        cmd += ["--env", env]
    # A dataset-targeted run's dependents each live in their own workspace.
    workspace_id = (
        (getattr(args, "playwright_report_workspaces", None) or {}).get(artifact.stem)
        or getattr(args, "workspace_id", "")
        or __import__("os").getenv("FABRIC_WORKSPACE_ID", "")
    )
    if workspace_id:
        cmd += ["--workspace-id", workspace_id]
    impact_manifest = getattr(args, "impact_manifest", None)
    if impact_manifest:
        cmd += ["--impact-manifest", str(impact_manifest)]
    dataset_id, dataset_workspace_id = _dataset_override_for_command(artifact, args)
    if dataset_id:
        cmd += ["--dataset-id", dataset_id]
    if dataset_workspace_id:
        cmd += ["--dataset-workspace-id", dataset_workspace_id]
    report_type = _report_type_for_command(artifact, args)
    if report_type:
        cmd += ["--report-type", report_type]
    report_parameters = _report_parameters_for_command(artifact, args)
    if report_parameters:
        cmd += ["--report-parameters", report_parameters]
    if getattr(args, "plan_only", False):
        cmd += ["--plan-only"]
    pages = getattr(args, "pages", "auto")
    if pages != "auto":
        cmd += ["--pages", pages]
    roles = getattr(args, "roles", "auto")
    if roles != "auto":
        cmd += ["--roles", roles]
    user_name = getattr(args, "user_name", "")
    if user_name:
        cmd += ["--user-name", user_name]
    forward_execution_flags(cmd, args)
    return cmd


def build_dependencies_command(
    _artifact: Path,
    args: argparse.Namespace,
    _output_dir: Path,
) -> list[str]:
    """Build the semantic-model dependency discovery command."""
    cmd = [
        sys.executable,
        "-m",
        _script_module("invoke_playwright_dependencies"),
        "--semantic-model",
        getattr(args, "semantic_model", ""),
    ]
    env_file = getattr(args, "playwright_env_file", None)
    if env_file:
        cmd += ["--env-file", str(env_file)]
    env = getattr(args, "environment", "") or __import__("os").getenv("FABRIC_ENVIRONMENT", "")
    if env:
        cmd += ["--env", env]
    workspace_id = getattr(args, "workspace_id", "") or __import__("os").getenv("FABRIC_WORKSPACE_ID", "")
    if workspace_id:
        cmd += ["--workspace-id", workspace_id]
    output_path = getattr(args, "output_path", None)
    if output_path:
        cmd += ["--output", str(output_path)]
    return cmd


_COMMAND_BUILDERS: dict[str, Any] = {
    "bpa": build_bpa_command,
    "pbir": build_pbir_command,
    "a11y": build_a11y_command,
    "pql_test": build_pql_test_command,
    "pql_lint": build_pql_lint_command,
    "playwright": build_playwright_command,
    "dependencies": build_dependencies_command,
    "rdl": build_rdl_command,
}


def build_command(
    name: str,
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Return the subprocess command for analyzer ``name`` and ``artifact``."""
    builder = _COMMAND_BUILDERS[name]
    return builder(artifact, args, output_dir)
