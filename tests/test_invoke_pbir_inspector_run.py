"""Contract tests for invoke_pbir_inspector.run_inspector and main.

Scope
-----
End-to-end exit-code and envelope behavior of `run_inspector` (subprocess
mocked) and the `main()` CLI entry point -- split out of
test_invoke_pbir_inspector.py (Analyzer Runtime Readiness epic) once that
file crossed its hard line-count budget. Unit-level tests for parsing,
command-building, and logging stay in the original file; this one covers
the process-outcome contract: exit codes, envelope status, and what reaches
stderr when the tool never runs at all.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [pytest.mark.pbir, pytest.mark.analyzers]


import fab_test.scripts.invoke_pbir_inspector as invoke_pbir_inspector
from fab_test.scripts.invoke_pbir_inspector import main, run_inspector


class TestRunInspector:
    """Tests for run_inspector entry function."""

    def test_missing_artifact_path_exits(self, tmp_path: Path):
        """Missing artifact path exits early."""

        class Args:
            artifact_path = str(tmp_path / "missing")
            rules_path = str(tmp_path / "rules.json")
            inspector_path = str(tmp_path / "PBIRInspectorCLI")
            output_path = str(tmp_path / "out.json")

        with pytest.raises(SystemExit) as exc_info:
            run_inspector(Args())
        assert exc_info.value.code == 1

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_passes_no_findings(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """Tool exits 0 and output file parses as empty findings."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 0
        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["findings"] == []

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_errors_when_process_fails_with_no_findings(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """A non-zero exit with no parseable output (e.g. the .NET runtime is
        missing, so the tool never ran) must not be reported as a pass.

        Regression for the silent false negative: `_classify_inspector_result`
        used to derive status from findings alone, so an empty findings list
        always meant "passed" regardless of the exit code -- a broken
        installation and a clean report were indistinguishable.
        """
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="You must install .NET to run this application.",
        )

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "error"
        assert data["findings"] == []
        assert ".NET" in data["message"] or "exit code 1" in data["message"]

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_stderr_reaches_caller_when_process_fails_with_no_findings(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """The tool's own stderr (naming the missing runtime) must not be
        discarded just because there were no findings to report."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="You must install .NET to run this application.",
        )

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        run_inspector(Args())
        captured = capsys.readouterr()
        assert "You must install .NET to run this application." in captured.err

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_summary_does_not_show_a_checkmark_when_process_failed(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """A run that never produced output must not print a passing ✅ banner
        just because there happened to be no findings to list."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ANALYZER_OUTPUT_MODE", raising=False)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="You must install .NET to run this application.",
        )

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        run_inspector(Args())
        captured = capsys.readouterr()
        assert "✅" not in captured.out

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_fails_with_findings(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """Tool exits 0 but JSON findings present results in failure."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        # The updated wrapper reads findings from the *native* output path.
        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        findings = [{"RuleId": "AvoidBiDi", "LogType": 0, "Pass": False}]
        (native_dir / "native.json").write_text(
            json.dumps({"Results": findings}), encoding="utf-8"
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 1

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_warns_with_warning_findings(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """LogType 1 warning findings warn but do not fail the executable."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        findings = [
            {
                "RuleId": "WARN_01",
                "RuleName": "Missing alt text",
                "LogType": 1,
                "Pass": False,
                "ItemPath": "pages/Page1/visuals/Chart",
                "Message": "Visual lacks alt text",
            }
        ]
        (native_dir / "native.json").write_text(
            json.dumps({"Results": findings}), encoding="utf-8"
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"
        assert len(data["findings"]) == 1

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_fails_with_error_findings(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """LogType 0 error findings fail the build."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        findings = [
            {
                "RuleId": "ERR_01",
                "RuleName": "Invalid binding",
                "LogType": 0,
                "Pass": False,
                "ParentDisplayName": "Page 1",
                "Message": "Field binding is invalid",
            }
        ]
        (native_dir / "native.json").write_text(
            json.dumps({"Results": findings}), encoding="utf-8"
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 1

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_fails_with_mixed_severities(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """Mixed warnings and errors fail on errors."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        findings = [
            {
                "RuleId": "WARN_01",
                "RuleName": "Missing alt text",
                "LogType": 1,
                "Pass": False,
                "ItemPath": "pages/Page1/visuals/Chart",
                "Message": "Visual lacks alt text",
            },
            {
                "RuleId": "ERR_01",
                "RuleName": "Invalid binding",
                "LogType": 0,
                "Pass": False,
                "ItemPath": "pages/Page1/visuals/Table",
                "Message": "Field binding is invalid",
            },
        ]
        (native_dir / "native.json").write_text(
            json.dumps({"Results": findings}), encoding="utf-8"
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 2
        severities = {f["severity"] for f in data["findings"]}
        assert severities == {"error", "warning"}

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_reads_newest_native_json_file(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """When PBIR Inspector writes multiple TestRun_*.json files,
        the newest one is used."""
        import time

        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        native_dir = (
            tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "native.json"
        )
        native_dir.mkdir(parents=True, exist_ok=True)

        old_file = native_dir / (
            "TestRun_11111111111111111111111111111111_111111.json"
        )
        old_file.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(
                {
                    "Results": [
                        {
                            "RuleId": "OLD",
                            "LogType": 0,
                            "Pass": False,
                            "Message": "old",
                        }
                    ]
                }
            ).encode("utf-8")
        )
        time.sleep(0.05)

        new_file = native_dir / (
            "TestRun_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz_999999.json"
        )
        new_file.write_bytes(
            b"\xef\xbb\xbf"
            + json.dumps(
                {
                    "Results": [
                        {
                            "RuleId": "NEW_ERR",
                            "RuleName": "New error",
                            "LogType": 0,
                            "Pass": False,
                            "ParentDisplayName": "Page 1",
                            "Message": "newest error",
                        }
                    ]
                }
            ).encode("utf-8")
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["rule"] == "NEW_ERR"
        assert data["findings"][0]["severity"] == "error"

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_warns_severity_normalized(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """Warning-level PBIR findings carry severity=warning in the envelope."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        findings = [
            {
                "RuleId": "WARN_01",
                "RuleName": "Missing alt text",
                "LogType": 1,
                "Pass": False,
                "ParentDisplayName": "Page 1",
                "Message": "Visual lacks alt text",
            }
        ]
        (native_dir / "native.json").write_text(
            json.dumps({"Results": findings}), encoding="utf-8"
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"
        assert len(data["findings"]) == 1
        assert data["findings"][0]["severity"] == "warning"
        assert data["findings"][0]["object"] == "Page 1"

    def test_print_findings_table_uses_normalized_schema(
        self, capsys
    ):
        """Verbose table prints normalized rule/severity/object/message fields."""
        findings = [
            {
                "rule": "ERR_01",
                "severity": "error",
                "object": "Page 1",
                "message": "Invalid binding",
            },
            {
                "rule": "WARN_01",
                "severity": "warning",
                "object": "Page 2",
                "message": "Missing alt text",
            },
        ]
        invoke_pbir_inspector._print_findings_table(findings)
        captured = capsys.readouterr()
        assert "ERR_01" in captured.out
        assert "WARN_01" in captured.out
        assert "Error" in captured.out
        assert "Warning" in captured.out
        assert "Invalid binding" in captured.out
        assert "Missing alt text" in captured.out

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_timeout(self, mock_run, tmp_path: Path):
        """Timeout is handled gracefully."""
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["PBIRInspectorCLI"], timeout=300
        )

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)

        exit_code = run_inspector(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "timeout"

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_missing_binary(self, mock_run, tmp_path: Path):
        """Missing executable is handled gracefully."""
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

        mock_run.side_effect = FileNotFoundError(2, "No such file")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)

        exit_code = run_inspector(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "error"


class TestMain:
    """Tests for invoke_pbir_inspector.py main entry point."""

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.run_inspector")
    def test_main_accepts_verbose_flag(
        self, mock_run_inspector, tmp_path: Path, monkeypatch
    ):
        """main accepts --v / --verbose and propagates it to run_inspector."""
        artifact = tmp_path / "report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)

        mock_run_inspector.return_value = 0
        monkeypatch.delenv("ANALYZER_VERBOSITY", raising=False)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "invoke_pbir_inspector.py",
                "--artifact-path",
                str(artifact),
                "--rules-path",
                str(rules),
                "--inspector-path",
                str(inspector),
                "--v",
            ],
        )
        result = main()
        assert result == 0
        mock_run_inspector.assert_called_once()
        passed_args = mock_run_inspector.call_args[0][0]
        assert passed_args.verbose is True
        assert os.environ.get("ANALYZER_VERBOSITY") == "verbose"

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.run_inspector")
    def test_main_returns_run_inspector_code(
        self, mock_run_inspector, tmp_path: Path, monkeypatch
    ):
        """main returns the exit code produced by run_inspector."""
        artifact = tmp_path / "report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)

        mock_run_inspector.return_value = 42

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "invoke_pbir_inspector.py",
                "--artifact-path",
                str(artifact),
                "--rules-path",
                str(rules),
                "--inspector-path",
                str(inspector),
            ],
        )
        result = main()
        assert result == 42
        mock_run_inspector.assert_called_once()
        passed_args = mock_run_inspector.call_args[0][0]
        assert passed_args.artifact_path == str(artifact)
        assert passed_args.rules_path == str(rules)
        assert passed_args.inspector_path == str(inspector)
