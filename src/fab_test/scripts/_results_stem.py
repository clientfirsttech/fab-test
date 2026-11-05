"""The folder name an artifact's results go under.

Results live in ``<output-dir>/<analyzer>/<stem>/``, and a stem is only unique
by luck: ``ACC-03.rdl`` beside ``ACC-03.PaginatedReport/ACC-03.rdl`` share one.
Discovery records the artifacts whose stem collides with another's in the same
run, and everything that builds or reads a results path asks ``results_stem``
instead of reading ``.stem``. A stem nobody else shares keeps the plain name,
so every path that worked before still does.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

_SUFFIXED: dict[Path, str] = {}


def _disambiguator(artifact: Path, root: Path) -> str:
    """Eight hex digits from the path relative to ``root``: the same in CI as on a laptop."""
    try:
        relative = artifact.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = artifact.resolve().as_posix()
    return hashlib.sha1(relative.encode("utf-8")).hexdigest()[:8]  # noqa: S324 -- a label, not security


def register_stems(artifacts: Iterable[Path], root: Path) -> None:
    """Record which of ``artifacts`` share a stem. Idempotent: the latest run wins."""
    found = list(artifacts)
    counts = Counter(a.stem for a in found)
    for artifact in found:
        key = artifact.resolve()
        if counts[artifact.stem] > 1:
            _SUFFIXED[key] = f"{artifact.stem}-{_disambiguator(artifact, root)}"
        else:
            _SUFFIXED.pop(key, None)


def results_stem(artifact: Path) -> str:
    """The results folder name for ``artifact``: its stem, suffixed only on a collision."""
    return _SUFFIXED.get(artifact.resolve(), artifact.stem)
