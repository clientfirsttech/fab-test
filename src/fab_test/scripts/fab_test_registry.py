"""Analyzer registry and command builders for ``fab-test``.

This module keeps ``fab_test.py`` focused on CLI orchestration. Each supported
analyzer defines a glob for artifact discovery, a human description, and a
command builder that turns an artifact path + parsed args into a subprocess
command list.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

from ._analyzer_tool_bootstrap import (
    UnsupportedPlatformError,
    probe_executable,
    resolve_executable,
)
from ._artifact_types import load_artifact_map
from ._credentials import configured_workspace, probe_credentials
from ._desktop import (
    DesktopMatchError,
    desktop_ports,
    detect_desktop_instances,
    match_instance_to_artifact,
)
from ._metadata import ANALYZERS, BPA_RULES, PBIR_RULES, RDL_RULES, default_repo_root, metadata_path
from ._pbip_discovery import discover_pbip_projects
from ._report_html import resolve_report
from ._rule_overlay import apply_overlay, apply_pbir_overlay, apply_rdl_overlay
from ._scan import find_artifact_dirs, find_files_by_suffix
from ._target import ResolvedTarget
from .playwright_validation.execution_config import forward_execution_flags
from .playwright_validation.execution_runtime import execution_readiness
from .playwright_validation.rdl_datasource import (
    parse_rdl_power_bi_datasource,
    parse_rdl_report_parameters,
)

# Shares _metadata.default_repo_root with fab_test.py, so the two cannot
# disagree about what the repository is. This comment used to claim the reuse
# while a third copy of the rule sat underneath it.
REPO_ROOT = default_repo_root()
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _script_module(script_name: str) -> str:
    """Return the module name used to invoke an analyzer script.

    Runs the script via ``python -m fab_test.scripts.<name>`` so
    relative imports inside the package work correctly. This works for both
    editable/source installs and wheel installs because the script is always
    part of the installed ``fab_test.scripts`` package.
    """
    return f"fab_test.scripts.{script_name}"


# Default tool locations (match analyzers.json registry)
_DEFAULT_TE_PATH = str(REPO_ROOT / "TabularEditor" / "TabularEditor.exe")
# Resolved through metadata_path so an install outside a checkout falls back
# to the copy in the wheel. The repository copy still wins where one exists.
_DEFAULT_BPA_RULES = str(metadata_path(BPA_RULES, REPO_ROOT))
_DEFAULT_INSPECTOR_PATH = str(REPO_ROOT / "PBIR-Inspector" / "PBIRInspectorCLI")
_DEFAULT_A11Y_PATH = str(REPO_ROOT / "pbir-a11y" / "dist" / "cli.js")
_DEFAULT_PBIR_RULES = str(metadata_path(PBIR_RULES, REPO_ROOT))
_DEFAULT_RDL_RULES = str(metadata_path(RDL_RULES, REPO_ROOT))

ANALYZERS_JSON = metadata_path(ANALYZERS, REPO_ROOT)

# Maps subcommand name -> (artifact glob, human description)
ANALYZER_REGISTRY: dict[str, tuple[str, str]] = {
    "bpa": ("*.SemanticModel", "Tabular Editor Best Practice Analyzer"),
    "pbir": ("*.Report", "PBIR Inspector"),
    "a11y": ("*.Report", "PBIR accessibility checks (pbir-a11y)"),
    "pql_test": ("*.SemanticModel", "pql-test"),
    "pql_lint": ("*.SemanticModel", "pqlint"),
    "playwright": ("*.Report", "Playwright visual/error validation"),
    "playwright-impact": ("", "Playwright impact manifest builder"),
    "dependencies": ("", "Report dependency discovery"),
    "rdl": ("*.rdl", "RDL (paginated report) static analysis"),
}

# Analyzers kept out of the advertised surface: absent from `--help`,
# `fab-test list`, and the default `doctor` report. They stay fully
# invocable, aliases included -- the backward-compatibility constraint in
# vision.md says existing commands keep working, so this is a visibility
# state and never a removal. `doctor --analyzer <name>` still reports one
# on request, because hiding a name from a menu should not refuse to
# answer a direct question about it.
HIDDEN_ANALYZERS: frozenset[str] = frozenset({"pql_lint"})


def visible_analyzers() -> tuple[str, ...]:
    """Return the analyzer names that belong on the advertised surface."""
    return tuple(name for name in ANALYZER_REGISTRY if name not in HIDDEN_ANALYZERS)


# Which target scopes each analyzer can actually honor, declared once so the
# check cannot drift per command builder.
#
# The file-reading analyzers accept `desktop` as well as `path`: for them
# `local/Sales` is just a name, since the artifact is on disk either way.
# Only pql_test truly *binds* to a running instance, which is why the
# running-instance preflight keys off _DESKTOP_CAPABLE_ANALYZERS instead.
#
# None of them accept `workspace` except the ones that call the Fabric API.
# Making bpa read a deployed item would mean exporting its definition
# first, which is fabric-cicd-deployment's job and a stated non-goal.
ANALYZER_SCOPES: dict[str, frozenset[str]] = {
    "bpa": frozenset({"path", "desktop"}),
    "pbir": frozenset({"path", "desktop"}),
    "a11y": frozenset({"path", "desktop"}),
    "pql_lint": frozenset({"path", "desktop"}),
    "rdl": frozenset({"path", "desktop"}),
    "pql_test": frozenset({"path", "desktop", "workspace"}),
    "playwright": frozenset({"path", "workspace"}),
    "playwright-impact": frozenset({"path", "workspace"}),
    "dependencies": frozenset({"path", "workspace"}),
}

_SCOPE_HINTS = {
    "path": "a path (./src/Sales.SemanticModel) or a name (Sales.SemanticModel)",
    "desktop": "local/NAME for a running Power BI Desktop instance",
    "workspace": "WORKSPACE.Workspace/NAME.Type for a deployed item",
}

_SCOPE_REFUSALS = {
    "workspace": "reads artifact files on disk and cannot fetch a deployed item",
    "desktop": "does not bind to a running Power BI Desktop instance",
}


def unsupported_scope_error(name: str, target: ResolvedTarget | None) -> str | None:
    """Return an error message when ``name`` cannot honor ``target``'s scope.

    Parsing the grammar universally and refusing here -- rather than
    refusing at the parser -- is what lets the message name the analyzer
    and the forms that *would* work, instead of rejecting a target that is
    perfectly valid for the analyzer standing next to it.
    """
    if target is None:
        return None
    supported = ANALYZER_SCOPES.get(name)
    if supported is None or target.scope in supported:
        return None
    reason = _SCOPE_REFUSALS.get(target.scope, "does not support that target")
    alternatives = "; ".join(_SCOPE_HINTS[scope] for scope in sorted(supported))
    return f"{name} {reason}. Use {alternatives}"


def unsupported_type_error(name: str, target: ResolvedTarget | None) -> str | None:
    """Return an error when ``name`` cannot read ``target``'s artifact type.

    Accepting all nine declared Fabric types means a caller can now name
    one no analyzer reads. Before this, `bpa Sales.Notebook` failed at the
    parser as an "unknown artifact type" -- a type the repository's own map
    declares. After, discovery simply matched nothing and the run reported
    "no *.SemanticModel artifacts found", which is true and useless: it
    describes the directory rather than the mistake.

    Naming both halves -- what the analyzer reads, and what the target
    actually is -- is the difference between a message a caller can act on
    and one they have to reverse-engineer. Where another analyzer does
    read that type, it is named, because the next question is always
    "then what do I run?".
    """
    if target is None or target.type is None:
        return None
    glob, _description = ANALYZER_REGISTRY.get(name, ("", ""))
    if not glob:
        # Repository-scoped: it runs against the repo, so an artifact type
        # is not a thing it could refuse.
        return None
    handled = glob.removeprefix("*.")
    if target.type == handled:
        return None

    others = tuple(
        analyzer for analyzer in _suffix_to_analyzers().get(f".{target.type}", ()) if analyzer not in HIDDEN_ANALYZERS
    )
    opening = f"{name} reads {handled} artifacts; '{target.raw}' is a {target.type}"
    if not others:
        return f"{opening}, which no fab-test analyzer reads"
    return f"{opening}. Analyzers that read {target.type}: {', '.join(others)}"


# Analyzers that depend on an external binary/tool.
_BOOTSTRAPPED_ANALYZERS = {"bpa", "pbir", "a11y"}

# Analyzers that resolve no external binary but still cannot run on a bare
# checkout: they need a Fabric workspace plus credentials, or -- pql_test
# only -- a running Power BI Desktop instance to bind to. Without this set,
# check_readiness reported them ready on the strength of having no tool to
# find, a green light `doctor` could not honor.
_CLOUD_ANALYZERS = {"pql_test", "playwright", "playwright-impact", "dependencies"}

# The subset that can bind to a running Desktop instance instead of a
# workspace. Only pql_test does today; see build_pql_test_command.
_DESKTOP_CAPABLE_ANALYZERS = {"pql_test"}

# Which variables actually resolve a credential lives in _credentials.py,
# the single chain both `doctor` and `auth status` read. This is only the
# phrasing used when no workspace is set and there is nothing to probe yet.
_SERVICE_PRINCIPAL_HINT = "FABRIC_TENANT_ID, FABRIC_SERVICE_PRINCIPAL_ID, and FABRIC_SERVICE_PRINCIPAL_SECRET"

# Maps fab-test subcommand name to the matching analyzer registry key in
# .github/metadata/analyzers.json.
_BOOTSTRAP_REGISTRY_NAME = {
    "bpa": "tabular_editor_bpa",
    "pbir": "pbir_inspector",
    "a11y": "pbir_a11y",
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# Maps an artifact folder suffix to the analyzers whose glob matches it.
def _suffix_to_analyzers() -> dict[str, tuple[str, ...]]:
    """Group the registry's analyzers by the suffix their glob matches.

    Was a hand-written dict repeating what the globs above already say.
    Deriving it means a new analyzer is routed by declaring its glob and
    nowhere else, instead of by remembering to edit a second list.

    This answers "which analyzers handle this suffix" only. Which suffixes
    *exist* is `_artifact_types`' question, and the two are different: a
    Notebook is an artifact whether or not anything here reads one.
    """
    grouped: dict[str, list[str]] = {}
    for name, (glob, _description) in ANALYZER_REGISTRY.items():
        if not glob:
            continue
        grouped.setdefault(glob.removeprefix("*"), []).append(name)
    return {suffix: tuple(names) for suffix, names in grouped.items()}


def applicable_analyzers(artifact: Path) -> tuple[str, ...]:
    """Return the analyzer names whose artifact glob matches this path's suffix."""
    return _suffix_to_analyzers().get(artifact.suffix, ())


