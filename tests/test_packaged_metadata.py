"""Contract tests for metadata that ships with the distribution (TestPyPI Release §2).

Scope
-----
`bpa` and `pbir` are handed a rules file path, and `doctor` reads
`analyzers.json` to learn where a missing tool can be downloaded from.
Both were resolved only under the caller's own `.github/metadata/`, so a
`pip install fab-test` outside this repository reported rules at a path
that did not exist and no install URL for Tabular Editor at all.

These tests guard the two halves of the fix: the files exist in the
package tree, and `package-data` actually ships them. The second half is
not paranoia -- `agents/*` and `skills/*/*` were declared for months and
silently shipped nothing, because a glob that matches no file is not an
error.

They read `pyproject.toml` and the source tree rather than building a
wheel, so they are fast; the built wheel is asserted in CI.
"""

import tomllib
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._metadata import PACKAGED_METADATA

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_PACKAGE = _SRC / "fabric_ci_cd_dataops"

# Every metadata file an analyzer needs before it can do anything.
_REQUIRED = (
    Path("analyzers.json"),
    Path("artifact-map.json"),
    Path("rules") / "BPARules.json",
    Path("rules") / "pbi-inspector-custom-rules.json",
)


@pytest.fixture(scope="module")
def package_data() -> dict[str, list[str]]:
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["setuptools"]["package-data"]


def _shipped_files(package_data: dict[str, list[str]]) -> set[Path]:
    """Expand every package-data glob to the files setuptools will include."""
    shipped: set[Path] = set()
    for package, patterns in package_data.items():
        root = _SRC / Path(*package.split("."))
        for pattern in patterns:
            shipped.update(p.relative_to(_SRC) for p in root.glob(pattern) if p.is_file())
    return shipped


@pytest.mark.fab_test
@pytest.mark.parametrize("relative", _REQUIRED, ids=lambda p: p.as_posix())
def test_every_required_metadata_file_is_in_the_package_tree(relative):
    """An install outside a checkout has only what the package carries."""
    assert (PACKAGED_METADATA / relative).is_file(), f"missing {PACKAGED_METADATA / relative}"


@pytest.mark.fab_test
@pytest.mark.parametrize("relative", _REQUIRED, ids=lambda p: p.as_posix())
def test_every_required_metadata_file_is_shipped(relative, package_data):
    """Being in the tree is not enough; a glob has to match it.

    This is the half that failed before: the files were declared by a
    pattern that did not reach them, and the build said nothing.
    """
    expected = Path("fabric_ci_cd_dataops") / "metadata" / relative

    assert expected in _shipped_files(package_data), f"package-data does not ship {expected.as_posix()}"


@pytest.mark.fab_test
def test_no_package_data_glob_matches_nothing(package_data):
    """A glob matching no file is a promise the wheel does not keep.

    `agents/*` and `skills/*/*` were declared against directories that do
    not exist, so the README told readers to find files after install that
    were never there.
    """
    for package, patterns in package_data.items():
        root = _SRC / Path(*package.split("."))
        for pattern in patterns:
            assert any(root.glob(pattern)), f"{package}: pattern matches nothing: {pattern}"


@pytest.mark.fab_test
@pytest.mark.parametrize("relative", _REQUIRED, ids=lambda p: p.as_posix())
def test_the_packaged_copy_matches_this_repository_copy(relative):
    """Two copies of a file drift, and the stale one answers confidently.

    `.github/metadata/` wins inside this checkout, so a divergence here is
    invisible to every test and every local run -- it only shows up for a
    consumer installing from an index, who has no way to know their rules
    differ from ours.
    """
    packaged = (PACKAGED_METADATA / relative).read_text(encoding="utf-8")
    in_repo = (_ROOT / ".github" / "metadata" / relative).read_text(encoding="utf-8")

    assert packaged == in_repo, f"{relative.as_posix()} has drifted from .github/metadata/"
