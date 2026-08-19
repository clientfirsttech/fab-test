"""Unit tests for scripts/invoke_tabular_editor_bpa.py."""

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa as invoke_tabular_editor_bpa
from fabric_ci_cd_dataops.scripts._analyzer_envelope import ENVELOPE_REQUIRED_KEYS
from fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa import (
    _format_bpa_message,
    _parse_vstest_counters,
    build_bpa_command,
    main,
    run_bpa,
    validate_path,
    write_results,
)


class TestValidatePath:
    """Tests for validate_path helper."""

    def test_validate_existing_path(self, tmp_path: Path):
        """Existing path returns resolved Path object."""
        file_path = tmp_path / "model.tmdl"
        file_path.write_text("model", encoding="utf-8")
        result = validate_path(str(file_path), "TMDL path")
        assert result == file_path.resolve()

    def test_validate_missing_path_exits(self, tmp_path: Path):
        """Missing path prints error and exits."""
        missing = tmp_path / "missing.tmdl"
        with pytest.raises(SystemExit) as exc_info:
            validate_path(str(missing), "TMDL path")
        assert exc_info.value.code == 1


class TestBuildBpaCommand:
    """Tests for build_bpa_command."""

    def test_command_structure(self, tmp_path: Path):
        """Command contains expected flags in order."""
        tabular_editor = tmp_path / "TabularEditor.exe"
        tmdl = tmp_path / "model"
        rules = tmp_path / "rules.json"
        output = tmp_path / "out.xml"
        command = build_bpa_command(tabular_editor, tmdl, rules, output)
        assert command[0] == str(tabular_editor)
        assert str(tmdl) in command
        assert "-A" in command
        assert str(rules) in command
        assert "-T" in command
        assert str(output) in command
        assert "-B" not in command
        assert "-O" not in command


class TestWriteResults:
    """Tests for write_results helper."""

    def test_results_written(self, tmp_path: Path):
        """Results JSON is written with expected keys."""
        output_path = tmp_path / "results.json"
        artifact_path = tmp_path / "model"
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
        assert data["analyzer"] == "tabular_editor_bpa"
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
    """Tests for ANALYZER_VERBOSITY handling in run_bpa."""

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_summary_suppresses_per_artifact_output(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """Given ANALYZER_VERBOSITY=summary, wrapper prints no per-artifact header."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        native_out.write_text("[]", encoding="utf-8")
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Tabular Editor BPA" not in captured.out

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_debug_includes_command(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """Given ANALYZER_VERBOSITY=debug, wrapper prints the executed command."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        native_out.write_text("[]", encoding="utf-8")
        mock_run.return_value = mock.Mock(
            returncode=0, stdout="debug stdout", stderr=""
        )

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Executing:" in captured.out
        assert "TabularEditor.exe" in captured.out
        assert "debug stdout" in captured.out

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_verbosity_does_not_change_envelope(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """Files on disk are identical regardless of verbosity level."""
        outputs = []
        for level in ("summary", "default", "verbose", "debug"):
            monkeypatch.setenv("ANALYZER_VERBOSITY", level)
            tmdl = tmp_path / f"SalesModel-{level}.SemanticModel"
            tmdl.mkdir()
            rules = tmp_path / f"rules-{level}.json"
            rules.write_text("[]", encoding="utf-8")
            te = tmp_path / f"TabularEditor-{level}.exe"
            te.write_text("fake", encoding="utf-8")
            output = tmp_path / f"out-{level}.json"
            native_out = tmp_path / f"native-{level}.xml"
            native_out.write_text('[]', encoding="utf-8")
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

            class Args:
                pass

            args = Args()
            args.tmdl_path = str(tmdl)
            args.bpa_rules_path = str(rules)
            args.tabular_editor_path = str(te)
            args.output_path = str(output)
            args.native_output_path = str(native_out)
            run_bpa(args)
            outputs.append(json.loads(output.read_text(encoding="utf-8")))

        for key in ("status", "analyzer", "findings"):
            assert all(
                o[key] == outputs[0][key] for o in outputs
            ), f"{key} varied across verbosity levels"


class TestVstestCounters:
    """Tests for VSTest counter parsing."""

    def test_parse_counters_from_xml(self):
        """Counters are extracted from VSTest XML."""
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">\n'
            '  <ResultSummary outcome="Failed">\n'
            '    <Counters total="72" executed="72" passed="56" failed="16" />\n'
            '  </ResultSummary>\n'
            '</TestRun>'
        )
        counters = _parse_vstest_counters(xml)
        assert counters == {"total": 72, "executed": 72, "passed": 56, "failed": 16}

    def test_parse_counters_missing_returns_none(self):
        """Missing Counters element returns None."""
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">\n'
            '  <ResultSummary outcome="Failed" />\n'
            '</TestRun>'
        )
        assert _parse_vstest_counters(xml) is None

    def test_parse_counters_malformed_returns_none(self):
        """Malformed XML returns None."""
        assert _parse_vstest_counters("not xml") is None


