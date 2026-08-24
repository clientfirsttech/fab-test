"""Contract tests for artifact-type resolution (Discover From CWD §1).

Scope
-----
`artifact-map.json` declares which folder suffixes are Fabric artifacts. A
repository layer (`.fab-test/metadata` or `.github/metadata`) wins when
present; otherwise resolution falls back to the copy packaged with the
distribution, so an install from PyPI -- or a run from any directory that
is not a fab-test repository -- still knows what an artifact looks like.

Playwright Through The Front Door §7 deleted this repository's own copy of
`artifact-map.json` from `.github/metadata/`: it was byte-identical to the
packaged copy, so keeping both was a drift risk with nothing to show for
it. There is now exactly one copy to test, not two to compare.

Always passes on any machine.
"""

import json
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._artifact_types import (
    PACKAGED_ARTIFACT_MAP,
    artifact_types,
    load_artifact_map,
    suffix_for,
)

_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Where the map comes from
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_this_repository_no_longer_keeps_a_redundant_github_metadata_copy():
    """The byte-identical copy is gone from `.github/metadata/`.

    Resolution for this repository now falls through to the packaged copy,
    the same as any other install; this guards against a stale copy
    quietly coming back.
    """
    stale_path = _ROOT / ".github" / "metadata" / "artifact-map.json"

    assert not stale_path.exists(), f"{stale_path} should not exist -- resolve from the packaged copy"


@pytest.mark.fab_test
def test_a_directory_without_the_map_falls_back(tmp_path):
    """An install from PyPI has no .github/metadata; it must still work."""
    loaded = load_artifact_map(tmp_path)

    assert loaded == json.loads(PACKAGED_ARTIFACT_MAP.read_text(encoding="utf-8"))
    assert loaded, "the fallback must not be empty"


@pytest.mark.fab_test
def test_this_repository_resolves_the_map_from_the_packaged_copy():
    """With no repository-layer copy left, this repository reads the same
    packaged map every other install falls back to."""
    assert load_artifact_map(_ROOT) == json.loads(
        PACKAGED_ARTIFACT_MAP.read_text(encoding="utf-8")
    )


@pytest.mark.fab_test
def test_the_packaged_copy_is_declared_as_package_data():
    """Otherwise it is missing from the wheel and the fallback is a crash."""
    import tomllib

    config = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["fabric_ci_cd_dataops"]

    assert any("metadata" in p for p in patterns), patterns


@pytest.mark.fab_test
def test_a_malformed_map_falls_back_and_warns(tmp_path, capsys):
    """A broken file must not be worse than a missing one."""
    bad = tmp_path / ".github" / "metadata"
    bad.mkdir(parents=True)
    (bad / "artifact-map.json").write_text("{not json", encoding="utf-8")

    loaded = load_artifact_map(tmp_path)

    assert loaded == json.loads(PACKAGED_ARTIFACT_MAP.read_text(encoding="utf-8"))
    assert "artifact-map.json" in capsys.readouterr().err


@pytest.mark.fab_test
def test_a_map_that_is_not_an_object_falls_back(tmp_path):
    """A JSON array parses fine and is still not a suffix mapping."""
    bad = tmp_path / ".github" / "metadata"
    bad.mkdir(parents=True)
    (bad / "artifact-map.json").write_text('["SemanticModel"]', encoding="utf-8")

    assert load_artifact_map(tmp_path) == json.loads(
        PACKAGED_ARTIFACT_MAP.read_text(encoding="utf-8")
    )


# --------------------------------------------------------------------------- #
# What it exposes
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_artifact_types_covers_every_type_the_map_declares():
    """Nine, not the two the hardcoded lists knew."""
    types = set(artifact_types(_ROOT))

    assert {"SemanticModel", "Report", "Notebook", "Lakehouse"} <= types
    assert len(types) >= 9


@pytest.mark.fab_test
def test_a_folder_name_resolves_to_its_suffix():
    assert suffix_for("Sales.SemanticModel", _ROOT) == ".SemanticModel"
    assert suffix_for("Sales.Notebook", _ROOT) == ".Notebook"


@pytest.mark.fab_test
def test_a_folder_with_no_known_suffix_resolves_to_nothing():
    """`definition` and `fab-test-results` are folders, not artifacts."""
    assert suffix_for("definition", _ROOT) is None
    assert suffix_for("Sales", _ROOT) is None


@pytest.mark.fab_test
def test_suffix_matching_is_case_sensitive():
    """Fabric's type names are exact; a lowercase folder is not an artifact."""
    assert suffix_for("Sales.semanticmodel", _ROOT) is None
