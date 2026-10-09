"""Contract tests for `fab-test playwright --changed-since REF`.

Change detection runs against a real throwaway Git repository; only the
Fabric service is faked, by the same in-memory client the impact tests use.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts import _playwright_changed as changed
from fab_test.scripts._mode import resolve_mode
from fab_test.scripts._playwright_dataset_target import (
    REPORT_NAMES_ATTR,
    REPORT_WORKSPACES_ATTR,
    DatasetTargetExit,
)
from fab_test.scripts.detect_changes import ChangeDetectionError, changed_artifacts_since

from .test_playwright_impact import FakeClient

pytestmark = pytest.mark.playwright

WS = "11111111-1111-1111-1111-111111111111"


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)


def _write(repo: Path, relative: str, text: str = "x") -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on `main` holding one model and one report."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _write(root, "fabric-artifacts/Sales.SemanticModel/definition/model.tmdl")
    _write(root, "fabric-artifacts/Sales Report.Report/definition/report.json")
    _write(root, "README.md")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "feature")
    return root


def _names(repo: Path, ref: str = "main") -> list[str]:
    return sorted(a["name"] for a in changed_artifacts_since(repo, ref))


def test_given_a_committed_model_change_should_report_that_model(repo):
    _write(repo, "fabric-artifacts/Sales.SemanticModel/definition/model.tmdl", "changed")
    _git(repo, "commit", "-qam", "change model")
    assert _names(repo) == ["Sales.SemanticModel"]


def test_given_uncommitted_and_untracked_changes_should_count_both(repo):
    _write(repo, "fabric-artifacts/Sales Report.Report/definition/report.json", "edited")
    _write(repo, "fabric-artifacts/New.SemanticModel/definition/model.tmdl")
    assert _names(repo) == ["New.SemanticModel", "Sales Report.Report"]


def test_given_only_non_artifact_changes_should_report_nothing(repo):
    _write(repo, "README.md", "edited")
    assert _names(repo) == []


def test_given_an_unknown_ref_should_raise_naming_it(repo):
    with pytest.raises(ChangeDetectionError, match="no-such-branch"):
        changed_artifacts_since(repo, "no-such-branch")


def test_given_a_folder_outside_git_should_raise_naming_the_ref(tmp_path):
    with pytest.raises(ChangeDetectionError, match="main"):
        changed_artifacts_since(tmp_path, "main")


def _args(repo: Path, **extra) -> argparse.Namespace:
    workspace = extra.pop("workspace_id", WS)
    ns = argparse.Namespace(
        workspace_id=workspace,
        changed_since=extra.pop("changed_since", "main"),
        artifact_dir=str(repo),
        artifact_dir_explicit=False,
        output_format="text",
        playwright_env_file=None,
        environment="",
        resolved_target=None,
        **extra,
    )
    ns.resolved_mode = resolve_mode(None, workspace_flag=workspace)
    return ns


@pytest.fixture
def fabric(monkeypatch) -> FakeClient:
    """Sales Report is deployed on the Sales model; Other Report on another model."""
    client = FakeClient()
    client.add_item(WS, "SemanticModel", "sm-sales", "Sales")
    client.add_item(WS, "SemanticModel", "sm-other", "Other")
    client.add_item(WS, "Report", "rpt-sales", "Sales Report")
    client.add_item(WS, "Report", "rpt-other", "Other Report")
    client.add_dependent(WS, "sm-sales", "rpt-sales", "Sales Report")
    client.add_dependent(WS, "sm-other", "rpt-other", "Other Report")
    monkeypatch.setattr(changed, "build_fabric_service_client", lambda **kwargs: client)
    return client


def test_given_a_changed_model_should_target_only_its_deployed_reports(repo, fabric, capsys):
    _write(repo, "fabric-artifacts/Sales.SemanticModel/definition/model.tmdl", "changed")
    args = _args(repo)
    assert changed.resolve_changed_reports(args) == [Path("Sales Report.Report")]
    assert getattr(args, REPORT_WORKSPACES_ATTR) == {"Sales Report": WS}
    assert getattr(args, REPORT_NAMES_ATTR) == {"Sales Report": "Sales Report"}
    assert "Sales Report" in capsys.readouterr().out


def test_given_a_new_undeployed_report_should_skip_it_and_test_the_rest(repo, fabric, capsys):
    _write(repo, "fabric-artifacts/Sales.SemanticModel/definition/model.tmdl", "changed")
    _write(repo, "fabric-artifacts/Brand New.Report/definition/report.json")
    assert changed.resolve_changed_reports(_args(repo)) == [Path("Sales Report.Report")]
    out = capsys.readouterr().out
    assert "Brand New" in out
    assert "not deployed" in out


def test_given_no_artifact_changes_should_exit_0_saying_nothing_changed(repo, fabric, capsys):
    with pytest.raises(DatasetTargetExit) as stopped:
        changed.resolve_changed_reports(_args(repo))
    assert stopped.value.code == 0
    assert "changed since main" in capsys.readouterr().out


def test_given_changes_affecting_no_deployed_report_should_exit_0_saying_so(repo, fabric, capsys):
    _write(repo, "fabric-artifacts/Unused.SemanticModel/definition/model.tmdl")
    fabric.add_item(WS, "SemanticModel", "sm-unused", "Unused")
    with pytest.raises(DatasetTargetExit) as stopped:
        changed.resolve_changed_reports(_args(repo))
    assert stopped.value.code == 0
    assert "no deployed report" in capsys.readouterr().out


def test_given_a_bad_ref_should_exit_2_before_calling_fabric(repo, monkeypatch, capsys):
    monkeypatch.setattr(changed, "build_fabric_service_client", lambda **kwargs: pytest.fail("no network"))
    with pytest.raises(DatasetTargetExit) as stopped:
        changed.resolve_changed_reports(_args(repo, changed_since="no-such-branch"))
    assert stopped.value.code == 2
    assert "no-such-branch" in capsys.readouterr().err


def _cli(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        env={**os.environ, "FABRIC_WORKSPACE_ID": "", "PYTHONIOENCODING": "utf-8"},
        cwd=cwd,
        check=False,
    )


def test_given_changed_since_without_workspace_should_exit_2_naming_workspace(repo):
    result = _cli("playwright", "--changed-since", "main", cwd=repo)
    assert result.returncode == 2
    assert "--workspace" in result.stderr


def test_given_changed_since_with_workspace_should_print_service_mode(repo):
    result = _cli("playwright", "--workspace", WS, "--changed-since", "main", "--dry-run", cwd=repo)
    assert result.stderr.splitlines()[0] == f"mode=service workspace={WS} source=flag"


def test_playwright_impact_is_no_longer_a_command():
    result = _cli("playwright-impact", "--help")
    assert result.returncode == 2
    assert "unknown analyzer 'playwright-impact'" in result.stderr


def test_playwright_help_lists_changed_since_but_not_impact_manifest():
    help_text = _cli("playwright", "--help").stdout
    assert "--changed-since" in help_text
    assert "--impact-manifest" not in help_text
