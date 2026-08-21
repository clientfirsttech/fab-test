"""Where fab-test finds the metadata its analyzers need (TestPyPI Release §2).

`bpa` receives a rules file path, `pbir` receives its own, and `doctor`
reads `analyzers.json` to learn where a missing tool can be downloaded
from. All three were resolved only under the caller's own
`.github/metadata/`, which is this repository's layout -- so a
`pip install fab-test` anywhere else reported rules at a path that did not
exist, and offered no install URL for Tabular Editor at all.

The repository copy still wins when present, so this repository and the
reference implementation are unaffected. A copy packaged with the
distribution covers every other install. This is the same arrangement
`_artifact_types` already uses for `artifact-map.json`, and for the same
reason: the caller needs a working answer, not a path to a missing file.

Paths only. Rules files are handed to Tabular Editor and PBIR Inspector as
arguments and never parsed here; `_artifact_types` keeps the loading and
validation that its own map needs.
"""

from __future__ import annotations

from pathlib import Path

PACKAGED_METADATA = Path(__file__).resolve().parent.parent / "metadata"

# Searched in order; the first readable file wins. `.fab-test/metadata` is
# what a consumer is told to create -- fab-test's own directory, alongside
# `.fab-test-tools/`. `.github/metadata` is this repository's own layout and
# stays searched only so existing repositories and every workflow under
# `.github/workflows/` keep working, per the backward-compatibility
# constraint in vision.md. A consumer is never told to create it: `.github/`
# belongs to GitHub, not to us.
_OVERRIDE_LAYERS: tuple[tuple[Path, str], ...] = (
    (Path(".fab-test") / "metadata", ".fab-test/metadata"),
    (Path(".github") / "metadata", ".github/metadata"),
)

PACKAGED_ORIGIN = "packaged"

# Named once here so the registry (which needs the path) and
# `config --show` (which needs the origin too) cannot disagree about which
# file they mean.
BPA_RULES = Path("rules") / "BPARules.json"
PBIR_RULES = Path("rules") / "pbi-inspector-custom-rules.json"
ANALYZERS = Path("analyzers.json")


def resolve_metadata(relative: Path | str, repo_root: Path) -> tuple[Path, str]:
    """Return the metadata file at ``relative`` and the layer it came from.

    ``relative`` is a path under a metadata directory, e.g.
    ``rules/BPARules.json``. The origin is one of ``".fab-test/metadata"``,
    ``".github/metadata"``, or ``"packaged"`` -- reported by
    `fab-test config --show` so a caller can see which ruleset is in force
    without guessing from the path.

    Falls through to the packaged copy silently. An absent override is a
    default, not a problem: warning would put a line on every run of every
    consumer who never asked to override anything.
    """
    for directory, origin in _OVERRIDE_LAYERS:
        candidate = repo_root / directory / relative
        if candidate.is_file():
            return candidate, origin
    return PACKAGED_METADATA / relative, PACKAGED_ORIGIN


def metadata_path(relative: Path | str, repo_root: Path) -> Path:
    """Return the metadata file at ``relative``, overrides first.

    For callers that need the path and not where it came from.
    """
    return resolve_metadata(relative, repo_root)[0]
