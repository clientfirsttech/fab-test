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

Not every file can take that fallback (Environments Metadata Layers §2).
`environments.yml` carries workspace GUIDs and branch policy, so a copy
baked into the wheel would silently aim a `prod` deployment at whatever
workspace was packaged -- and report success while doing it. Those callers
pass ``packaged=False`` and get `MetadataNotFoundError` naming every place
the file could live. `resolve_environments_yml` fixes that rule in one
place so none of its six callers can spell it wrong.

Paths only. Rules files are handed to Tabular Editor and PBIR Inspector as
arguments and never parsed here; `_artifact_types` keeps the loading and
validation that its own map needs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

PACKAGED_METADATA = Path(__file__).resolve().parent.parent / "metadata"

# Searched in order; the first readable file wins. `.fab-test/metadata` is
# what a consumer is told to create -- fab-test's own directory, alongside
# `.fab-test-tools/`. `.github/metadata` is searched only for consumer
# repositories already on that legacy layout, per the backward-compatibility
# constraint in vision.md -- not because any workflow in this repository
# reads it: this repository itself moved onto `.fab-test/metadata/`
# (Playwright Through The Front Door §7), and none of its four remaining
# workflows ever referenced `.github/metadata`. A consumer is never told to
# create it: `.github/` belongs to GitHub, not to us.
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
ARTIFACT_MAP = Path("artifact-map.json")
ENVIRONMENTS = Path("environments.yml")


class ResolvedMetadata(NamedTuple):
    """A metadata file and the layer it came from.

    A `NamedTuple` rather than a bare tuple so the six `environments.yml`
    call sites can say `.path` instead of indexing, while the three callers
    that already destructure ``resolved, origin`` keep working untouched.
    `__fspath__` lets it drop straight into `open()` at the sites that used
    to hold a plain `Path`.
    """

    path: Path
    origin: str

    def __fspath__(self) -> str:
        return str(self.path)


class MetadataNotFoundError(Exception):
    """No layer supplies a metadata file that has no packaged default.

    Carries the candidates so a caller can name every place the file could
    live rather than only the last place it looked.
    """

    def __init__(self, relative: Path, candidates: list[Path]) -> None:
        places = " or ".join(str(path) for path in candidates)
        super().__init__(f"{relative} not found. Create it at {places}.")
        self.relative = relative
        self.candidates = candidates


def default_repo_root() -> Path:
    """Return the repository root for the directory the CLI was invoked from.

    The single decider for the whole CLI: `fab_test` and `fab_test_registry`
    both call this rather than keeping copies, because three copies of one
    rule is three places for it to stop agreeing -- and it did.

    ``GITHUB_WORKSPACE`` wins only when the working directory is inside it.
    That preserves what the variable is for, so `cd src && fab-test bpa` in a
    workflow still resolves to the checkout root instead of depending on
    which directory a step happened to be standing in. It used to win
    unconditionally, which meant that inside GitHub Actions the CLI ignored
    where it was invoked from entirely: `cd elsewhere && fab-test init` wrote
    its config to the workspace root, silently.

    Discover From CWD made the working directory meaningful, so this
    deliberately does not walk up looking for a `.git` directory.
    """
    cwd = Path.cwd().resolve()
    workspace = os.getenv("GITHUB_WORKSPACE")
    if not workspace:
        return cwd
    root = Path(workspace).resolve()
    # is_relative_to, not a prefix comparison: `/work/repo-2` must not count
    # as being inside `/work/repo`.
    return root if cwd.is_relative_to(root) else cwd


def candidates(relative: Path | str, repo_root: Path, *, packaged: bool = True) -> list[Path]:
    """Return every path ``relative`` could resolve to, in precedence order."""
    paths = [repo_root / directory / relative for directory, _ in _OVERRIDE_LAYERS]
    if packaged:
        paths.append(PACKAGED_METADATA / relative)
    return paths


def resolve_metadata(
    relative: Path | str, repo_root: Path, *, packaged: bool = True
) -> ResolvedMetadata:
    """Return the metadata file at ``relative`` and the layer it came from.

    ``relative`` is a path under a metadata directory, e.g.
    ``rules/BPARules.json``. The origin is one of ``".fab-test/metadata"``,
    ``".github/metadata"``, or ``"packaged"`` -- reported by
    `fab-test config --show` so a caller can see which ruleset is in force
    without guessing from the path.

    Falls through to the packaged copy silently. An absent override is a
    default, not a problem: warning would put a line on every run of every
    consumer who never asked to override anything.

    ``packaged=False`` drops that last resort for a file that must never be
    answered from the wheel, and raises `MetadataNotFoundError` instead.
    """
    for directory, origin in _OVERRIDE_LAYERS:
        candidate = repo_root / directory / relative
        if candidate.is_file():
            return ResolvedMetadata(candidate, origin)
    if not packaged:
        raise MetadataNotFoundError(
            Path(relative), candidates(relative, repo_root, packaged=False)
        )
    return ResolvedMetadata(PACKAGED_METADATA / relative, PACKAGED_ORIGIN)


def metadata_path(relative: Path | str, repo_root: Path) -> Path:
    """Return the metadata file at ``relative``, overrides first.

    For callers that need the path and not where it came from.
    """
    return resolve_metadata(relative, repo_root).path


def resolve_environments_yml(repo_root: Path | None = None) -> ResolvedMetadata:
    """Return `environments.yml` from a repository layer, never from the wheel.

    The one place ``packaged=False`` is spelled for this file, so that no
    caller among `deploy`, `check_promotion_safety`,
    `generate_fabric_cicd_config`, the two schema validators, and the
    Playwright resolver can get the rule wrong on its own.

    Raises `MetadataNotFoundError` naming both places the file could go.
    """
    return resolve_metadata(
        ENVIRONMENTS, repo_root if repo_root is not None else default_repo_root(), packaged=False
    )
