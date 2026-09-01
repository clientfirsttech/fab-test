"""Contract tests for .pbip project discovery (Local Desktop First Run §1).

Finds *.pbip files wherever they live in a repository — not only under the
fixed .fabric/artifacts layout — and resolves each project's paired
.Report and .SemanticModel folders. Always passes on any machine — no
external tool or real Power BI project required.

    pytest -m fab_test tests/test_pbip_discovery.py
"""

import json

import pytest

from fab_test.scripts._pbip_discovery import discover_pbip_projects


def _write_pbip(root, name, report_relpath):
    pbip_path = root / f"{name}.pbip"
    pbip_path.write_text(
        json.dumps({"version": "1.0", "artifacts": [{"report": {"path": report_relpath}}]}),
        encoding="utf-8",
    )
    return pbip_path


def _write_report(root, name, semantic_model_relpath):
    report_dir = root / f"{name}.Report"
    report_dir.mkdir(parents=True)
    (report_dir / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": semantic_model_relpath}}}),
        encoding="utf-8",
    )
    return report_dir


def _write_semantic_model(root, name):
    model_dir = root / f"{name}.SemanticModel"
    model_dir.mkdir(parents=True)
    return model_dir


@pytest.mark.fab_test
def test_discover_returns_project_with_paired_folders(tmp_path):
    """A .pbip with both paired folders present resolves both paths and is complete."""
    _write_pbip(tmp_path, "SampleModel", "SampleModel.Report")
    _write_report(tmp_path, "SampleModel", "../SampleModel.SemanticModel")
    _write_semantic_model(tmp_path, "SampleModel")

    projects = discover_pbip_projects(tmp_path)

    assert len(projects) == 1
    project = projects[0]
    assert project.name == "SampleModel"
    assert project.report_path == (tmp_path / "SampleModel.Report").resolve()
    assert project.semantic_model_path == (tmp_path / "SampleModel.SemanticModel").resolve()
    assert project.is_complete is True


@pytest.mark.fab_test
def test_discover_reports_incomplete_when_semantic_model_missing(tmp_path):
    """A project whose paired SemanticModel folder is absent is reported, not skipped."""
    _write_pbip(tmp_path, "Orphan", "Orphan.Report")
    _write_report(tmp_path, "Orphan", "../Orphan.SemanticModel")
    # No SemanticModel folder written.

    projects = discover_pbip_projects(tmp_path)

    assert len(projects) == 1
    assert projects[0].semantic_model_path is None
    assert projects[0].is_complete is False


@pytest.mark.fab_test
def test_discover_reports_incomplete_when_report_missing(tmp_path):
    """A .pbip whose report folder is absent is reported as incomplete, not skipped."""
    _write_pbip(tmp_path, "NoReport", "NoReport.Report")
    # No Report folder written, no SemanticModel folder written.

    projects = discover_pbip_projects(tmp_path)

    assert len(projects) == 1
    assert projects[0].report_path is None
    assert projects[0].semantic_model_path is None
    assert projects[0].is_complete is False


@pytest.mark.fab_test
def test_discover_returns_empty_list_for_directory_with_no_projects(tmp_path):
    """A directory with no .pbip files returns an empty list without raising."""
    (tmp_path / "unrelated.txt").write_text("nothing here", encoding="utf-8")

    assert discover_pbip_projects(tmp_path) == []


@pytest.mark.fab_test
def test_discover_returns_empty_list_when_root_does_not_exist(tmp_path):
    """A nonexistent root returns an empty list without raising."""
    missing_root = tmp_path / "does-not-exist"

    assert discover_pbip_projects(missing_root) == []


@pytest.mark.fab_test
def test_discover_falls_back_to_naming_convention_when_pbip_unparseable(tmp_path):
    """Malformed .pbip JSON falls back to the <name>.Report naming convention."""
    (tmp_path / "Fallback.pbip").write_text("not valid json", encoding="utf-8")
    _write_report(tmp_path, "Fallback", "../Fallback.SemanticModel")
    _write_semantic_model(tmp_path, "Fallback")

    projects = discover_pbip_projects(tmp_path)

    assert len(projects) == 1
    assert projects[0].report_path == (tmp_path / "Fallback.Report").resolve()
    assert projects[0].semantic_model_path == (tmp_path / "Fallback.SemanticModel").resolve()


@pytest.mark.fab_test
def test_discover_finds_multiple_projects_in_nested_directories(tmp_path):
    """Projects are found recursively, wherever they live under root."""
    nested = tmp_path / "workspace" / "team-reports"
    nested.mkdir(parents=True)
    _write_pbip(nested, "Nested", "Nested.Report")
    _write_report(nested, "Nested", "../Nested.SemanticModel")
    _write_semantic_model(nested, "Nested")

    projects = discover_pbip_projects(tmp_path)

    assert len(projects) == 1
    assert projects[0].name == "Nested"


@pytest.mark.fab_test
def test_discover_skips_pbip_files_inside_excluded_directories(tmp_path):
    """A `.pbip` inside a directory `_scan.EXCLUDED_DIR_NAMES` prunes (`.venv`,
    `node_modules`, ...) is not discovered -- a vendored sample or cached
    wheel should not surface as a project any more than a folder-suffix
    artifact would (pbip Discovery Shared Pruning epic)."""
    excluded = tmp_path / ".venv" / "lib"
    excluded.mkdir(parents=True)
    _write_pbip(excluded, "Vendored", "Vendored.Report")

    visible = tmp_path / "workspace"
    visible.mkdir()
    _write_pbip(visible, "Real", "Real.Report")
    _write_report(visible, "Real", "../Real.SemanticModel")
    _write_semantic_model(visible, "Real")

    projects = discover_pbip_projects(tmp_path)

    assert [p.name for p in projects] == ["Real"]


@pytest.mark.fab_test
def test_discover_skips_projects_inside_a_nested_git_checkout(tmp_path):
    """A .pbip inside a separate git checkout (e.g. a worktree under
    .claude/worktrees/<branch>) is not discovered -- a broad repo-root walk
    shouldn't double-count the same fixture living in two checkouts. A
    dot-prefixed directory that ISN'T a separate checkout (like .fabric,
    this project's own artifacts root) is still searched.
    """
    nested_checkout = tmp_path / ".claude" / "worktrees" / "some-branch"
    nested_checkout.mkdir(parents=True)
    (nested_checkout / ".git").write_text("gitdir: ../../../.git/worktrees/some-branch\n", encoding="utf-8")
    inside_checkout = nested_checkout / ".fabric" / "artifacts"
    inside_checkout.mkdir(parents=True)
    _write_pbip(inside_checkout, "Hidden", "Hidden.Report")
    _write_report(inside_checkout, "Hidden", "../Hidden.SemanticModel")
    _write_semantic_model(inside_checkout, "Hidden")

    visible = tmp_path / ".fabric" / "artifacts"
    visible.mkdir(parents=True)
    _write_pbip(visible, "Visible", "Visible.Report")
    _write_report(visible, "Visible", "../Visible.SemanticModel")
    _write_semantic_model(visible, "Visible")

    projects = discover_pbip_projects(tmp_path)

    assert [p.name for p in projects] == ["Visible"]
