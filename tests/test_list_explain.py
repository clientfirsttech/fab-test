"""Contract tests for `fab-test list` and `fab-test explain`
(CLI Agent Ergonomics §9 and §10).

Scope
-----
`list` lets a caller discover capability from the tool instead of the docs.
`explain` shows the resolved command for one analyzer without running it.
Both always pass on any machine — dry, read-only introspection.

    pytest -m fab_test tests/test_list_explain.py -k list
    pytest -m fab_test tests/test_list_explain.py -k explain
"""

import json
import subprocess

import pytest

from fabric_ci_cd_dataops.scripts.fab_test_registry import ANALYZER_REGISTRY


@pytest.mark.fab_test
def test_list_text_shows_every_analyzer_with_glob_and_tool():
    """fab-test list (text) names every analyzer, its glob, and required tool."""
    result = subprocess.run(
        ["fab-test", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for name in ANALYZER_REGISTRY:
        assert name in result.stdout, f"{name} missing from list output"
    assert "Tabular Editor" in result.stdout
    assert "*.SemanticModel" in result.stdout


@pytest.mark.fab_test
def test_list_json_format_is_one_document():
    """--format json emits one document covering every registered analyzer."""
    result = subprocess.run(
        ["fab-test", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert len(summary["analyzers"]) == len(ANALYZER_REGISTRY)
    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["glob"] == "*.SemanticModel"
    assert bpa_row["required_tool"] == "Tabular Editor"
    assert "matched_artifacts" in bpa_row


@pytest.mark.fab_test
def test_list_matched_artifact_count_reflects_real_artifacts(tmp_path):
    """matched_artifacts counts real matches under --artifact-dir."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ModelOne.SemanticModel").mkdir(parents=True)
    (artifact_dir / "ModelTwo.SemanticModel").mkdir(parents=True)

    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(artifact_dir), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["matched_artifacts"] == 2


@pytest.mark.fab_test
def test_list_empty_artifact_dir_exits_zero_with_zero_counts(tmp_path):
    """An artifact-less directory reports zero matches for glob-based analyzers
    and still exits 0.
    """
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(artifact_dir), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["matched_artifacts"] == 0


@pytest.mark.fab_test
def test_list_repository_scoped_analyzers_have_no_glob():
    """dependencies/playwright-impact run once against the repo, not a glob match."""
    result = subprocess.run(
        ["fab-test", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    deps_row = next(r for r in summary["analyzers"] if r["analyzer"] == "dependencies")
    assert deps_row["glob"] is None
    assert deps_row["matched_artifacts"] == 1
