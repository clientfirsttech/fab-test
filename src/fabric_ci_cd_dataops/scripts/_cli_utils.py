"""
CLI utilities shared across Fabric CI/CD scripts.

Provides a single helper for terse machine-readable output so that every
script in this repository enforces the same format when --terse is active.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

# A warning stays a warning: on a developer's machine the full list is
# every repository they have ever cloned, and three is enough to make the
# remedy pasteable.
CHECKOUTS_NAMED = 3
CHECKOUT_REMEDIATION = "cd into a checkout, or point at one with --artifact-dir <path>"


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


def skipped_checkout_lines(checkouts: Sequence[Path]) -> list[str]:
    """Explain a scan that pruned repositories, or say nothing at all.

    An empty scan has two very different causes that used to read
    identically: the root holds no artifacts, or every candidate below it
    was pruned as a nested checkout. The second is what a developer sees
    running `fab-test` from a folder of sibling repositories, and it is
    the one with a fix worth naming.

    Empty when nothing was pruned -- the in-repo case is the common one
    and must not get noisier to serve the caller who ran `fab-test` one
    directory too high. Lives in this leaf module so `fab_test` and
    `fab_test_summary` can share it without a cycle.
    """
    if not checkouts:
        return []
    verb = "was" if len(checkouts) == 1 else "were"
    plural = "" if len(checkouts) == 1 else "s"
    return [
        f"    {len(checkouts)} git checkout{plural} below this root {verb} skipped — "
        "a scan does not",
        "    descend into a nested repository. cd into one, or name it directly:",
        *(f"      --artifact-dir {path}" for path in checkouts[:CHECKOUTS_NAMED]),
    ]
