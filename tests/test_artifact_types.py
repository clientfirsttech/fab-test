"""Contract tests for artifact-type resolution (Discover From CWD §1).

Scope
-----
`.github/metadata/artifact-map.json` declares which folder suffixes are
Fabric artifacts. It already existed and `fab-test` never read it, keeping
three hardcoded copies that each knew two of its nine types.

The repository copy wins when present. A packaged copy ships with the
distribution so an install from PyPI — or a run from any directory that is
not this repository — still knows what an artifact looks like. A test
asserts the two agree, because a fallback that has drifted is worse than
no fallback: it would answer confidently and wrongly.

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
_REPO_MAP = _ROOT / ".github" / "metadata" / "artifact-map.json"


# --------------------------------------------------------------------------- #
# Where the map comes from
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_the_repository_map_is_used_when_present():
    """The repo's own declaration wins; that is the point of reading it."""
    expected = json.loads(_REPO_MAP.read_text(encoding="utf-8"))

    assert load_artifact_map(_ROOT) == expected


@pytest.mark.fab_test
def test_a_directory_without_the_map_falls_back(tmp_path):
    """An install from PyPI has no .github/metadata; it must still work."""
    loaded = load_artifact_map(tmp_path)

    assert loaded == json.loads(PACKAGED_ARTIFACT_MAP.read_text(encoding="utf-8"))
    assert loaded, "the fallback must not be empty"


@pytest.mark.fab_test
def test_the_packaged_copy_matches_the_repository_copy():
    """A drifted fallback answers confidently and wrongly, which is worse
    than having none at all."""
    packaged = json.loads(PACKAGED_ARTIFACT_MAP.read_text(encoding="utf-8"))
    repository = json.loads(_REPO_MAP.read_text(encoding="utf-8"))

    assert packaged == repository


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
    """`definition` and `analyzer-results` are folders, not artifacts."""
    assert suffix_for("definition", _ROOT) is None
    assert suffix_for("Sales", _ROOT) is None


@pytest.mark.fab_test
def test_suffix_matching_is_case_sensitive():
    """Fabric's type names are exact; a lowercase folder is not an artifact."""
    assert suffix_for("Sales.semanticmodel", _ROOT) is None