class TestFormatBpaMessage:
    """Tests for BPA message formatting."""

    def test_message_with_counters_and_severity_breakdown(self):
        """Message includes total tests, failures, errors, and warnings."""
        findings = [
            {"Severity": "3", "RuleName": "Bad"},
            {"Severity": "2", "RuleName": "Warn"},
        ]
        counters = {"total": 72, "executed": 72, "passed": 56, "failed": 16}
        message = _format_bpa_message(findings, counters, 1)
        assert "72" in message
        assert "16 failed" in message
        assert "1 error" in message
        assert "1 warning" in message

    def test_message_without_counters(self):
        """Message degrades to finding-based severity summary."""
        findings = [
            {"Severity": "3", "RuleName": "Bad"},
            {"Severity": "2", "RuleName": "Warn"},
        ]
        message = _format_bpa_message(findings, None, 1)
        assert "2 violation(s)" in message
        assert "1 error" in message
        assert "1 warning" in message


class TestRunBpa:
    """Tests for run_bpa entry function."""

    def test_missing_tmdl_path_exits(self, tmp_path: Path):
        """Missing TMDL path exits early."""
        class Args:
            tmdl_path = str(tmp_path / "missing")
            bpa_rules_path = str(tmp_path / "rules.json")
            tabular_editor_path = str(tmp_path / "te.exe")
            output_path = str(tmp_path / "out.json")

        with pytest.raises(SystemExit) as exc_info:
            run_bpa(Args())
        assert exc_info.value.code == 1

    def test_invalid_rules_file_non_array_exits(self, tmp_path: Path):
        """Rules file containing a JSON object (e.g. a model/bim file) instead
        of a JSON array exits with code 1 (regression: was silently passing with
        findings: [])."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        # Simulate BPARules.json accidentally containing a model file.
        rules.write_text(
            '{"name": "SemanticModel", "compatibilityLevel": 1702}',
            encoding="utf-8",
        )
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(tmp_path / "out.json")

        with pytest.raises(SystemExit) as exc_info:
            run_bpa(Args())
        assert exc_info.value.code == 1



    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_run_passes_no_findings(self, mock_run, tmp_path: Path):
        """Tool exits 0 and output file parses as empty findings."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = None

        exit_code = run_bpa(Args())
        assert exit_code == 0
        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["findings"] == []
        # Envelope must contain every required key.
        missing = ENVELOPE_REQUIRED_KEYS - data.keys()
        assert not missing, f"Envelope missing keys: {missing}"
    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_run_fails_with_findings(self, mock_run, tmp_path: Path):
        """Tool exits 0 but JSON findings with severity 3 result in failure."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        # findings written to the *native* path that run_bpa reads back
        native_out = tmp_path / "native.xml"
        findings = [{"rule": "AvoidBiDi", "Severity": "3"}]
        native_out.write_text(json.dumps(findings), encoding="utf-8")

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 1

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_run_warns_with_vstest_xml(self, mock_run, tmp_path: Path):
        """VSTest XML output from TE2 -T flag is parsed into per-object findings.
        Severities <= 2 warn but do not fail the executable."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        # Real VSTest XML as produced by TE2 -T flag
        native_out.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<TestRun id="abc" name="model" runUser="user"'
            ' xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">\n'
            '  <ResultSummary outcome="Failed">\n'
            '    <Counters total="2" executed="2" passed="1" failed="1" />\n'
            '  </ResultSummary>\n'
            '  <TestDefinitions>\n'
            '    <UnitTest name="Avoid bi-directional relationships" id="2">\n'
            '      <Properties>\n'
            '        <Property><Key>RuleID</Key><Value>PERF_01</Value></Property>\n'
            '        <Property><Key>Severity</Key><Value>2</Value></Property>\n'
            '        <Property><Key>Category</Key><Value>Performance</Value>'
            '</Property>\n'
            '      </Properties>\n'
            '    </UnitTest>\n'
            '    <UnitTest name="Add descriptions to measures" id="4">\n'
            '      <Properties>\n'
            '        <Property><Key>RuleID</Key><Value>MAINT_02</Value></Property>\n'
            '        <Property><Key>Severity</Key><Value>1</Value></Property>\n'
            '        <Property><Key>Category</Key><Value>Maintenance</Value>'
            '</Property>\n'
            '      </Properties>\n'
            '    </UnitTest>\n'
            '  </TestDefinitions>\n'
            '  <Results>\n'
            '    <UnitTestResult testId="2" testName="Avoid bi-directional relationships"'
            ' outcome="Passed"><Output /></UnitTestResult>\n'
            '    <UnitTestResult testId="4" testName="Add descriptions to measures"'
            ' outcome="Failed">\n'
            '      <Output><ErrorInfo>\n'
            '        <Message>2 object(s) in violation of rule</Message>\n'
            '        <StackTrace>Objects in violation:\n'
            '  [Total Sales] (Measure)\n'
            '  [Profit Margin] (Measure)</StackTrace>\n'
            '      </ErrorInfo></Output>\n'
            '    </UnitTestResult>\n'
            '  </Results>\n'
            '</TestRun>',
            encoding="utf-8",
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"
        # 2 objects violated the rule → 2 findings
        assert len(data["findings"]) == 2
        assert data["findings"][0]["RuleID"] == "MAINT_02"
        assert data["findings"][0]["RuleName"] == "Add descriptions to measures"
        assert data["findings"][0]["Severity"] == "1"
        assert "[Total Sales]" in data["findings"][0]["ObjectName"]
        assert "[Profit Margin]" in data["findings"][1]["ObjectName"]
        assert data["findings"][0]["Category"] == "Maintenance"

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_severity_3_fails_build(self, mock_run, tmp_path: Path):
        """Severity 3 findings fail the build (exit 1, status failed)."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        native_out.write_text(
            json.dumps([{"RuleName": "Bad", "RuleID": "PERF_01", "Severity": "3"}]),
            encoding="utf-8",
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_severity_2_warns_but_passes(self, mock_run, tmp_path: Path):
        """Severity 2 findings warn but do not fail the executable (exit 0)."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        native_out.write_text(
            json.dumps([{"RuleName": "Warn", "RuleID": "MAINT_01", "Severity": "2"}]),
            encoding="utf-8",
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_mixed_severities_fails_on_max(self, mock_run, tmp_path: Path):
        """Mixed severities fail if any finding is severity 3 or higher."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        native_out.write_text(
            json.dumps([
                {"RuleName": "Warn", "RuleID": "MAINT_01", "Severity": "2"},
                {"RuleName": "Bad", "RuleID": "PERF_01", "Severity": "3"},
            ]),
            encoding="utf-8",
        )

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_run_warns_with_low_severity_findings(self, mock_run, tmp_path: Path):
        """Findings with severity <= 2 produce warning status and exit 0."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        findings = [{"rule": "AddDescription", "Severity": "2"}]
        native_out.write_text(json.dumps(findings), encoding="utf-8")

        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"
        assert len(data["findings"]) == 1

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_run_fails_via_exit_code_fallback(self, mock_run, tmp_path: Path):
        """When TE2 exits non-zero and writes no native output file, findings
        are synthesized from the exit code. Unknown severity is treated as error
        by default."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"

        # TE2 exits 3 (3 violations) but does NOT write native output file.
        mock_run.return_value = mock.Mock(returncode=3, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = None

        exit_code = run_bpa(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) > 0, (
            "findings must be populated via exit-code fallback (not [])"
        )
        assert data["findings"][0]["RuleName"] == "BPA violation"
        assert data["findings"][0]["count"] == 3

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_run_timeout(self, mock_run, tmp_path: Path):
        """Timeout is handled gracefully."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["te"], timeout=300)

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = None

        exit_code = run_bpa(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "timeout"

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_run_missing_executable(self, mock_run, tmp_path: Path):
        """Missing executable is handled gracefully."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.side_effect = FileNotFoundError(2, "No such file")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = None

        exit_code = run_bpa(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "error"


class TestPrintFindingsTable:
    """Tests for the BPA findings table formatter."""

    def test_table_includes_severity_rule_id_name_object_category(self, capsys):
        """Verbose table displays severity, rule ID, name, object, and category."""
        findings = [
            {
                "RuleID": "PERF_01",
                "RuleName": "Avoid bi-directional relationships",
                "ObjectName": "[Sales]",
                "Severity": "3",
                "Category": "Performance",
            }
        ]
        invoke_tabular_editor_bpa._print_findings_table(findings)
        captured = capsys.readouterr()
        out = captured.out
        assert "PERF_01" in out
        assert "Avoid bi-directional" in out
        assert "[Sales]" in out
        assert "3" in out
        assert "Performance" in out


class TestSeverityThreshold:
    """Tests for the BPA error severity threshold constant."""

    def test_error_severity_threshold_value(self):
        """The module exposes a threshold of 3 for error-level findings."""
        assert invoke_tabular_editor_bpa.BPA_ERROR_SEVERITY_THRESHOLD == 3

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_threshold_severity_fails_build(self, mock_run, tmp_path: Path):
        """Severity equal to the threshold fails the build."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        native_out.write_text(
            json.dumps(
                [
                    {
                        "RuleName": "Bad",
                        "RuleID": "PERF_01",
                        "Severity": str(
                            invoke_tabular_editor_bpa.BPA_ERROR_SEVERITY_THRESHOLD
                        ),
                    }
                ]
            ),
            encoding="utf-8",
        )
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa.subprocess.run")
    def test_below_threshold_severity_warns(self, mock_run, tmp_path: Path):
        """Severity one below the threshold warns but does not fail."""
        tmdl = tmp_path / "SalesModel.SemanticModel"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "TabularEditor.exe"
        te.write_text("fake", encoding="utf-8")
        output = tmp_path / "out.json"
        native_out = tmp_path / "native.xml"
        native_out.write_text(
            json.dumps(
                [
                    {
                        "RuleName": "Warn",
                        "RuleID": "MAINT_01",
                        "Severity": str(
                            invoke_tabular_editor_bpa.BPA_ERROR_SEVERITY_THRESHOLD - 1
                        ),
                    }
                ]
            ),
            encoding="utf-8",
        )
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            tmdl_path = str(tmdl)
            bpa_rules_path = str(rules)
            tabular_editor_path = str(te)
            output_path = str(output)
            native_output_path = str(native_out)

        exit_code = run_bpa(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"


class TestMain:
    """Tests for invoke_tabular_editor_bpa.py main entry point."""

    def test_main_returns_run_bpa_code(self, tmp_path: Path, monkeypatch):
        """main returns the exit code produced by run_bpa."""
        tmdl = tmp_path / "model"
        tmdl.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        te = tmp_path / "te.exe"
        te.write_text("fake", encoding="utf-8")

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "invoke_tabular_editor_bpa.py",
                "--tmdl-path",
                str(tmdl),
                "--bpa-rules-path",
                str(rules),
                "--tabular-editor-path",
                str(te),
            ],
        )
        # main() calls run_bpa via LOAD_GLOBAL in the module's namespace.
        # Replacing the module-level binding in sys.modules is the most
        # reliable way to intercept that call during testing.
        module = sys.modules["fabric_ci_cd_dataops.scripts.invoke_tabular_editor_bpa"]
        original_run_bpa = module.run_bpa
        module.run_bpa = lambda args: 42
        try:
            result = main()
            assert result == 42
        finally:
            module.run_bpa = original_run_bpa
