"""Contract tests for metadata that ships with the distribution (TestPyPI Release §2).

Scope
-----
`bpa` and `pbir` are handed a rules file path, and `doctor` reads
`analyzers.json` to learn where a missing tool can be downloaded from.
Both were resolved only under the caller's own `.github/metadata/`, so a
`pip install cft-fab-test` outside this repository reported rules at a path
that did not exist and no install URL for Tabular Editor at all.

These tests guard the two halves of the fix: the files exist in the
package tree, and `package-data` actually ships them. The second half is
not paranoia -- `agents/*` and `skills/*/*` were declared for months and
silently shipped nothing, because a glob that matches no file is not an
error.

They read `pyproject.toml` and the source tree rather than building a
wheel, so they are fast; the built wheel is asserted in CI.

Playwright Through The Front Door §7 deleted this repository's own copies
of these four files from `.github/metadata/` -- they were byte-identical
to the packaged copy, so keeping both was a drift risk with nothing to
show for it. There is now exactly one copy to test, not two to compare;
the packaged tree is still the real subject worth asserting, since a
consumer's fresh install has only what the wheel carries.
"""

import tomllib
from pathlib import Path

import pytest

from fab_test.scripts._metadata import PACKAGED_METADATA

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
_PACKAGE = _SRC / "fab_test"

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
    expected = Path("fab_test") / "metadata" / relative

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
def test_this_repository_no_longer_keeps_a_redundant_github_metadata_copy():
    """The four byte-identical files are gone from `.github/metadata/`.

    They used to duplicate the packaged copy exactly, which is what
    `test_the_packaged_copy_matches_this_repository_copy` used to guard --
    a redundant copy that could only drift, never diverge usefully. Deleting
    them means resolution for this repository now falls through to the
    packaged copy for every one of them (Playwright Through The Front Door
    §7); this test guards against a stale copy quietly coming back.
    """
    github_metadata = _ROOT / ".github" / "metadata"
    for relative in _REQUIRED:
        stale_path = github_metadata / relative
        assert not stale_path.exists(), f"{stale_path} should not exist -- resolve from the packaged copy"


@pytest.mark.fab_test
def test_environments_yml_lives_under_fab_test_metadata():
    """`environments.yml` moved to `.fab-test/metadata/`, the packaged layout.

    It has no packaged fallback (Environments Metadata Layers §2) and was
    the only file in `.github/metadata/` actually doing work, so it moved
    rather than being deleted.
    """
    assert (_ROOT / ".fab-test" / "metadata" / "environments.yml").is_file()
    assert not (_ROOT / ".github" / "metadata" / "environments.yml").exists()
