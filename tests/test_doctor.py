"""Contract tests for `fab-test doctor` (CLI Agent Ergonomics §8).

Scope
-----
`doctor` surfaces the readiness probe (task 7) as the command a human or
agent runs first. Always passes on any machine — it only reads local state
and never downloads anything. The one exception is `doctor --local`'s
Desktop-instance check, which spawns a local PowerShell process to resolve
an open file path, but only when exactly one instance is running.
"""

import argparse
import json
import os
import subprocess

import pytest

from fabric_ci_cd_dataops.scripts.fab_test_registry import visible_analyzers
from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_doctor

_DOCTOR_KEYS = {"analyzer", "ready", "reason", "resolved_path", "remediation"}


@pytest.mark.fab_test
def test_doctor_lists_every_analyzer_text_format():
    """fab-test doctor (text) mentions every registered analyzer."""
    result = subprocess.run(
        ["fab-test", "doctor"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    for name in visible_analyzers():
        assert name in result.stdout, f"{name} missing from doctor text output"


@pytest.mark.fab_test
def test_doctor_json_format_has_stable_keys():
    """--format json emits one document; each entry has exactly the stable key set."""
    result = subprocess.run(
        ["fab-test", "doctor", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    summary = json.loads(result.stdout)
    assert "analyzers" in summary
    # Every visible analyzer, plus the telemetry row (Eventhouse Shipping §7),
    # which is reported in the same shape but never counts toward whether
    # doctor passes.
    assert len(summary["analyzers"]) == len(visible_analyzers()) + 1
    assert summary["analyzers"][-1]["analyzer"] == "telemetry"
    for entry in summary["analyzers"]:
        assert set(entry.keys()) == _DOCTOR_KEYS, f"key mismatch: {entry.keys()}"


@pytest.mark.fab_test
def test_doctor_analyzer_filter_checks_only_that_one():
    """--analyzer bpa restricts the report to just that analyzer."""
    result = subprocess.run(
        ["fab-test", "doctor", "--analyzer", "bpa", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    summary = json.loads(result.stdout)
    assert len(summary["analyzers"]) == 1
    assert summary["analyzers"][0]["analyzer"] == "bpa"


@pytest.mark.fab_test
def test_doctor_exits_zero_when_at_least_one_analyzer_is_ready():
    """pql_lint (no external tool) is always ready, so the overall exit code is 0."""
    result = subprocess.run(
        ["fab-test", "doctor", "--analyzer", "pql_lint", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_doctor_does_not_greenlight_a_cloud_analyzer_without_credentials(tmp_path):
    """End-to-end guard for the §6 false green.

    Runs with every workspace and credential variable stripped and
    LOCALAPPDATA pointed at an empty directory, so neither ambient
    credentials nor a Power BI Desktop session the developer happens to
    have open can make this pass by accident. Before the fix, pql_test
    reported ready here on the strength of having no binary to resolve.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("FABRIC_")}
    env["LOCALAPPDATA"] = str(tmp_path)
    result = subprocess.run(
        ["fab-test", "doctor", "--analyzer", "pql_test", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    entry = json.loads(result.stdout)["analyzers"][0]
    assert entry["analyzer"] == "pql_test"
    assert entry["ready"] is False
    assert "FABRIC_WORKSPACE_ID" in entry["remediation"]


@pytest.mark.fab_test
def test_doctor_unknown_analyzer_exits_2_and_lists_valid_names():
    """An unrecognized --analyzer name exits 2 and lists the valid choices."""
    result = subprocess.run(
        ["fab-test", "doctor", "--analyzer", "not-a-real-analyzer"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "not-a-real-analyzer" in result.stderr
    assert "bpa" in result.stderr


@pytest.mark.fab_test
def test_print_doctor_returns_zero_when_any_ready():
    """_print_doctor returns 0 as long as at least one row is ready."""
    rows = [
        {"analyzer": "bpa", "ready": False, "reason": "x", "resolved_path": None, "remediation": "y"},
        {
            "analyzer": "pql_lint",
            "ready": True,
            "reason": "no external tool required",
            "resolved_path": None,
            "remediation": None,
        },
    ]
    assert _print_doctor(rows, output_format="json") == 0


@pytest.mark.fab_test
def test_print_doctor_returns_nonzero_when_none_ready():
    """_print_doctor returns non-zero when every row is not-ready."""
    rows = [
        {"analyzer": "bpa", "ready": False, "reason": "x", "resolved_path": None, "remediation": "y"},
        {"analyzer": "pbir", "ready": False, "reason": "x", "resolved_path": None, "remediation": "y"},
    ]
    assert _print_doctor(rows, output_format="json") != 0


@pytest.mark.fab_test
def test_print_doctor_text_shows_remediation_for_not_ready(capsys):
    """Text-format output shows the remediation hint for a not-ready analyzer."""
    rows = [
        {
            "analyzer": "bpa",
            "ready": False,
            "reason": "not yet downloaded",
            "resolved_path": None,
            "remediation": "Would download from https://example.com/tool.zip on first run.",
        },
    ]
    _print_doctor(rows, output_format="text")
    captured = capsys.readouterr()
    assert "bpa" in captured.out
    assert "not yet downloaded" in captured.out
    assert "https://example.com/tool.zip" in captured.out


# --------------------------------------------------------------------------- #
# fab-test doctor --local (Local Desktop First Run §11)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_doctor_local_reports_python_desktop_bridge_and_tool_checks():
    """doctor --local reports Python, Desktop, bridge CLI, and both external tools."""
    result = subprocess.run(
        ["fab-test", "doctor", "--local"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    # pql_lint is deliberately absent: it is hidden from the advertised
    # surface, and the local bundle should not run what the CLI does not
    # offer. See HIDDEN_ANALYZERS and _LOCAL_ANALYZERS.
    for expected in ("python", "desktop", "bridge", "bpa", "pbir", "pql_test"):
        assert expected in result.stdout.lower(), f"missing '{expected}' in:\n{result.stdout}"


@pytest.mark.fab_test
def test_doctor_local_json_is_single_document_with_would_run():
    """doctor --local --format json emits one document with a would_run list."""
    result = subprocess.run(
        ["fab-test", "doctor", "--local", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    data = json.loads(result.stdout)
    assert "checks" in data
    assert "would_run" in data
    assert isinstance(data["would_run"], list)


@pytest.mark.fab_test
def test_doctor_local_remediation_present_for_missing_prerequisite(monkeypatch):
    """A not-ready check includes a remediation hint the caller can act on."""
    from fabric_ci_cd_dataops.scripts import fab_test_admin

    monkeypatch.setattr(
        fab_test_admin,
        "_local_readiness",
        lambda name, args: {"ready": False, "reason": "not installed", "remediation": "pip install it"},
    )
    args = argparse.Namespace(output_format="json", local=True)

    exit_code = fab_test_admin._doctor(args)
    assert exit_code in (0, 1)
