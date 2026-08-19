"""Analyzer registry and command builders for ``fab-test``.

This module keeps ``fab_test.py`` focused on CLI orchestration. Each supported
analyzer defines a glob for artifact discovery, a human description, and a
command builder that turns an artifact path + parsed args into a subprocess
command list.
"""

from __future__ import annotations

import argparse
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
from ._desktop import DesktopMatchError, detect_desktop_instances, match_instance_to_artifact
from ._pbip_discovery import discover_pbip_projects

# Reuse the same repo-root logic as fab_test.py so paths stay consistent.


def _repo_root() -> Path:
    """Return the repository root."""
    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    return Path.cwd().resolve()


REPO_ROOT = _repo_root()
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _script_module(script_name: str) -> str:
    """Return the module name used to invoke an analyzer script.

    Runs the script via ``python -m fabric_ci_cd_dataops.scripts.<name>`` so
    relative imports inside the package work correctly. This works for both
    editable/source installs and wheel installs because the script is always
    part of the installed ``fabric_ci_cd_dataops.scripts`` package.
    """
    return f"fabric_ci_cd_dataops.scripts.{script_name}"


# Default tool locations (match analyzers.json registry)
_DEFAULT_TE_PATH = str(REPO_ROOT / "TabularEditor" / "TabularEditor.exe")
_DEFAULT_BPA_RULES = str(
    REPO_ROOT / ".github" / "metadata" / "rules" / "BPARules.json"
)
_DEFAULT_INSPECTOR_PATH = str(REPO_ROOT / "PBIR-Inspector" / "PBIRInspectorCLI")
_DEFAULT_PBIR_RULES = str(
    REPO_ROOT / ".github" / "metadata" / "rules" / "pbi-inspector-custom-rules.json"
)

ANALYZERS_JSON = REPO_ROOT / ".github" / "metadata" / "analyzers.json"

# Maps subcommand name -> (artifact glob, human description)
ANALYZER_REGISTRY: dict[str, tuple[str, str]] = {
    "bpa": ("*.SemanticModel", "Tabular Editor Best Practice Analyzer"),
    "pbir": ("*.Report", "PBIR Inspector"),
    "pql_test": ("*.SemanticModel", "pql-test"),
    "pql_lint": ("*.SemanticModel", "pqlint"),
    "playwright": ("*.Report", "Playwright visual/error validation"),
    "playwright-impact": ("", "Playwright impact manifest builder"),
    "dependencies": ("", "Report dependency discovery"),
}

# Analyzers that depend on an external binary/tool.
_BOOTSTRAPPED_ANALYZERS = {"bpa", "pbir"}

# Maps fab-test subcommand name to the matching analyzer registry key in
# .github/metadata/analyzers.json.
_BOOTSTRAP_REGISTRY_NAME = {
    "bpa": "tabular_editor_bpa",
    "pbir": "pbir_inspector",
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# Maps an artifact folder suffix to the analyzers whose glob matches it.
_SUFFIX_TO_ANALYZERS: dict[str, tuple[str, ...]] = {
    ".SemanticModel": ("bpa", "pql_test", "pql_lint"),
    ".Report": ("pbir", "playwright"),
}


def applicable_analyzers(artifact: Path) -> tuple[str, ...]:
    """Return the analyzer names whose artifact glob matches this path's suffix."""
    return _SUFFIX_TO_ANALYZERS.get(artifact.suffix, ())


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
    stem_filter: str | None,
) -> list[Path]:
    """Return sorted artifact paths matching ``glob`` and optional stem filter.

    Includes artifacts found directly under ``artifact_dir`` and any
    matching folder paired with a `.pbip` project discovered recursively
    within ``artifact_dir`` — a developer's `.pbip` need not sit at the top
    level of the directory being scanned. Search never leaves
    ``artifact_dir``.
    """
    if not artifact_dir.exists():
        return []
    suffix = glob.lstrip("*")
    matches = {path.resolve() for path in artifact_dir.glob(glob)}
    matches.update(
        path for path in discover_pbip_sources(artifact_dir) if path.name.endswith(suffix)
    )
    artifacts = sorted(matches)
    if stem_filter:
        # Accept either the artifact stem or the full artifact name
        # (e.g. "SampleModel-PQLAssert" or "SampleModel-PQLAssert.SemanticModel").
        artifacts = [
            a for a in artifacts if a.stem == stem_filter or a.name == stem_filter
        ]
    return artifacts


