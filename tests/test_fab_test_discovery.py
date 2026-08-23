"""Artifact discovery: dry-run listing, .pbip pairing, the `all` analyzer list.

Scope
-----
--dry-run discovery of *.SemanticModel/*.Report folders, .pbip-paired
project discovery (discover_artifacts, discover_pbip_sources,
applicable_analyzers), and the metadata-driven analyzer list `fab-test all`
reads from analyzers.json (_load_fab_test_all_analyzers).

    pytest -m fab_test
"""
import json
import subprocess
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.fab_test import _load_fab_test_all_analyzers
from fabric_ci_cd_dataops.scripts.fab_test_registry import (
    applicable_analyzers,
    discover_artifacts,
    discover_pbip_sources,
)

# --------------------------------------------------------------------------- #
# Dry-run artifact discovery — no external tools needed
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_bpa_dry_run_exits_zero():
    """fab-test bpa --dry-run exits 0 (no Tabular Editor needed)."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_bpa_dry_run_discovers_sample_model():
    """fab-test bpa --dry-run finds the sample SemanticModel."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "SampleModel-PQLAssert" in result.stdout, (
        f"Expected SampleModel-PQLAssert in dry-run output.\nGot: {result.stdout}"
    )


@pytest.mark.fab_test
def test_bpa_dry_run_with_artifact_filter():
    """--artifact STEM filters the discovered artifact list."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run",
         "--artifact", "SampleModel-PQLAssert"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "SampleModel-PQLAssert" in result.stdout


@pytest.mark.fab_test
def test_bpa_dry_run_empty_artifact_dir(tmp_path: Path):
    """--artifact-dir with no matching artifacts exits 0 with a warning."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run",
         "--artifact-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_pbir_dry_run_exits_zero():
    """fab-test pbir --dry-run exits 0 regardless of Report artifact count."""
    result = subprocess.run(
        ["fab-test", "pbir", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_pql_lint_dry_run_exits_zero():
    """fab-test pql_lint --dry-run exits 0."""
    result = subprocess.run(
        ["fab-test", "pql_lint", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# .pbip discovery wired into artifact resolution
# --------------------------------------------------------------------------- #


def _write_pbip_project(root, name, *, with_report=True, with_model=True):
    (root / f"{name}.pbip").write_text(
        json.dumps({"artifacts": [{"report": {"path": f"{name}.Report"}}]}),
        encoding="utf-8",
    )
    if with_report:
        report_dir = root / f"{name}.Report"
        report_dir.mkdir(parents=True)
        (report_dir / "definition.pbir").write_text(
            json.dumps({"datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}}),
            encoding="utf-8",
        )
    if with_model:
        (root / f"{name}.SemanticModel").mkdir(parents=True)


@pytest.mark.fab_test
def test_discover_artifacts_finds_pbip_paired_folder_nested_in_subdirectory(tmp_path):
    """A .pbip project nested below artifact_dir is still discovered."""
    nested = tmp_path / "reports" / "team"
    nested.mkdir(parents=True)
    _write_pbip_project(nested, "Nested", with_report=False)

    artifacts = discover_artifacts(tmp_path, "*.SemanticModel", None)

    assert (nested / "Nested.SemanticModel").resolve() in artifacts


@pytest.mark.fab_test
def test_discover_artifacts_does_not_duplicate_top_level_pbip_project(tmp_path):
    """A .pbip project directly under artifact_dir isn't counted twice."""
    _write_pbip_project(tmp_path, "TopLevel")

    artifacts = discover_artifacts(tmp_path, "*.SemanticModel", None)

    assert artifacts.count((tmp_path / "TopLevel.SemanticModel").resolve()) == 1


@pytest.mark.fab_test
def test_discover_artifacts_stays_restricted_to_artifact_dir(tmp_path):
    """A .pbip project outside artifact_dir is never discovered."""
    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    _write_pbip_project(outside, "Outside", with_report=False)

    artifacts = discover_artifacts(inside, "*.SemanticModel", None)

    assert artifacts == []


@pytest.mark.fab_test
def test_discover_pbip_sources_maps_artifact_to_its_pbip_path(tmp_path):
    """discover_pbip_sources reports which .pbip file pairs each artifact."""
    _write_pbip_project(tmp_path, "Sourced", with_report=False)

    sources = discover_pbip_sources(tmp_path)

    model_path = (tmp_path / "Sourced.SemanticModel").resolve()
    assert sources[model_path] == (tmp_path / "Sourced.pbip").resolve()


@pytest.mark.fab_test
def test_applicable_analyzers_for_semantic_model():
    """A .SemanticModel folder is applicable to bpa, pql_test, and pql_lint."""
    assert applicable_analyzers(Path("Foo.SemanticModel")) == ("bpa", "pql_test", "pql_lint")


@pytest.mark.fab_test
def test_applicable_analyzers_for_report():
    """A .Report folder is applicable to pbir and playwright."""
    assert applicable_analyzers(Path("Foo.Report")) == ("pbir", "playwright")


@pytest.mark.fab_test
def test_bpa_dry_run_lists_applicable_analyzers():
    """Dry-run output names the analyzers applicable to each discovered artifact."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pql_test" in result.stdout


@pytest.mark.fab_test
def test_bpa_dry_run_empty_artifact_dir_names_directory_and_suffix(tmp_path):
    """The 'nothing found' message names the directory it searched and the
    folder suffix it searched for.

    It used to also claim `.pbip` projects were searched, which offered a
    caller a second route to being found that has not existed since
    discovery went suffix-based (Empty Discovery Diagnostics §2).
    """
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run", "--artifact-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert str(tmp_path) in combined
    assert "*.SemanticModel" in combined
    assert ".pbip" not in combined


# --------------------------------------------------------------------------- #
# Metadata-driven analyzer list for `fab-test all`
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_reads_metadata(tmp_path):
    """The analyzer list for `all` is read from analyzers.json."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text(
        json.dumps({"fab_test_all": ["bpa", "pbir"]}),
        encoding="utf-8",
    )
    assert _load_fab_test_all_analyzers(metadata) == ("bpa", "pbir")


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_ignores_non_string_items(tmp_path):
    """Only string items in the list are returned."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text(
        json.dumps({"fab_test_all": ["bpa", 123, None, "pbir"]}),
        encoding="utf-8",
    )
    assert _load_fab_test_all_analyzers(metadata) == ("bpa", "pbir")


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_falls_back_on_missing_file(tmp_path):
    """A missing or unreadable file falls back to the historical default."""
    missing = tmp_path / "analyzers.json"
    assert _load_fab_test_all_analyzers(missing) == (
        "bpa",
        "pbir",
        "pql_test",
        "pql_lint",
    )


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_falls_back_on_bad_json(tmp_path):
    """Malformed JSON falls back to the historical default."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text("not json", encoding="utf-8")
    assert _load_fab_test_all_analyzers(metadata) == (
        "bpa",
        "pbir",
        "pql_test",
        "pql_lint",
    )


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_falls_back_when_key_missing(tmp_path):
    """A valid JSON file without fab_test_all falls back to the default."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text(json.dumps({"analyzer_registry": {}}), encoding="utf-8")
    assert _load_fab_test_all_analyzers(metadata) == (
        "bpa",
        "pbir",
        "pql_test",
        "pql_lint",
    )


@pytest.mark.fab_test
def test_all_dry_run_uses_metadata_list_not_pql_lint():
    """`fab-test all --dry-run` skips analyzers excluded from metadata."""
    result = subprocess.run(
        ["fab-test", "all", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # pql_lint is excluded from fab_test_all in the committed metadata.
    assert "fab-test pql_lint" not in result.stdout
    assert "fab-test bpa" in result.stdout
    assert "fab-test pbir" in result.stdout
    assert "fab-test pql_test" in result.stdout


@pytest.mark.fab_test
def test_pql_lint_direct_subcommand_still_works_dry_run():
    """`fab-test pql_lint` can still be invoked directly even when excluded from `all`."""
    result = subprocess.run(
        ["fab-test", "pql_lint", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fab-test pql_lint" in result.stdout


