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
from collections.abc import Iterable, Iterator
from pathlib import Path

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


def iter_artifact_dirs(
    root: Path,
    suffixes: Iterable[str],
    *,
    excluded_paths: Iterable[Path] = (),
) -> Iterator[Path]:
    """Yield every directory under ``root`` whose name ends in a suffix.

    ``excluded_paths`` prunes specific trees the caller owns -- the run's
    output directory above all, since analyzer results land in folders
    named after the artifacts that produced them and would otherwise be
    rediscovered as artifacts on the next run.

    A matched directory is not descended into. Fabric artifacts do not
    nest, and `Sales.SemanticModel/definition` is a matched artifact's
    contents rather than another artifact.
    """
    root = root.resolve()
    if not root.is_dir():
        return
    suffix_tuple = tuple(suffixes)
    pruned = {path.resolve() for path in excluded_paths}

    for dirpath, dirnames, _filenames in os.walk(root):
        current = Path(dirpath)
        keep: list[str] = []
        for name in sorted(dirnames):
            child = current / name
            if name in EXCLUDED_DIR_NAMES or child in pruned:
                continue
            if _is_nested_checkout(child, root):
                continue
            if name.endswith(suffix_tuple):
                yield child
                continue
            keep.append(name)
        dirnames[:] = keep


def find_artifact_dirs(
    root: Path,
    suffixes: Iterable[str],
    *,
    excluded_paths: Iterable[Path] = (),
) -> list[Path]:
    """Return `iter_artifact_dirs` sorted and deduplicated."""
    return sorted(set(iter_artifact_dirs(root, suffixes, excluded_paths=excluded_paths)))
