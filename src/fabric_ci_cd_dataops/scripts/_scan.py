"""Find artifact folders by suffix, at any depth (Discover From CWD §3).

Discovery used to ask two narrow questions -- what sits directly under
`--artifact-dir`, and what is paired with a `.pbip` -- so a committed
`deployed/Sales.SemanticModel` with no `.pbip` beside it was invisible.
That is exactly the shape of artifacts checked in for CI. The signal that
identifies an artifact is its folder suffix; `.pbip` pairing enriches the
result but no longer decides whether it exists.

Scanning from the working directory makes the exclusion list load-bearing
rather than a nicety. Measured on this repository: a naive recursive scan
returns eight artifacts where three are real, the other five being copies
inside `.claude/worktrees/`. Without pruning, this feature would have
reported every artifact three times on the author's own machine the day
it shipped.

Directories are pruned rather than filtered, so an excluded tree costs
one `stat`, not a walk. `os.walk` is used over `Path.rglob` for exactly
that: `rglob` has no way to say "do not descend".
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

# Never worth walking, and expensive when walked: a virtualenv or a
# node_modules can hold tens of thousands of directories and cannot hold a
# Fabric artifact anyone meant to test.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".fab-test-tools",
    }
)


def _is_nested_checkout(directory: Path, root: Path) -> bool:
    """Whether ``directory`` is a separate git checkout below ``root``.

    A worktree or a vendored clone holds a `.git` entry -- a directory for
    a clone, a file for a worktree -- and holds its own copy of whatever
    the outer repository contains. Generalised from the guard
    `_pbip_discovery` already applied to `.pbip` files, for the same
    reason and now for every artifact.
    """
    return directory != root and (directory / ".git").exists()


class ScanResult(NamedTuple):
    """What one walk found, and what it refused to walk into.

    `skipped_checkouts` exists because pruning silently makes an empty
    result ambiguous: a caller cannot tell a repository with no artifacts
    from a directory of sibling repositories, every one of which was
    pruned. Only nested checkouts are reported -- `EXCLUDED_DIR_NAMES`
    and caller-supplied `excluded_paths` are not, since naming `.venv`
    tells the caller nothing they can act on.
    """

    artifacts: list[Path]
    skipped_checkouts: list[Path]


def scan(
    root: Path,
    suffixes: Iterable[str],
    *,
    excluded_paths: Iterable[Path] = (),
) -> ScanResult:
    """Walk ``root`` once for directories whose name ends in a suffix.

    ``excluded_paths`` prunes specific trees the caller owns -- the run's
    output directory above all, since analyzer results land in folders
    named after the artifacts that produced them and would otherwise be
    rediscovered as artifacts on the next run.

    A matched directory is not descended into. Fabric artifacts do not
    nest, and `Sales.SemanticModel/definition` is a matched artifact's
    contents rather than another artifact.

    Both lists come from the same walk. Counting the pruned checkouts
    separately would walk twice and give the prune rules a second home to
    drift from.
    """
    root = root.resolve()
    if not root.is_dir():
        return ScanResult([], [])
    suffix_tuple = tuple(suffixes)
    pruned = {path.resolve() for path in excluded_paths}
    artifacts: list[Path] = []
    checkouts: list[Path] = []

    for dirpath, dirnames, _filenames in os.walk(root):
        current = Path(dirpath)
        keep: list[str] = []
        for name in sorted(dirnames):
            child = current / name
            if name in EXCLUDED_DIR_NAMES or child in pruned:
                continue
            if _is_nested_checkout(child, root):
                checkouts.append(child)
                continue
            if name.endswith(suffix_tuple):
                artifacts.append(child)
                continue
            keep.append(name)
        dirnames[:] = keep

    return ScanResult(sorted(set(artifacts)), sorted(set(checkouts)))


def find_artifact_dirs(
    root: Path,
    suffixes: Iterable[str],
    *,
    excluded_paths: Iterable[Path] = (),
) -> list[Path]:
    """Return just the artifacts `scan` found, sorted and deduplicated."""
    return scan(root, suffixes, excluded_paths=excluded_paths).artifacts


def find_skipped_checkouts(root: Path) -> list[Path]:
    """The nested git checkouts a scan of ``root`` refuses to walk into.

    A second walk, run only when a caller has to explain a result that
    came back empty. It shares `scan` rather than restating the prune
    rule, so the explanation cannot drift from the behaviour it
    describes. No suffix is passed, so nothing is collected but the
    checkouts themselves.
    """
    return scan(root, ()).skipped_checkouts
