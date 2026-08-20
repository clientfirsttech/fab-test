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

# Every artifact type fab-test can target. `tests/test_target.py` asserts
# this agrees with the globs in ANALYZER_REGISTRY, so the two cannot drift.
KNOWN_ARTIFACT_TYPES = ("Report", "SemanticModel")

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
_KNOWN_TYPES_HINT = f"known types: {', '.join(KNOWN_ARTIFACT_TYPES)}"


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


def _canonical_type(candidate: str) -> str | None:
    """Return the canonically-cased known type matching ``candidate``, or None."""
    for known in KNOWN_ARTIFACT_TYPES:
        if candidate.lower() == known.lower():
            return known
    return None


def _split_type(segment: str) -> tuple[str, str | None]:
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
    resolved = _canonical_type(candidate)
    if resolved is None:
        raise TargetError(f"unknown artifact type '{candidate}' in '{segment}'; {_KNOWN_TYPES_HINT}")
    if not name:
        raise TargetError(f"'{segment}' names a type but no artifact; {_ACCEPTED_FORMS}")
    return name, resolved


def _parse_path(target: str, raw: str) -> ResolvedTarget:
    """Parse the filesystem scope, whether or not it names a real location."""
    segments = _SEPARATOR_PATTERN.split(target)
    name, artifact_type = _split_type(segments[-1])
    has_separator = len(segments) > 1
    return ResolvedTarget(
        scope="path",
        name=name,
        type=artifact_type,
        workspace=None,
        path=Path(target) if has_separator else None,
        raw=raw,
    )


def _parse_desktop(segments: list[str], raw: str) -> ResolvedTarget:
    """Parse ``local/NAME``, the running-Desktop scheme."""
    if len(segments) != 2 or not segments[1].strip():
        raise TargetError(f"'{raw.strip()}' is not a valid Desktop target; {_ACCEPTED_FORMS}")
    name, artifact_type = _split_type(segments[1].strip())
    return ResolvedTarget(
        scope="desktop",
        name=name,
        type=artifact_type,
        workspace=None,
        path=None,
        raw=raw,
    )


def _parse_workspace(segments: list[str], raw: str) -> ResolvedTarget:
    """Parse ``WORKSPACE.Workspace/NAME.Type``, the Fabric CLI form."""
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
    name, artifact_type = _split_type(item)
    if artifact_type is None:
        raise TargetError(
            f"'{item}' needs an explicit type in a workspace target -- a deployed item "
            f"cannot be found by name alone; {_KNOWN_TYPES_HINT}"
        )
    return ResolvedTarget(
        scope="workspace",
        name=name,
        type=artifact_type,
        workspace=workspace,
        path=None,
        raw=raw,
    )


def parse_target(raw: str) -> ResolvedTarget:
    """Parse ``raw`` into a `ResolvedTarget`, or raise `TargetError`.

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

    if _EXPLICIT_PATH_PATTERN.match(target):
        return _parse_path(target, raw)

    segments = _SEPARATOR_PATTERN.split(target)
    first = segments[0].strip().lower()

    if first == _LOCAL_SCHEME and len(segments) > 1:
        return _parse_desktop(segments, raw)
    if first.endswith(_WORKSPACE_SUFFIX):
        return _parse_workspace(segments, raw)
    return _parse_path(target, raw)
