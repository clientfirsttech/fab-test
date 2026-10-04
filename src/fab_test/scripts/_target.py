"""Parse a target string into a `ResolvedTarget` (Artifact Targeting and Auth §1).

`fab-test` used to name artifacts with `--artifact STEM` against an
`--artifact-dir` root, which cannot express a deployed workspace item and
leaves local-versus-remote implied by whether `--workspace-id` happens to
be set. This module adopts the grammar `pql-test` and the Fabric CLI
already use, so a target pasted from either means the same thing here:

    ./src/Sales.SemanticModel          a location on disk
    Sales.SemanticModel                a name and type, resolved by discovery
    Sales                              a name, type left to the analyzer's glob
    local/Sales                        a running Power BI Desktop instance
    Sales Dev.Workspace/Sales.Report   a deployed item in a named workspace

Parsing only. This module touches no filesystem, opens no socket, and
knows nothing about analyzers: whether a scope is *usable* by a given
analyzer is §4's question, and turning a workspace name into an ID is
§3's. Keeping those out means the grammar can be tested exhaustively
without a Fabric tenant or a Desktop session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ._artifact_types import artifact_types

# Recognized ".Type" tokens that aren't Fabric folder types from
# artifact-map.json. A paginated report is a flat NAME.rdl file, not a
# NAME.PaginatedReport/ folder (Paginated Report RDL Data Source
# Resolution epic), so "rdl" needs its own recognized type token
# alongside the folder-suffix vocabulary `artifact_types` supplies.
_FILE_SUFFIX_TYPES: tuple[str, ...] = ("rdl",)

_LOCAL_SCHEME = "local"
_WORKSPACE_SUFFIX = ".workspace"
_SEPARATOR_PATTERN = re.compile(r"[/\\]")
# ./x  ../x  .\x  ..\x  /x  \x  C:\x -- unambiguously a location, so these
# never fall through to the `local/` scheme or the `.Workspace/` form.
_EXPLICIT_PATH_PATTERN = re.compile(r"^(\.{1,2}[/\\]|[/\\]|[A-Za-z]:)")

_ACCEPTED_FORMS = (
    "accepted forms: PATH (./src/Sales.SemanticModel), NAME.Type "
    "(Sales.SemanticModel), NAME (Sales), local/NAME, or "
    "WORKSPACE.Workspace/NAME.Type"
)


class TargetError(ValueError):
    """Raised when a target string cannot be parsed.

    Mirrors `_config.ConfigError`: the CLI turns it into exit code 2,
    since a malformed target means no analyzer was invoked.
    """


@dataclass(frozen=True)
class ResolvedTarget:
    """One parsed target. Immutable so it can be passed around freely.

    `path` is set only when the target names a location -- a bare
    `Sales.SemanticModel` is a filter applied to discovery, not a path.
    `workspace` is set only for the workspace scope, and is whatever the
    caller wrote: a display name or a GUID, resolved later by §3.
    """

    scope: str  # "path" | "desktop" | "workspace"
    name: str
    type: str | None
    workspace: str | None
    path: Path | None
    raw: str

    def as_dict(self, workspace_id: str = "") -> dict[str, object]:
        """Return a JSON-serializable view, for `run.json` and `--format json`.

        A structured object rather than an interpolated string, so a
        consumer can branch on ``scope`` without parsing prose.
        ``workspace_id`` is the GUID resolved from ``workspace``, passed in
        because resolving it needs a network call this module never makes.
        Carries no credential: a workspace ID names a workspace, it does
        not grant access to one.
        """
        return {
            "raw": self.raw,
            "scope": self.scope,
            "name": self.name,
            "type": self.type,
            "workspace": self.workspace,
            "workspace_id": workspace_id or None,
            "path": str(self.path) if self.path is not None else None,
        }


def _canonical_type(candidate: str, known: tuple[str, ...]) -> str | None:
    """Return the canonically-cased type in ``known`` matching ``candidate``."""
    for artifact_type in known:
        if candidate.lower() == artifact_type.lower():
            return artifact_type
    return None


def _split_type(segment: str, known: tuple[str, ...]) -> tuple[str, str | None]:
    """Split ``Name.Type`` into its parts, or return the whole thing as a name.

    Splits on the *last* dot so a name that contains one (``Sales.2024``)
    keeps it. A trailing token that is not a known type is a typo rather
    than part of the name -- silently treating ``Sales.SemmanticModel`` as
    an artifact called "Sales.SemmanticModel" would discover nothing and
    say nothing about why.
    """
    if "." not in segment:
        return segment, None
    name, _, candidate = segment.rpartition(".")
    resolved = _canonical_type(candidate, known)
    if resolved is None:
        raise TargetError(
            f"unknown artifact type '{candidate}' in '{segment}'; "
            f"known types: {', '.join(known)}"
        )
    if not name:
        raise TargetError(f"'{segment}' names a type but no artifact; {_ACCEPTED_FORMS}")
    return name, resolved


def _parse_path(target: str, raw: str, known: tuple[str, ...]) -> ResolvedTarget:
    """Parse the filesystem scope, whether or not it names a real location."""
    segments = _SEPARATOR_PATTERN.split(target)
    name, artifact_type = _split_type(segments[-1], known)
    has_separator = len(segments) > 1
    return ResolvedTarget(
        scope="path",
        name=name,
        type=artifact_type,
        workspace=None,
        path=Path(target) if has_separator else None,
        raw=raw,
    )


def _parse_desktop(segments: list[str], raw: str, known: tuple[str, ...]) -> ResolvedTarget:
    """Parse ``local/NAME``, the running-Desktop scheme."""
    if len(segments) != 2 or not segments[1].strip():
        raise TargetError(f"'{raw.strip()}' is not a valid Desktop target; {_ACCEPTED_FORMS}")
    name, artifact_type = _split_type(segments[1].strip(), known)
    return ResolvedTarget(
        scope="desktop",
        name=name,
        type=artifact_type,
        workspace=None,
        path=None,
        raw=raw,
    )


def _parse_workspace(
    segments: list[str], raw: str, known: tuple[str, ...], default_type: str | None = None
) -> ResolvedTarget:
    """Parse ``WORKSPACE.Workspace/NAME.Type``, the Fabric CLI form.

    ``default_type`` is the analyzer's own type, which lets an untyped
    ``WORKSPACE.Workspace/NAME`` resolve the way an untyped repo target does.
    """
    if len(segments) != 2:
        raise TargetError(
            f"'{raw.strip()}' has {len(segments)} path segments; a workspace target is "
            f"exactly WORKSPACE.Workspace/NAME.Type (nested folders are not supported)"
        )
    workspace = segments[0][: -len(_WORKSPACE_SUFFIX)].strip()
    if not workspace:
        raise TargetError(f"'{raw.strip()}' names no workspace; {_ACCEPTED_FORMS}")
    item = segments[1].strip()
    if not item:
        raise TargetError(f"'{raw.strip()}' names no artifact; {_ACCEPTED_FORMS}")
    name, artifact_type = _split_type(item, known)
    if artifact_type is None and default_type is not None:
        artifact_type = default_type
    if artifact_type is None:
        raise TargetError(
            f"'{item}' needs an explicit type in a workspace target -- a deployed item "
            f"cannot be found by name alone; known types: {', '.join(known)}"
        )
    return ResolvedTarget(
        scope="workspace",
        name=name,
        type=artifact_type,
        workspace=workspace,
        path=None,
        raw=raw,
    )


def target_from_args(args: object) -> ResolvedTarget | None:
    """Return the resolved target for ``args``, deriving it if `main` has not.

    `main` resolves once and stashes the result on ``args`` so the whole
    run agrees. Anything that discovers artifacts must read it through
    here rather than reaching for ``args.artifact``: that attribute is the
    raw deprecated string, and passing it where a `ResolvedTarget` is due
    silently ignores a positional target -- or raises.
    """
    cached = getattr(args, "resolved_target", None)
    if cached is not None:
        return cached
    return select_target(getattr(args, "target", None), getattr(args, "artifact", None))


def workspace_conflict(
    target: ResolvedTarget | None, workspace_id_flag: str | None
) -> str | None:
    """Return an error message when a target and ``--workspace-id`` disagree.

    Compared as written, with no lookup: a display name and a GUID cannot
    be compared without a round trip, and one invocation naming two
    different workspaces is a mistake whichever of them is correct. Saying
    the same thing twice is merely redundant and passes.
    """
    if target is None or target.workspace is None or not workspace_id_flag:
        return None
    if target.workspace.strip() == workspace_id_flag.strip():
        return None
    return (
        f"target names workspace '{target.workspace}' but --workspace-id says "
        f"'{workspace_id_flag}'; pass one or the other"
    )


def select_target(
    positional: str | None, artifact_flag: str | None, *, default_type: str | None = None
) -> ResolvedTarget | None:
    """Resolve the one target from the positional argument and ``--artifact``.

    ``--artifact`` predates the grammar and keeps working, routed through
    the same parser so it gains type awareness for free. Supplying both is
    refused rather than given a precedence rule: two ways to name one
    artifact in a single invocation is a mistake, and silently preferring
    one would hide it.
    """
    if positional and artifact_flag:
        raise TargetError(
            f"pass either a TARGET ('{positional}') or --artifact "
            f"('{artifact_flag}'), not both"
        )
    raw = positional or artifact_flag
    return parse_target(raw, default_type=default_type) if raw else None


def parse_target(
    raw: str, *, root: Path | None = None, default_type: str | None = None
) -> ResolvedTarget:
    """Parse ``raw`` into a `ResolvedTarget`, or raise `TargetError`.

    ``root`` is where the artifact-type map is read from, defaulting to the
    working directory. The set of types is data, not code -- see
    `_artifact_types` -- so a repository that declares a type this build
    has never heard of can still name it.

    Scope is decided by the first path segment, in this order: an explicit
    path prefix wins outright, then the reserved ``local/`` scheme, then a
    ``.Workspace`` suffix, and anything else is a path. The ordering is
    what lets ``./local/Sales`` address a directory actually named
    "local" -- the same escape hatch a shell gives you for a file named
    like a flag.
    """
    target = raw.strip()
    if not target:
        raise TargetError(f"empty target; {_ACCEPTED_FORMS}")

    known = artifact_types(root if root is not None else Path.cwd()) + _FILE_SUFFIX_TYPES

    if _EXPLICIT_PATH_PATTERN.match(target):
        return _parse_path(target, raw, known)

    segments = _SEPARATOR_PATTERN.split(target)
    first = segments[0].strip().lower()

    if first == _LOCAL_SCHEME and len(segments) > 1:
        return _parse_desktop(segments, raw, known)
    if first.endswith(_WORKSPACE_SUFFIX):
        return _parse_workspace(segments, raw, known, default_type)
    return _parse_path(target, raw, known)
