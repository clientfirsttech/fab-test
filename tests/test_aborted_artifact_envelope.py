"""An analyzer that aborts before writing an envelope must not inherit an earlier run's.

Playwright, 2026-10-09: with the service principal unset, every artifact
exited 127 before writing anything, yet three showed last run's findings --
`_load_artifact_envelope` read the stale file and `_stamp_mode` rewrote it
with a fresh mtime. The other nine read "failed, 0 errors" in the index
with nothing saying why.
"""

import json
import subprocess
from pathlib import Path

import pytest

from fab_test.scripts import fab_test_execution
from fab_test.scripts._report_html import render_index
from fab_test.scripts.fab_test import _run_analyzer
from fab_test.scripts.fab_test_summary import _index_row_fields
from tests.conftest import _RunAnalyzerArgs

pytestmark = pytest.mark.fab_test

_REASON = "Playwright needs a full service principal to generate an embed token; missing: FABRIC_TENANT_ID."


@pytest.fixture(autouse=True)
def _local_run(monkeypatch):
    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution, "_preflight_error", lambda *a, **k: None)


def _aborting_run(cmd, **_kwargs):
    return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=f"::error::{_REASON}\n")


def _project(tmp_path: Path) -> tuple[Path, Path, Path]:
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Alpha.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "results"
    return artifact_dir, output_dir, output_dir / "bpa" / "Alpha" / "envelope.json"


def test_given_a_stale_envelope_an_aborted_run_should_not_report_its_findings(tmp_path, monkeypatch):
    artifact_dir, output_dir, envelope_path = _project(tmp_path)
    envelope_path.parent.mkdir(parents=True)
    stale = {"status": "failed", "findings": [{"rule": "old", "severity": "Error", "object": "T", "message": "m"}]}
    envelope_path.write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _aborting_run)

    code = _run_analyzer("bpa", _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text"), output_dir)

    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    assert code != 0
    assert envelope["findings"] == []
    assert envelope["message"] == _REASON


def test_given_an_aborted_run_the_index_should_say_why(tmp_path, monkeypatch):
    artifact_dir, output_dir, _ = _project(tmp_path)
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _aborting_run)

    _run_analyzer("bpa", _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text"), output_dir)
    row = {"analyzer": "bpa", "artifact": "Alpha", **_index_row_fields(output_dir, "bpa", "Alpha", 127)}

    assert row["status"] == "failed"
    assert row["detail"] == _REASON
    assert "missing: FABRIC_TENANT_ID" in render_index([row], output_dir)


def test_given_error_findings_the_index_should_not_repeat_the_message(tmp_path):
    output_dir = tmp_path / "results"
    path = output_dir / "bpa" / "Alpha" / "envelope.json"
    path.parent.mkdir(parents=True)
    findings = [{"rule": "R", "severity": "Error", "object": "T", "message": "m"}]
    path.write_text(json.dumps({"status": "failed", "message": "2 cases", "findings": findings}), encoding="utf-8")

    assert _index_row_fields(output_dir, "bpa", "Alpha", 1)["detail"] is None
