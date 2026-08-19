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


def narrate(message: str, *, output_format: str = "text", quiet: bool = False) -> None:
    """Print a human-facing narration line, routed by output format.

    Callers use this instead of a bare ``print`` for banners, per-artifact
    progress, and warnings, so stdout stays reserved for the machine-readable
    payload under ``--format json``.

    Args:
        message: The line to narrate.
        output_format: ``"json"`` routes to stderr; anything else (default
            ``"text"``) routes to stdout, exactly like ``print`` does today.
        quiet: When True, the line is suppressed entirely in both formats.
    """
    if quiet:
        return
    if output_format == "json":
        print(message, file=sys.stderr)
    else:
        print(message)
