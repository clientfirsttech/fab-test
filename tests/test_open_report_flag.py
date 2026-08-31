"""Contract tests for `--open-report` and its resolution (Open Report Flag epic, Task 1).

Scope
-----
This covers only resolution: `--open-report` turning on `open_report` and
auto-enabling `report`, its env var, and the explicit `--no-report
--open-report` conflict. Actually opening a browser (Task 2) and wiring the
resolved path into each run shape (Task 3) are out of scope here.

Always passes on any machine -- no analyzer binary is invoked, no browser
is opened.
"""

import argparse
import os
import subprocess
import sys

import pytest

from fabric_ci_cd_dataops.scripts._report_html import (
    open_report_conflict,
    resolve_open_report,
    resolve_report,
)


def _run_cli(*argv, env=None):
    return subprocess.run(
        [sys.executable, "-m", "fabric_ci_cd_dataops.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
        check=False,
    )


# --------------------------------------------------------------------------- #
# resolve_open_report
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_open_report_defaults_off_when_neither_flag_nor_env_is_set(monkeypatch):
    monkeypatch.delenv("ANALYZER_OPEN_REPORT", raising=False)
    args = argparse.Namespace(file_config={}, open_report=None)

    assert resolve_open_report(args) is False


@pytest.mark.fab_test
def test_open_report_flag_resolves_true():
    args = argparse.Namespace(file_config={}, open_report=True)

    assert resolve_open_report(args) is True


@pytest.mark.fab_test
@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_open_report_env_var_turns_it_on(monkeypatch, value):
    monkeypatch.setenv("ANALYZER_OPEN_REPORT", value)
    args = argparse.Namespace(file_config={}, open_report=None)

    assert resolve_open_report(args) is True


@pytest.mark.fab_test
@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_open_report_env_var_falsey_values_leave_it_off(monkeypatch, value):
    monkeypatch.setenv("ANALYZER_OPEN_REPORT", value)
    args = argparse.Namespace(file_config={}, open_report=None)

    assert resolve_open_report(args) is False


@pytest.mark.fab_test
def test_open_report_cli_flag_beats_env_var(monkeypatch):
    monkeypatch.setenv("ANALYZER_OPEN_REPORT", "0")
    args = argparse.Namespace(file_config={}, open_report=True)

    assert resolve_open_report(args) is True


# --------------------------------------------------------------------------- #
# --open-report auto-enables --report
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_open_report_alone_auto_enables_report(monkeypatch):
    """`--open-report` with no `--report`/`--no-report` still turns reports on."""
    monkeypatch.delenv("ANALYZER_REPORT", raising=False)
    args = argparse.Namespace(file_config={}, report=None, open_report=True)

    assert resolve_report(args) is True


@pytest.mark.fab_test
def test_open_report_env_var_also_auto_enables_report(monkeypatch):
    monkeypatch.delenv("ANALYZER_REPORT", raising=False)
    monkeypatch.setenv("ANALYZER_OPEN_REPORT", "true")
    args = argparse.Namespace(file_config={}, report=None, open_report=None)

    assert resolve_report(args) is True


@pytest.mark.fab_test
def test_neither_flag_leaves_report_off(monkeypatch):
    monkeypatch.delenv("ANALYZER_REPORT", raising=False)
    monkeypatch.delenv("ANALYZER_OPEN_REPORT", raising=False)
    args = argparse.Namespace(file_config={}, report=None, open_report=None)

    assert resolve_report(args) is False


@pytest.mark.fab_test
def test_open_report_and_report_together_is_not_a_conflict(monkeypatch):
    monkeypatch.delenv("ANALYZER_REPORT", raising=False)
    args = argparse.Namespace(file_config={}, report=True, open_report=True)

    assert resolve_report(args) is True
    assert open_report_conflict(args) is None


# --------------------------------------------------------------------------- #
# --no-report --open-report is an explicit, refused conflict
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_no_report_with_open_report_is_a_conflict():
    args = argparse.Namespace(file_config={}, report=False, open_report=True)

    conflict = open_report_conflict(args)

    assert conflict is not None
    assert "--no-report" in conflict
    assert "--open-report" in conflict


@pytest.mark.fab_test
def test_no_conflict_when_open_report_not_requested():
    args = argparse.Namespace(file_config={}, report=False, open_report=None)

    assert open_report_conflict(args) is None


@pytest.mark.fab_test
def test_no_conflict_when_neither_flag_passed():
    args = argparse.Namespace(file_config={}, report=None, open_report=None)

    assert open_report_conflict(args) is None


# --------------------------------------------------------------------------- #
# The real CLI
# --------------------------------------------------------------------------- #


@pytest.fixture
def artifact_tree(tmp_path):
    (tmp_path / "Sales.SemanticModel").mkdir()
    return tmp_path


@pytest.mark.fab_test
def test_open_report_flag_exists_on_an_analyzer_subcommand():
    result = _run_cli("bpa", "--help")

    assert result.returncode == 0, result.stderr
    assert "--open-report" in result.stdout


@pytest.mark.fab_test
def test_no_report_open_report_conflict_refused_through_real_cli(artifact_tree):
    output_dir = artifact_tree / "results"

    result = _run_cli(
        "bpa",
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        str(output_dir),
        "--no-report",
        "--open-report",
        "--dry-run",
    )

    assert result.returncode == 2, result.stdout
    assert "--no-report" in result.stderr
    assert "--open-report" in result.stderr
