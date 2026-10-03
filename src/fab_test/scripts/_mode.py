"""Decide repo / desktop / service for one run (Service Targeting epic).

The one rule: the TARGET (or its default) decides the mode. Flags and env
vars supply defaults; they never silently change the mode. Pure -- no
filesystem, no network -- so every analyzer, `all`, `list`, `explain`
and `doctor` can share one answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._target import ResolvedTarget


class ModeError(ValueError):
    """Contradictory mode inputs; the CLI turns it into exit code 2."""


@dataclass(frozen=True)
class ResolvedMode:
    """``mode`` in repo|desktop|service; ``source`` in target|flag|env|config|default."""

    mode: str
    workspace: str | None
    source: str

    def banner(self) -> str:
        """The first stderr line of every run."""
        return f"mode={self.mode} workspace={self.workspace or '—'} source={self.source}"


def resolve_mode(
    target: ResolvedTarget | None,
    *,
    workspace_flag: str | None = None,
    artifact_dir_explicit: bool = False,
) -> ResolvedMode:
    """Resolve the mode per the epic's matrix.

    ``FABRIC_WORKSPACE_ID`` and the ``workspace:`` config key are
    deliberately not inputs: they supply a default workspace for service
    mode and never select it, so a bare invocation stays ``repo``.
    """
    flag = (workspace_flag or "").strip() or None
    scope = target.scope if target is not None else None

    if scope == "desktop":
        if flag:
            raise ModeError(
                f"target '{target.raw.strip()}' is a Desktop instance but --workspace "
                f"'{flag}' asks for the service; pass one or the other"
            )
        return ResolvedMode("desktop", None, "target")

    if scope == "workspace":
        if flag and flag != target.workspace.strip():
            raise ModeError(
                f"target names workspace '{target.workspace}' but --workspace says "
                f"'{flag}'; pass one or the other"
            )
        return ResolvedMode("service", target.workspace.strip(), "target")

    if flag and not (target is None and artifact_dir_explicit):
        return ResolvedMode("service", flag, "flag")

    return ResolvedMode("repo", None, "target" if target is not None else "default")
