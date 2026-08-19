"""Unit tests for scripts/invoke_pbir_inspector.py."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [pytest.mark.pbir, pytest.mark.analyzers]


import fabric_ci_cd_dataops.scripts.invoke_pbir_inspector as invoke_pbir_inspector
from fabric_ci_cd_dataops.scripts._analyzer_envelope import ENVELOPE_REQUIRED_KEYS
from fabric_ci_cd_dataops.scripts.invoke_pbir_inspector import (
    build_inspector_command,
    ensure_executable,
    main,
    parse_findings,
    run_inspector,
    write_results,
)


class TestEnsureExecutable:
    """Tests for executable permission helper."""

    @pytest.mark.skipif(
        os.name != "posix", reason="Executable bit is a POSIX concept"
    )
    def test_existing_executable(self, tmp_path: Path):
        """Valid executable file is accepted and permissions remain unchanged."""
        binary = tmp_path / "PBIRInspectorCLI"
        binary.write_text("fake", encoding="utf-8")
        binary.chmod(0o755)
        ensure_executable(binary)  # no exception
        assert binary.stat().st_mode & 0o111

    def test_missing_binary_exits(self, tmp_path: Path):
        """Missing binary exits with error."""
        missing = tmp_path / "PBIRInspectorCLI"
        with pytest.raises(SystemExit) as exc_info:
            ensure_executable(missing)
        assert exc_info.value.code == 1

    @pytest.mark.skipif(
        os.name != "posix", reason="Executable bit is a POSIX concept"
    )
    def test_non_executable_made_executable(self, tmp_path: Path):
        """Non-executable binary is made executable."""
        binary = tmp_path / "PBIRInspectorCLI"
        binary.write_text("fake", encoding="utf-8")
        binary.chmod(0o644)
        ensure_executable(binary)
        assert binary.stat().st_mode & 0o111


class TestBuildInspectorCommand:
    """Tests for command builder."""

    def test_command_structure(self, tmp_path: Path):
        """Command contains expected flags in order."""
        inspector = tmp_path / "PBIRInspectorCLI"
        artifact = tmp_path / "SalesReport.Report"
        rules = tmp_path / "rules.json"
        output = tmp_path / "out.json"
        command = build_inspector_command(inspector, artifact, rules, output)
        assert command[0] == str(inspector)
        assert str(artifact) in command
        assert "-fabricitem" in command
        assert str(rules) in command
        assert "-rules" in command
        assert str(output) in command
        assert "-output" in command
        assert "-formats" in command
        assert "JSON" in command
        assert "-verbose" in command
        assert "true" in command


class TestParseFindings:
    """Tests for output parsing."""

    def test_empty_string_returns_no_findings(self):
        """Empty string yields no findings."""
        assert parse_findings("") == []

    def test_parses_json_list_directly(self):
        """JSON list parsed directly."""
        raw = '[{"rule":"TestRule"}]'
        assert parse_findings(raw) == [{"rule": "TestRule"}]

    def test_parses_dict_with_findings_key(self):
        """Dictionary with findings key parsed."""
        raw = '{"findings":[{"rule":"TestRule"}]}'
        assert parse_findings(raw) == [{"rule": "TestRule"}]

    def test_parses_dict_with_items_key(self):
        """Dictionary with items key parsed."""
        raw = '{"items":[{"rule":"TestRule"}]}'
        assert parse_findings(raw) == [{"rule": "TestRule"}]

    def test_parses_dict_with_results_key(self):
        """Dictionary with results key parsed."""
        raw = '{"results":[{"rule":"TestRule"}]}'
        assert parse_findings(raw) == [{"rule": "TestRule"}]

    def test_parses_dict_with_uppercase_results_key(self):
        """Dictionary with PBIR Inspector 'Results' key parsed."""
        raw = '{"Results":[{"RuleId":"R1","Pass":false,"LogType":1}]}'
        assert parse_findings(raw) == [{"RuleId": "R1", "Pass": False, "LogType": 1}]

    def test_parses_native_pbir_fields_from_list(self):
        """Raw PBIR findings list with native fields is returned unchanged."""
        raw = (
            '[{"RuleId":"R1","Pass":false,"LogType":0,'
            '"ItemPath":"pages/Page1/visuals/Chart","Message":"Invalid binding"}]'
        )
        assert parse_findings(raw) == [
            {
                "RuleId": "R1",
                "Pass": False,
                "LogType": 0,
                "ItemPath": "pages/Page1/visuals/Chart",
                "Message": "Invalid binding",
            }
        ]

    def test_parses_native_pbir_fields_from_uppercase_results(self):
        """PBIR findings wrapped under 'Results' with native fields are extracted."""
        raw = (
            '{"Results":['
            '{"RuleId":"R2","Pass":false,"LogType":1,'
            '"ItemPath":"pages/Page2/visuals/Table","Message":"Missing alt text"}'
            ']}'
        )
        assert parse_findings(raw) == [
            {
                "RuleId": "R2",
                "Pass": False,
                "LogType": 1,
                "ItemPath": "pages/Page2/visuals/Table",
                "Message": "Missing alt text",
            }
        ]

    def test_invalid_json_returns_no_findings(self):
        """Invalid JSON yields no findings."""
        assert parse_findings("not json") == []


class TestLogTypeCoercion:
    """Tests for tolerant LogType parsing in PBIR findings."""

    def test_string_logtype_zero_is_error(self):
        """String-encoded LogType '0' is treated as an error."""
        assert invoke_pbir_inspector._is_error_finding(
            {"RuleId": "R1", "Pass": False, "LogType": "0"}
        )

    def test_string_logtype_one_with_pass_false_is_warning(self):
        """String-encoded LogType '1' with Pass false is a warning."""
        assert invoke_pbir_inspector._is_warning_finding(
            {"RuleId": "R1", "Pass": False, "LogType": "1"}
        )

    def test_string_logtype_one_with_pass_true_is_not_error(self):
        """String-encoded LogType '1' with Pass true is not an error."""
        assert not invoke_pbir_inspector._is_error_finding(
            {"RuleId": "R1", "Pass": True, "LogType": "1"}
        )

    def test_int_logtype_zero_still_is_error(self):
        """Integer LogType 0 continues to be treated as an error."""
        assert invoke_pbir_inspector._is_error_finding(
            {"RuleId": "R1", "Pass": False, "LogType": 0}
        )

    def test_logtype_zero_with_pass_true_is_not_error(self):
        """Passed results with LogType 0 are not violations."""
        assert not invoke_pbir_inspector._is_error_finding(
            {"RuleId": "R1", "Pass": True, "LogType": 0}
        )
        assert not invoke_pbir_inspector._is_warning_finding(
            {"RuleId": "R1", "Pass": True, "LogType": 0}
        )
        assert not invoke_pbir_inspector._is_violation(
            {"RuleId": "R1", "Pass": True, "LogType": 0}
        )


class TestWriteResults:
    """Tests for results writer."""

    def test_results_written(self, tmp_path: Path):
        """Results JSON is written with expected keys."""
        output_path = tmp_path / "results.json"
        artifact_path = tmp_path / "SalesReport.Report"
        rules_path = tmp_path / "rules.json"
        findings = [{"rule": "TestRule"}]
        write_results(
            output_path=output_path,
            status="passed",
            findings=findings,
            artifact_path=artifact_path,
            rules_path=rules_path,
            message="OK",
        )
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["message"] == "OK"
        assert data["analyzer"] == "pbir_inspector"
        assert data["findings"] == findings

    def test_envelope_shape(self, tmp_path: Path):
        """Envelope contains every required key from the shared schema."""
        output_path = tmp_path / "envelope.json"
        write_results(
            output_path=output_path,
            status="passed",
            findings=[],
            artifact_path=tmp_path / "model",
            rules_path=tmp_path / "rules.json",
            message="OK",
        )
        data = json.loads(output_path.read_text(encoding="utf-8"))
        missing = ENVELOPE_REQUIRED_KEYS - data.keys()
        assert not missing, f"Envelope missing keys: {missing}"


class TestVerbosity:
    """Tests for ANALYZER_VERBOSITY handling in run_inspector."""

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
    def test_summary_suppresses_header(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """Given ANALYZER_VERBOSITY=summary, wrapper prints no PBIR header."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "out.json"
        native_dir = tmp_path / "analyzer-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        (native_dir / "native.json").write_text("[]", encoding="utf-8")
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "PBIR Inspector" not in captured.out

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
    def test_debug_includes_command(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """Given ANALYZER_VERBOSITY=debug, wrapper prints the executed command."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "out.json"
        native_dir = tmp_path / "analyzer-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        (native_dir / "native.json").write_text("[]", encoding="utf-8")
        mock_run.return_value = mock.Mock(
            returncode=0, stdout="debug stdout", stderr=""
        )

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = False

        exit_code = run_inspector(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Executing:" in captured.out
        assert "PBIRInspectorCLI" in captured.out
        assert "debug stdout" in captured.out

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
    def test_verbosity_does_not_change_envelope(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """Files on disk are identical regardless of verbosity level."""
        outputs = []
        for level in ("summary", "default", "verbose", "debug"):
            monkeypatch.setenv("ANALYZER_VERBOSITY", level)
            monkeypatch.chdir(tmp_path)
            artifact = tmp_path / f"SalesReport-{level}.Report"
            artifact.mkdir()
            rules = tmp_path / f"rules-{level}.json"
            rules.write_text("[]", encoding="utf-8")
            inspector = tmp_path / f"PBIRInspectorCLI-{level}"
            inspector.write_text("fake", encoding="utf-8")
            inspector.chmod(0o755)
            output = tmp_path / f"out-{level}.json"
            native_dir = (
                tmp_path / "analyzer-results" / "pbir" / f"SalesReport-{level}"
            )
            native_dir.mkdir(parents=True, exist_ok=True)
            (native_dir / "native.json").write_text("[]", encoding="utf-8")
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

            class Args:
                pass

            args = Args()
            args.artifact_path = str(artifact)
            args.rules_path = str(rules)
            args.inspector_path = str(inspector)
            args.output_path = str(output)
            args.emit_html = False
            run_inspector(args)
            outputs.append(json.loads(output.read_text(encoding="utf-8")))

        for key in ("status", "analyzer", "findings"):
            assert all(
                o[key] == outputs[0][key] for o in outputs
            ), f"{key} varied across verbosity levels"


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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
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
        output = tmp_path / "out.json"

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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
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
        output = tmp_path / "out.json"

        # The updated wrapper reads findings from the *native* output path.
        native_dir = tmp_path / "analyzer-results" / "pbir" / "SalesReport"
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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
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
        output = tmp_path / "out.json"

        native_dir = tmp_path / "analyzer-results" / "pbir" / "SalesReport"
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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
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
        output = tmp_path / "out.json"

        native_dir = tmp_path / "analyzer-results" / "pbir" / "SalesReport"
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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
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
        output = tmp_path / "out.json"

        native_dir = tmp_path / "analyzer-results" / "pbir" / "SalesReport"
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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
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
        output = tmp_path / "out.json"

        native_dir = (
            tmp_path / "analyzer-results" / "pbir" / "SalesReport" / "native.json"
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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
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
        output = tmp_path / "out.json"

        native_dir = tmp_path / "analyzer-results" / "pbir" / "SalesReport"
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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_timeout(self, mock_run, tmp_path: Path):
        """Timeout is handled gracefully."""
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "out.json"

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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_missing_binary(self, mock_run, tmp_path: Path):
        """Missing executable is handled gracefully."""
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "out.json"

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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.run_inspector")
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

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_inspector.run_inspector")
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
