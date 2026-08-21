"""Which folder suffixes are Fabric artifacts (Discover From CWD §1).

`.github/metadata/artifact-map.json` maps a folder suffix to a Fabric type
and already existed before `fab-test` read it — three separate hardcoded
lists each knew two of its nine types, and a `.Notebook` target was
rejected as an unknown type the repository itself declared.

The repository copy wins when present. A copy packaged with the
distribution covers an install from PyPI, or any run outside a checkout.
A test asserts the two agree: a fallback that has drifted is worse than
none, because it answers confidently and wrongly.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PACKAGED_ARTIFACT_MAP = Path(__file__).resolve().parent.parent / "metadata" / "artifact-map.json"

_REPO_RELATIVE = Path(".github") / "metadata" / "artifact-map.json"


def _packaged() -> dict[str, str]:
    return json.loads(PACKAGED_ARTIFACT_MAP.read_text(encoding="utf-8"))


def load_artifact_map(repo_root: Path) -> dict[str, str]:
    """Return the suffix-to-type mapping for ``repo_root``.

    Falls back to the packaged copy when the repository has no map, and
    also when it has an unusable one. A malformed file is not worse than a
    missing file: either way the caller needs a working answer, and the
    warning says which file to fix.
    """
    candidate = repo_root / _REPO_RELATIVE
    if not candidate.exists():
        return _packaged()
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"::warning::could not read {candidate}: {exc}", file=sys.stderr)
        return _packaged()
    if not isinstance(data, dict) or not data:
        print(
            f"::warning::{candidate} is not a suffix-to-type mapping; using the "
            "packaged artifact map",
            file=sys.stderr,
        )
        return _packaged()
    return data


def artifact_types(repo_root: Path) -> tuple[str, ...]:
    """Return every Fabric artifact type name, sorted."""
    return tuple(sorted(load_artifact_map(repo_root).values()))


def suffix_for(folder_name: str, repo_root: Path) -> str | None:
    """Return the artifact suffix ``folder_name`` ends with, or None.

    Case-sensitive on purpose: Fabric's type names are exact, and treating
    `sales.semanticmodel` as an artifact would discover directories that
    merely resemble one.
    """
    for suffix in load_artifact_map(repo_root):
        if folder_name.endswith(suffix):
            return suffix
    return None