def discover_pbip_sources(artifact_dir: Path) -> dict[Path, Path]:
    """Map each artifact folder paired with a `.pbip` project to that project's path.

    Only folders found via `.pbip` pairing appear here — an artifact folder
    with no `.pbip` sibling (today's layout) is absent from the mapping.
    """
    sources: dict[Path, Path] = {}
    for project in discover_pbip_projects(artifact_dir):
        for candidate in (project.report_path, project.semantic_model_path):
            if candidate is not None:
                sources[candidate] = project.pbip_path
    return sources


def discover_artifacts(
    artifact_dir: Path,
    glob: str,
    target: ResolvedTarget | None,
    *,
    output_dir: Path | None = None,
) -> list[Path]:
    """Return sorted artifact paths matching ``glob``, narrowed by ``target``.

    A folder is an artifact because its name ends in a Fabric type suffix,
    found at any depth under ``artifact_dir``. It used to need either a
    top-level position or a `.pbip` beside it, which made a committed
    ``deployed/Sales.SemanticModel`` invisible — the shape artifacts take
    when they are checked in for CI rather than opened in Desktop. `.pbip`
    pairing still enriches a result; it no longer decides whether one
    exists. See `_scan` for what is pruned and why that matters.

    ``output_dir`` is pruned when given: analyzer results are written to
    folders named after the artifacts that produced them, so a run would
    otherwise rediscover its own output as artifacts.

    A target naming a *location* short-circuits discovery entirely and is
    not confined to ``artifact_dir``: the caller pointed at a specific
    folder, so scanning elsewhere and filtering would be both slower and
    wrong. Every other scope narrows the scan by name, and by type when
    the target carries one — which is how ``Sales.SemanticModel`` stops
    selecting ``Sales.Report``.

    A glob can name either a Fabric folder type (``*.SemanticModel``) or a
    flat-file suffix (``*.rdl`` — a paginated report is a single file, not
    a folder with a Fabric type suffix). Which shape it is comes from
    ``artifact-map.json``: a suffix declared there is a folder; anything
    else is a file. Both paths share the rest of this function's
    filtering, so a flat-file analyzer gets the same target/path/type
    narrowing a folder one already has.
    """
    suffix = glob.lstrip("*")
    is_folder_suffix = suffix in load_artifact_map(REPO_ROOT)

    if target is not None and target.path is not None:
        resolved = target.path.resolve()
        matches_shape = resolved.is_dir() if is_folder_suffix else resolved.is_file()
        return [resolved] if matches_shape and resolved.name.endswith(suffix) else []

    if not artifact_dir.exists():
        return []
    excluded_paths = [output_dir] if output_dir is not None else ()
    artifacts = (
        find_artifact_dirs(artifact_dir, (suffix,), excluded_paths=excluded_paths)
        if is_folder_suffix
        else find_files_by_suffix(artifact_dir, suffix, excluded_paths=excluded_paths)
    )
    if target is None:
        return artifacts

    if target.type is not None and not suffix.endswith(target.type):
        # The target names a type this analyzer does not read at all.
        return []
    # Accept either the artifact stem or the full artifact name
    # (e.g. "SampleModel-PQLAssert" or "SampleModel-PQLAssert.SemanticModel").
    return [a for a in artifacts if a.stem == target.name or a.name == target.name]


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
    forward_execution_flags(cmd, args)
    return cmd


