"""Unit tests for scripts/invoke_rdl_lint.py -- the CLI wrapper around _rdl_lint.py."""

import json
import sys
from pathlib import Path

import pytest

from fab_test.scripts._rdl_lint import CHECKS
from fab_test.scripts.invoke_rdl_lint import main, run_rdl_lint, validate_path

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">
  <Body><ReportItems><Tablix Name="Tablix1" /></ReportItems></Body>
</Report>
"""

_CATALOG = {
    "rules": [
        {
            "id": "DS-02",
            "name": "No unused datasets",
            "description": "No unused datasets",
            "severity": "error",
            "disabled": False,
        }
    ]
}


class _Args:
    def __init__(self, artifact, rules_path, output_path, verbose=False):
        self.artifact_path = str(artifact)
        self.rules_path = str(rules_path)
        self.output_path = str(output_path)
        self.verbose = verbose


def _write_fixture(tmp_path):
    artifact = tmp_path / "Sales.rdl"
    artifact.write_text(_RDL, encoding="utf-8")
    rules_path = tmp_path / "rdl-rules.json"
    rules_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    output = tmp_path / "out.json"
    return artifact, rules_path, output


class TestValidatePath:
    def test_missing_path_exits_1(self, tmp_path: Path):
        with pytest.raises(SystemExit) as exc_info:
            validate_path(str(tmp_path / "missing.rdl"), "RDL artifact path")
        assert exc_info.value.code == 1


class TestRunRdlLint:
    def test_passes_with_no_findings_when_no_check_is_registered(self, tmp_path: Path):
        artifact, rules_path, output = _write_fixture(tmp_path)

        exit_code = run_rdl_lint(_Args(artifact, rules_path, output))

        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["findings"] == []
        assert data["analyzer"] == "rdl"

    def test_the_results_folder_and_analyzer_name_are_both_rdl(self, tmp_path: Path):
        """The registry key, the envelope's analyzer field, and the results
        folder should all read "rdl" -- one name everywhere (unlike
        pbir_a11y/a11y), so telemetry, annotations, and reports agree."""
        artifact, rules_path, output = _write_fixture(tmp_path)

        run_rdl_lint(_Args(artifact, rules_path, output))

        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["analyzer"] == "rdl"

    def test_test_results_covers_every_catalog_rule_as_skip_when_unimplemented(self, tmp_path: Path):
        artifact, rules_path, output = _write_fixture(tmp_path)

        run_rdl_lint(_Args(artifact, rules_path, output))

        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["test_results"] == [{
            "rule": "DS-02", "severity": "error", "object": "",
            "message": "No unused datasets", "status": "skip",
        }]

    def test_a_registered_check_that_fires_fails_the_run(self, tmp_path: Path):
        artifact, rules_path, output = _write_fixture(tmp_path)
        CHECKS["DS-02"] = lambda _root: [{"object": "Sales", "message": "unused dataset"}]
        try:
            exit_code = run_rdl_lint(_Args(artifact, rules_path, output))
        finally:
            del CHECKS["DS-02"]

        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert data["findings"] == [
            {"object": "Sales", "message": "unused dataset", "rule": "DS-02", "severity": "error"}
        ]

    def test_a_warning_only_run_passes_the_exit_code_but_not_silently(self, tmp_path: Path):
        artifact, rules_path, output = _write_fixture(tmp_path)
        rules_path.write_text(
            json.dumps({"rules": [{"id": "QRY-07", "name": "n", "severity": "warning", "disabled": False}]}),
            encoding="utf-8",
        )
        CHECKS["QRY-07"] = lambda _root: [{"object": "Sales", "message": "long query"}]
        try:
            exit_code = run_rdl_lint(_Args(artifact, rules_path, output))
        finally:
            del CHECKS["QRY-07"]

        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"

    def test_a_malformed_rdl_reports_one_error_finding_rather_than_raising(self, tmp_path: Path):
        artifact = tmp_path / "Broken.rdl"
        artifact.write_text("<Report><Unclosed>", encoding="utf-8")
        rules_path = tmp_path / "rdl-rules.json"
        rules_path.write_text(json.dumps(_CATALOG), encoding="utf-8")
        output = tmp_path / "out.json"

        exit_code = run_rdl_lint(_Args(artifact, rules_path, output))

        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "error"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["severity"] == "error"
        assert "not well-formed" in data["findings"][0]["message"]

    def test_writes_a_report_when_enabled_even_with_zero_findings(self, tmp_path: Path, monkeypatch):
        """`--report` (ANALYZER_REPORT) writes report.html beside the envelope,
        including a clean run -- an analyzer that passed must still appear in
        the report/index, not be silently omitted."""
        monkeypatch.setenv("ANALYZER_REPORT", "1")
        artifact, rules_path, output = _write_fixture(tmp_path)

        run_rdl_lint(_Args(artifact, rules_path, output))

        report = output.parent / "report.html"
        assert report.exists()
        assert "Sales" in report.read_text(encoding="utf-8")


class TestMain:
    def test_main_invokes_runner(self, tmp_path: Path, monkeypatch):
        artifact, rules_path, output = _write_fixture(tmp_path)
        monkeypatch.setattr(
            sys, "argv",
            [
                "invoke_rdl_lint.py",
                "--artifact-path", str(artifact),
                "--rules-path", str(rules_path),
                "--output-path", str(output),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
