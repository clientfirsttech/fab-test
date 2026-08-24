"""Contract tests for PBIR Inspector's full test-results list (PBIR Report Completeness epic).

Scope
-----
PBIR Inspector's native JSON already records every rule it evaluated --
passed and failed -- as one entry under ``Results``. Historically only
violations made it past ``_is_violation`` into ``findings``, so telemetry
had no way to see what ran when nothing failed. ``test_results`` carries
every row (with a pass/error/warning status, the same vocabulary BPA's
wrapper already uses) without changing what ``findings`` means to the
callers that already read it (exit code, printed table, CI gating).

Always passes on any machine: no PBIR Inspector binary is invoked.
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from fabric_ci_cd_dataops.scripts.invoke_pbir_inspector import run_inspector

pytestmark = pytest.mark.pbir

_MIXED_RESULTS = [
    {
        "RuleId": "PERF_01",
        "LogType": 0,
        "Pass": True,
        "ParentDisplayName": "Page 1",
        "Message": "",
    },
    {
        "RuleId": "MAINT_02",
        "LogType": 0,
        "Pass": False,
        "ParentDisplayName": "Page 2",
        "Message": "Missing alt text",
    },
]

_ALL_PASSED_RESULTS = [
    {
        "RuleId": "PERF_01",
        "LogType": 0,
        "Pass": True,
        "ParentDisplayName": "Page 1",
        "Message": "",
    },
]


def _run(tmp_path: Path, results: list[dict], monkeypatch):
    monkeypatch.chdir(tmp_path)
    artifact = tmp_path / "SalesReport.Report"
    artifact.mkdir()
    rules = tmp_path / "rules.json"
    rules.write_text("[]", encoding="utf-8")
    inspector = tmp_path / "PBIRInspectorCLI"
    inspector.write_text("fake", encoding="utf-8")
    inspector.chmod(0o755)
    output = tmp_path / "envelope.json"

    native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
    native_dir.mkdir(parents=True, exist_ok=True)
    (native_dir / "native.json").write_text(json.dumps({"Results": results}), encoding="utf-8")

    class Args:
        artifact_path = str(artifact)
        rules_path = str(rules)
        inspector_path = str(inspector)
        output_path = str(output)
        emit_html = False

    with mock.patch(
        "fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run"
    ) as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        exit_code = run_inspector(Args())
    return exit_code, json.loads(output.read_text(encoding="utf-8"))


def test_envelope_carries_a_test_results_entry_for_every_rule_evaluated(tmp_path, monkeypatch):
    """Given one passed and one failed rule, should list both, not only the failure."""
    _exit_code, data = _run(tmp_path, _MIXED_RESULTS, monkeypatch)

    assert len(data["findings"]) == 1, "findings stays violations-only for existing consumers"
    assert len(data["test_results"]) == 2, "test_results should include the passed rule too"


def test_a_passing_run_still_lists_every_rule_evaluated(tmp_path, monkeypatch):
    """Given every rule passes, the envelope must not read as if nothing ran."""
    exit_code, data = _run(tmp_path, _ALL_PASSED_RESULTS, monkeypatch)

    assert exit_code == 0
    assert data["findings"] == []
    assert len(data["test_results"]) == 1
    assert data["test_results"][0]["status"] == "pass"


def test_test_results_carry_a_pass_error_status_per_row(tmp_path, monkeypatch):
    _exit_code, data = _run(tmp_path, _MIXED_RESULTS, monkeypatch)

    by_rule = {r["rule"]: r for r in data["test_results"]}
    assert by_rule["PERF_01"]["status"] == "pass"
    assert by_rule["MAINT_02"]["status"] == "error"


def test_a_failed_warning_level_rule_is_a_warning_status(tmp_path, monkeypatch):
    warning_result = [{**_MIXED_RESULTS[1], "LogType": 1}]
    _exit_code, data = _run(tmp_path, warning_result, monkeypatch)

    assert data["test_results"][0]["status"] == "warning"


def test_test_results_use_the_shared_rule_shape(tmp_path, monkeypatch):
    """Rows must line up with `normalize_test_results`'s rule shape (rule/severity/object/message)."""
    _exit_code, data = _run(tmp_path, _MIXED_RESULTS, monkeypatch)

    by_rule = {r["rule"]: r for r in data["test_results"]}
    failed = by_rule["MAINT_02"]
    assert failed["object"] == "Page 2"
    assert failed["message"] == "Missing alt text"
    assert failed["severity"] == "error"


def test_an_older_envelope_shape_is_unaffected_by_test_results(tmp_path, monkeypatch):
    """Adding test_results must not change any existing findings-based field."""
    _exit_code, data = _run(tmp_path, _MIXED_RESULTS, monkeypatch)

    assert data["status"] == "failed"
    assert data["findings"] == [
        {"rule": "MAINT_02", "severity": "error", "object": "Page 2", "message": "Missing alt text"}
    ]