def build_playwright_impact_command(
    artifact: Path,  # noqa: ARG001 - uniform builder signature
    args: argparse.Namespace,
    output_dir: Path,  # noqa: ARG001 - uniform builder signature
) -> list[str]:
    """Build the Playwright impact manifest command for ``artifact``."""
    changed_artifacts = getattr(args, "changed_artifacts", "changed-artifacts.json")
    cmd = [
        sys.executable,
        "-m",
        _script_module("invoke_playwright_impact"),
        "--changed-artifacts",
        str(changed_artifacts),
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
    "playwright-impact": build_playwright_impact_command,
    "dependencies": build_dependencies_command,
    "rdl": build_rdl_command,
}


# Analyzers that operate on a repository-level artifact path rather than a
# .fabric artifact directory.
_REPOSITORY_SCOPED_ANALYZERS = {"playwright-impact", "dependencies"}


def is_repository_scoped(name: str) -> bool:
    """Return True when the analyzer does not target a .fabric artifact."""
    return name in _REPOSITORY_SCOPED_ANALYZERS


def resolve_tool(name: str, args: argparse.Namespace) -> Path | None:
    """Resolve the external executable for ``name`` and store it on ``args``.

    Returns the resolved Path, or None for analyzers without a declared tool.
    Raises RuntimeError with a helpful message if the tool cannot be resolved.
    """
    if name not in _BOOTSTRAPPED_ANALYZERS:
        return None

    explicit = None
    if name == "bpa":
        explicit = getattr(args, "tabular_editor_path", None)
    elif name == "pbir":
        explicit = getattr(args, "inspector_path", None)
    elif name == "a11y":
        explicit = getattr(args, "a11y_path", None)

    resolved = resolve_executable(
        _BOOTSTRAP_REGISTRY_NAME.get(name, name),
        ANALYZERS_JSON,
        REPO_ROOT,
        explicit_path=explicit,
    )
    args._resolved_tool_path = str(resolved)
    return resolved


