"""Analyzer registry for ``fab-test``: the registry tables, scopes and
artifact discovery.

This module keeps ``fab_test.py`` focused on CLI orchestration. Each supported
analyzer defines a glob for artifact discovery and a human description; the
command builders that turn an artifact path + parsed args into a subprocess
command list live in ``_command_builders.py``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ._artifact_types import load_artifact_map
from ._feature_flags import disabled_analyzers, is_enabled
from ._metadata import ANALYZERS, BPA_RULES, PBIR_RULES, RDL_RULES, default_repo_root, metadata_path
from ._pbip_discovery import discover_pbip_projects
from ._scan import find_artifact_dirs, find_files_by_suffix
from ._target import ResolvedTarget

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
PACKAGED_RULE_FILES = {
    "bpa": Path(_DEFAULT_BPA_RULES), "pbir": Path(_DEFAULT_PBIR_RULES), "rdl": Path(_DEFAULT_RDL_RULES)
}

ANALYZERS_JSON = metadata_path(ANALYZERS, REPO_ROOT)

# Maps subcommand name -> (artifact glob, human description)
ANALYZER_REGISTRY: dict[str, tuple[str, str]] = {
    "bpa": ("*.SemanticModel", "Tabular Editor Best Practice Analyzer"),
    "pbir": ("*.Report", "PBIR Inspector"),
    "a11y": ("*.Report", "PBIR accessibility checks (pbir-a11y)"),
    "pql_test": ("*.SemanticModel", "pql-test"),
    "pql_lint": ("*.SemanticModel", "pqlint"),
    "playwright": ("*.Report", "Playwright visual/error validation"),
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
    return tuple(name for name in ANALYZER_REGISTRY if name not in HIDDEN_ANALYZERS | disabled_analyzers())


# Which target scopes each analyzer can actually honor, declared once so the
# check cannot drift per command builder.
#
# The file-reading analyzers accept `desktop` as well as `path`: for them
# `local/Sales` is just a name, since the artifact is on disk either way.
# Only pql_test truly *binds* to a running instance, which is why the
# running-instance preflight keys off _DESKTOP_CAPABLE_ANALYZERS instead.
#
# bpa, pbir, a11y and rdl accept `workspace` too (Service Targeting epic):
# a deployed item is exported read-only through Fabric getDefinition into
# the on-disk shape they already read (see `_service_export`). Deploying
# remains fabric-cicd-deployment's job; only test-input export is in scope.
ANALYZER_SCOPES: dict[str, frozenset[str]] = {
    "bpa": frozenset({"path", "desktop", "workspace"}),
    "pbir": frozenset({"path", "desktop", "workspace"}),
    "a11y": frozenset({"path", "desktop", "workspace"}),
    "pql_lint": frozenset({"path", "desktop"}),
    "rdl": frozenset({"path", "desktop", "workspace"}),
    "pql_test": frozenset({"path", "desktop", "workspace"}),
    "playwright": frozenset({"path", "workspace"}),
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
    if name == "rdl" and target.scope == "workspace" and target.type == "PaginatedReport":
        return None

    others = tuple(
        analyzer for analyzer in _suffix_to_analyzers().get(f".{target.type}", ()) if analyzer not in HIDDEN_ANALYZERS
    )
    opening = f"{name} reads {handled} artifacts; '{target.raw}' is a {target.type}"
    if not others:
        return f"{opening}, which no fab-test analyzer reads"
    return f"{opening}. Analyzers that read {target.type}: {', '.join(others)}"


# Analyzers that depend on an external binary/tool (data_agent's is promptfoo).
_BOOTSTRAPPED_ANALYZERS = {"bpa", "pbir", "a11y", "data_agent"}

# Analyzers that resolve no external binary but still cannot run on a bare
# checkout: they need a Fabric workspace plus credentials, or -- pql_test
# only -- a running Power BI Desktop instance to bind to. Without this set,
# check_readiness reported them ready on the strength of having no tool to
# find, a green light `doctor` could not honor.
_CLOUD_ANALYZERS = {"pql_test", "playwright", "dependencies"}

# The subset that can bind to a running Desktop instance instead of a
# workspace. Only pql_test does today; see build_pql_test_command.
_DESKTOP_CAPABLE_ANALYZERS = {"pql_test"}

# Which variables actually resolve a credential lives in _credentials.py,
# the single chain both `doctor` and `auth status` read. This is only the
# phrasing used when no workspace is set and there is nothing to probe yet.
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
        if not glob or not is_enabled(name):
            continue
        grouped.setdefault(glob.removeprefix("*"), []).append(name)
    return {suffix: tuple(names) for suffix, names in grouped.items()}


# A paginated report is a flat .rdl file locally, but service mode exports
# it as a NAME.PaginatedReport folder holding that file.
_EXPORTED_FILE_SUFFIX = {".PaginatedReport": ".rdl"}


def applicable_analyzers(artifact: Path) -> tuple[str, ...]:
    """Return the analyzer names whose artifact glob matches this path's suffix."""
    suffix = _EXPORTED_FILE_SUFFIX.get(artifact.suffix, artifact.suffix)
    return _suffix_to_analyzers().get(suffix, ())


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


# Analyzers that operate on a repository-level artifact path rather than a
# Fabric artifact directory.
_REPOSITORY_SCOPED_ANALYZERS = {"dependencies"}


def is_repository_scoped(name: str) -> bool:
    """Return True when the analyzer does not target a Fabric artifact."""
    return name in _REPOSITORY_SCOPED_ANALYZERS


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
    return tuple(str(name) for name in configured if isinstance(name, str) and is_enabled(name))
