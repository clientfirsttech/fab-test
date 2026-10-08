"""Decide local / service for one run (Service Targeting epic).

The one rule: the TARGET (or its default) decides the mode. Flags and env
vars supply defaults; they never silently change the mode. Pure -- no
file reads, no network; only the working directory, to shorten a path -- so every analyzer, `all`, `list`, `explain`
and `doctor` can share one answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ._target import ResolvedTarget


class ModeError(ValueError):
    """Contradictory mode inputs; the CLI turns it into exit code 2."""


@dataclass(frozen=True)
class ResolvedMode:
    """``mode`` in local|service; ``source`` in target|flag|env|config|default.

    ``local`` is anything on this machine: artifact files in a folder (a Git
    checkout or not) or a model open in Power BI Desktop, which pql-test
    binds to on its own. ``path`` is where a local run reads from;
    ``workspace`` is set only for service.
    """

    mode: str
    workspace: str | None
    source: str
    path: str | None = None

    def banner(self) -> str:
        """The first stderr line of every run: only the location that applies to the mode."""
        where = f"workspace={self.workspace}" if self.mode == "service" else f"path={self.path or '.'}"
        return f"mode={self.mode} {where} source={self.source}"


def _shown(path: str) -> str:
    """``path`` relative to the working directory when it is inside it, so the default reads ``.``."""
    try:
        relative = os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return path
    return path if relative.startswith("..") else relative


def resolve_mode(
    target: ResolvedTarget | None,
    *,
    workspace_flag: str | None = None,
    artifact_dir_explicit: bool = False,
    artifact_dir: str = ".",
) -> ResolvedMode:
    """Resolve the mode per the epic's matrix.

    ``FABRIC_WORKSPACE_ID`` and the ``workspace:`` config key are
    deliberately not inputs: they supply a default workspace for service
    mode and never select it, so a bare invocation stays ``local``.
    """
    flag = (workspace_flag or "").strip() or None
    scope = target.scope if target is not None else None

    if scope == "desktop":
        if flag:
            raise ModeError(
                f"target '{target.raw.strip()}' is a Desktop instance but --workspace "
                f"'{flag}' asks for the service; pass one or the other"
            )
        return ResolvedMode("local", None, "target", target.raw.strip())

    if scope == "workspace":
        if flag and flag != target.workspace.strip():
            raise ModeError(
                f"target names workspace '{target.workspace}' but --workspace says "
                f"'{flag}'; pass one or the other"
            )
        return ResolvedMode("service", target.workspace.strip(), "target")

    if flag and not (target is None and artifact_dir_explicit):
        return ResolvedMode("service", flag, "flag")

    path = str(target.path) if target is not None and target.path is not None else _shown(artifact_dir)
    return ResolvedMode("local", None, "target" if target is not None else "default", path)
