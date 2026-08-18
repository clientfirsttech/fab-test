"""
CLI utilities shared across Fabric CI/CD scripts.

Provides a single helper for terse machine-readable output so that every
script in this repository enforces the same format when --terse is active.
"""

import sys


def terse_print(terse: bool, status: str, scope: str, message: str) -> None:
    """Emit a single terse line when terse mode is active; silently no-ops otherwise.

    Output format::

        <STATUS> <scope>: <message>

    ``STATUS`` must be one of ``OK``, ``WARN``, ``ERROR``, ``FAIL``, ``SKIP``.
    ``ERROR`` and ``FAIL`` lines are written to *stderr*; all others to *stdout*.

    Args:
        terse:   Whether terse mode is enabled (``--terse`` flag value).
        status:  One of ``OK``, ``WARN``, ``ERROR``, ``FAIL``, ``SKIP``.
        scope:   Short dot-separated identifier for the check or operation.
        message: Human-readable detail; must fit on one line (no newlines).
    """
    if not terse:
        return
    line = f"{status} {scope}: {message}"
    if status in ("ERROR", "FAIL"):
        print(line, file=sys.stderr)
    else:
        print(line)