def build_bpa_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build the Tabular Editor BPA command for ``artifact``."""
    te_path = getattr(args, "_resolved_tool_path", None) or (
        getattr(args, "tabular_editor_path", None)
        or _env("TABULAR_EDITOR_PATH", _DEFAULT_TE_PATH)
    )
    rules_path = getattr(args, "bpa_rules_path", _DEFAULT_BPA_RULES)
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
        getattr(args, "inspector_path", None)
        or _env("PBIR_INSPECTOR_PATH", _DEFAULT_INSPECTOR_PATH)
    )
    rules_path = getattr(args, "rules_path", _DEFAULT_PBIR_RULES)
    output = output_dir / "pbir" / artifact.stem / "envelope.json"
    return [
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
        "--emit-html",
    ]


def _bound_desktop_instance(artifact: Path):
    """Return the (port, model_name) of a Desktop instance with this artifact's
    .pbip open, or None when there's no pairing or no unambiguous match.
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
    workspace_id = getattr(args, "workspace_id", "") or _env("FABRIC_WORKSPACE_ID")
    environment = getattr(args, "environment", "") or _env("FABRIC_ENVIRONMENT")
    if workspace_id:
        cmd += ["--workspace-id", workspace_id]
    if environment:
        cmd += ["--env", environment]
    if not workspace_id:
        bound = _bound_desktop_instance(artifact)
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


def build_playwright_command(
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
) -> list[str]:
    """Build the Playwright validation command for ``artifact``."""
    output = output_dir / "playwright" / artifact.stem / "envelope.json"
    cmd = [
        sys.executable,
        "-m",
        _script_module("invoke_playwright"),
        "--output-path",
        str(output),
        "--artifact",
        artifact.stem,
    ]
    env_file = getattr(args, "playwright_env_file", None)
    if env_file:
        cmd += ["--env-file", str(env_file)]
    env = getattr(args, "environment", "") or __import__("os").getenv(
        "FABRIC_ENVIRONMENT", ""
    )
    if env:
        cmd += ["--env", env]
    workspace_id = getattr(args, "workspace_id", "") or __import__("os").getenv(
        "FABRIC_WORKSPACE_ID", ""
    )
    if workspace_id:
        cmd += ["--workspace-id", workspace_id]
    impact_manifest = getattr(args, "impact_manifest", None)
    if impact_manifest:
        cmd += ["--impact-manifest", str(impact_manifest)]
    dataset_id = getattr(args, "dataset_id", "")
    if dataset_id:
        cmd += ["--dataset-id", dataset_id]
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
    env = getattr(args, "environment", "") or __import__("os").getenv(
        "FABRIC_ENVIRONMENT", ""
    )
    if env:
        cmd += ["--env", env]
    workspace_id = getattr(args, "workspace_id", "") or __import__("os").getenv(
        "FABRIC_WORKSPACE_ID", ""
    )
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
    env = getattr(args, "environment", "") or __import__("os").getenv(
        "FABRIC_ENVIRONMENT", ""
    )
    if env:
        cmd += ["--env", env]
    workspace_id = getattr(args, "workspace_id", "") or __import__("os").getenv(
        "FABRIC_WORKSPACE_ID", ""
    )
    if workspace_id:
        cmd += ["--workspace-id", workspace_id]
    output_path = getattr(args, "output_path", None)
    if output_path:
        cmd += ["--output", str(output_path)]
    return cmd


_COMMAND_BUILDERS: dict[str, Any] = {
    "bpa": build_bpa_command,
    "pbir": build_pbir_command,
    "pql_test": build_pql_test_command,
    "pql_lint": build_pql_lint_command,
    "playwright": build_playwright_command,
    "playwright-impact": build_playwright_impact_command,
    "dependencies": build_dependencies_command,
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


def check_readiness(name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    """Return a readiness dict for analyzer ``name`` (the engine behind `doctor`).

    Never reads an artifact or spawns a subprocess. Analyzers without an
    external tool to resolve (pql_test, pql_lint, playwright, ...) are always
    ready. See ``probe_executable`` for the bootstrapped-analyzer shape.
    """
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