_TOOL_FLAG_HINTS = {
    "bpa": "--tabular-editor-path",
    "pbir": "--inspector-path",
    "a11y": "--a11y-path",
}


def preflight_error(name: str, args: argparse.Namespace) -> tuple[str, int] | None:
    """Return an (error message, exit code) pair if a required tool is missing.

    Exit code 126 signals the tool exists but is unsupported on this platform
    ("command found but not executable" — the closest POSIX convention);
    exit code 127 ("command not found") covers any other resolution failure,
    distinguishing an unconfigured machine from a real rule violation (1).
    """
    if name not in _BOOTSTRAPPED_ANALYZERS:
        return None
    try:
        resolve_tool(name, args)
    except UnsupportedPlatformError as exc:
        return str(exc), 126
    except RuntimeError as exc:
        message = str(exc)
        flag = _TOOL_FLAG_HINTS.get(name)
        if flag:
            message = f"{message}\n  Or pass {flag} <path> on the command line."
        return message, 127
    else:
        return None


def _cloud_readiness(name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    """Return readiness for an analyzer that needs a workspace or Desktop.

    Reports the target it would actually use, or names every source it
    accepts, so a caller is never told "ready" for a run that cannot
    reach anything. Stays as cheap as the rest of the probe: no
    subprocess, no network call, and no secret value in any field --
    whether the workspace is genuinely *reachable* is `auth status`'s
    question, not this one's.
    """
    workspace_id = configured_workspace(args, playwright=name != "pql_test")

    if workspace_id:
        status = probe_credentials()
        # Playwright always calls MSAL with a service-principal secret to
        # generate an embed token -- unlike pql_test, an ambient credential
        # (az login, managed identity) cannot stand in. Reporting ready off
        # `status.resolved` alone would be the false green task 1 exists to
        # remove: green from `doctor`, then an MSAL error on the one
        # command that cannot use an ambient sign-in.
        if name == "playwright" and not status.verified:
            return {
                "ready": False,
                "resolved_path": None,
                "reason": f"workspace configured; playwright needs a full service principal ({status.detail})",
                "remediation": status.remediation
                or (
                    "set FABRIC_TENANT_ID, FABRIC_CLIENT_ID (or "
                    "FABRIC_SERVICE_PRINCIPAL_ID), and FABRIC_CLIENT_SECRET "
                    "(or FABRIC_SERVICE_PRINCIPAL_SECRET) in the environment "
                    "or a .env file"
                ),
            }
        if status.resolved:
            reason = (
                f"workspace configured, credentials from {status.source}"
                if status.verified
                else f"workspace configured; {status.detail}"
            )
            return {
                "ready": True,
                "resolved_path": None,
                "reason": reason,
                "remediation": None,
            }
        return {
            "ready": False,
            "resolved_path": None,
            "reason": f"workspace configured but {status.detail}",
            "remediation": status.remediation,
        }

    desktop_capable = name in _DESKTOP_CAPABLE_ANALYZERS
    if desktop_capable and desktop_ports():
        return {
            "ready": True,
            "resolved_path": None,
            "reason": "no workspace set; would bind to a running Power BI Desktop instance",
            "remediation": None,
        }

    remediation = f"Set FABRIC_WORKSPACE_ID (or pass --workspace-id) plus {_SERVICE_PRINCIPAL_HINT}"
    if desktop_capable:
        return {
            "ready": False,
            "resolved_path": None,
            "reason": "no workspace, credentials, or running Desktop instance",
            "remediation": (f"{remediation}; or open the .pbip in Power BI Desktop to run locally"),
        }
    return {
        "ready": False,
        "resolved_path": None,
        "reason": "no workspace or credentials resolved",
        "remediation": remediation,
    }


def check_readiness(name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    """Return a readiness dict for analyzer ``name`` (the engine behind `doctor`).

    Never reads an artifact or spawns a subprocess. Three cases: an
    analyzer needing a workspace or Desktop instance (`_CLOUD_ANALYZERS`)
    is probed by ``_cloud_readiness``; one needing neither a binary nor a
    workspace (pql_lint) is always ready; the rest resolve an external
    tool -- see ``probe_executable`` for that shape.

    Every branch's dict gets a ``version`` key here rather than in each of
    them, so the doctor row shape stays uniform (only ``probe_executable``'s
    bootstrapped-tool path ever has one to report) without touching
    `_cloud_readiness`'s five return statements for a field that never
    applies to them.
    """
    result = execution_readiness(_readiness_without_version(name, args), name, args)
    result.setdefault("version", None)
    return result


def _readiness_without_version(name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    if name in _CLOUD_ANALYZERS:
        return _cloud_readiness(name, args)

    if name not in _BOOTSTRAPPED_ANALYZERS:
        return {
            "ready": True,
            "resolved_path": None,
            "reason": "no external tool required",
            "remediation": None,
        }

    explicit = None
    if args is not None:
        if name == "bpa":
            explicit = getattr(args, "tabular_editor_path", None)
        elif name == "pbir":
            explicit = getattr(args, "inspector_path", None)
        elif name == "a11y":
            explicit = getattr(args, "a11y_path", None)

    return probe_executable(
        _BOOTSTRAP_REGISTRY_NAME.get(name, name),
        ANALYZERS_JSON,
        REPO_ROOT,
        explicit_path=explicit,
    )


def build_command(
    name: str,
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Return the subprocess command for analyzer ``name`` and ``artifact``."""
    builder = _COMMAND_BUILDERS[name]
    return builder(artifact, args, output_dir)


def load_fab_test_all_analyzers(metadata_path: Path) -> tuple[str, ...]:
    """Read the analyzer list for ``fab-test all`` from ``analyzers.json``.

    Falls back to the historical default if the file is unreadable so that
    existing scripts and environments keep working.
    """
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ("bpa", "pbir", "pql_test", "pql_lint")

    configured = data.get("fab_test_all")
    if not isinstance(configured, list):
        return ("bpa", "pbir", "pql_test", "pql_lint")
    return tuple(str(name) for name in configured if isinstance(name, str))
