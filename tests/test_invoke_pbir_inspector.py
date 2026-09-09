"""Unit tests for scripts/invoke_pbir_inspector.py."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [pytest.mark.pbir, pytest.mark.analyzers]


import fab_test.scripts.invoke_pbir_inspector as invoke_pbir_inspector
from fab_test.scripts._analyzer_envelope import ENVELOPE_REQUIRED_KEYS, WrapperResult
from fab_test.scripts.invoke_pbir_inspector import (
    build_inspector_command,
    ensure_executable,
    log,
    parse_findings,
    run_inspector,
    write_results,
)


class TestLog:
    """Tests for log(), the wrapper's human-banner choke point."""

    def test_log_routes_to_stdout_when_output_mode_absent(self, monkeypatch, capsys):
        """Direct invocation (no ANALYZER_OUTPUT_MODE) is unchanged: stdout."""
        monkeypatch.delenv("ANALYZER_OUTPUT_MODE", raising=False)
        log("hello")
        captured = capsys.readouterr()
        assert captured.out == "hello\n"
        assert captured.err == ""

    def test_log_routes_to_stderr_when_output_mode_json(self, monkeypatch, capsys):
        """fab-test sets ANALYZER_OUTPUT_MODE=json under --format json."""
        monkeypatch.setenv("ANALYZER_OUTPUT_MODE", "json")
        log("hello")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "hello\n"


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
            WrapperResult(output_path, "passed", findings, artifact_path, message="OK"),
            rules_path,
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
            WrapperResult(output_path, "passed", [], tmp_path / "model", message="OK"),
            tmp_path / "rules.json",
        )
        data = json.loads(output_path.read_text(encoding="utf-8"))
        missing = ENVELOPE_REQUIRED_KEYS - data.keys()
        assert not missing, f"Envelope missing keys: {missing}"


class TestVerbosity:
    """Tests for ANALYZER_VERBOSITY handling in run_inspector."""

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
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
        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
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

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
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
        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
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

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
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
                tmp_path / "fab-test-results" / "pbir" / f"SalesReport-{level}"
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


class TestLocateNativeHtml:
    """Tests for `_locate_native_html`'s pick among a reused native-output folder.

    ``native_out`` is the same directory across runs of the same artifact,
    so a stale HTML report (e.g. left over from a run before a bug fix, or
    from a previous invocation) can sit alongside the fresh one. Picking
    the wrong one is exactly what caused `fab-test all --open-report`'s
    broken images while a standalone `fab-test pbir --open-report` (a
    clean, single-HTML folder) was unaffected.
    """

    def test_picks_the_newest_html_not_the_first_glob_match(self, tmp_path: Path):
        native_out = tmp_path / "native.json"
        native_out.mkdir()
        stale = native_out / "aaa-stale.html"
        fresh = native_out / "zzz-fresh.html"
        stale.write_text("<html>stale</html>", encoding="utf-8")
        fresh.write_text("<html>fresh</html>", encoding="utf-8")
        # Force filesystem mtimes to disagree with alphabetical glob order,
        # so a naive `glob("*.html")[0]` would return the stale file.
        stale_time = 1_000_000
        fresh_time = 2_000_000
        os.utime(stale, (stale_time, stale_time))
        os.utime(fresh, (fresh_time, fresh_time))

        result = invoke_pbir_inspector._locate_native_html(
            native_out, emit_html=True, inspector_path=tmp_path / "PBIRInspectorCLI"
        )

        assert result == fresh

    def test_returns_none_when_emit_html_is_false(self, tmp_path: Path):
        native_out = tmp_path / "native.json"
        native_out.mkdir()
        (native_out / "TestRun.html").write_text("<html></html>", encoding="utf-8")

        result = invoke_pbir_inspector._locate_native_html(
            native_out, emit_html=False, inspector_path=tmp_path / "PBIRInspectorCLI"
        )

        assert result is None

    def test_returns_none_when_no_html_files_exist(self, tmp_path: Path):
        native_out = tmp_path / "native.json"
        native_out.mkdir()

        result = invoke_pbir_inspector._locate_native_html(
            native_out, emit_html=True, inspector_path=tmp_path / "PBIRInspectorCLI"
        )

        assert result is None


class TestClearStaleScreenshotFolder:
    """PBIR Screenshot Correlation epic: FabInspCLI does not regenerate
    ``PBIInspectorPNG`` on a second run against an already-populated
    ``native_out``, while it does randomize every finding's ``Id`` each
    run -- confirmed live (22/22 matched on a clean run, 0/22 after a
    second run left the old folder in place). The wrapper must clear that
    folder itself before invoking the inspector binary so FabInspCLI is
    always forced to write a fresh set that matches the run it belongs to.
    """

    def test_removes_an_existing_folder_and_its_contents(self, tmp_path: Path):
        native_out = tmp_path / "native.json"
        folder = native_out / "PBIInspectorPNG"
        folder.mkdir(parents=True)
        (folder / "stale-id.png").write_bytes(b"stale")

        invoke_pbir_inspector._clear_stale_screenshot_folder(native_out)

        assert not folder.exists()

    def test_missing_folder_does_not_raise(self, tmp_path: Path):
        native_out = tmp_path / "native.json"
        native_out.mkdir()

        invoke_pbir_inspector._clear_stale_screenshot_folder(native_out)  # no exception

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_inspector_clears_a_stale_screenshot_folder_before_invoking(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """A stale ``PBIInspectorPNG`` left from a prior run must not survive
        into the next invocation -- the mocked subprocess writes nothing back,
        so the folder's absence afterward proves it was cleared beforehand."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "out.json"
        # FabInspCLI treats the "-output" path as a directory when emitting
        # HTML too, e.g. .../SalesReport/native.json/PBIInspectorPNG/*.png --
        # matching the real on-disk layout this fix targets.
        native_out_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "native.json"
        stale_folder = native_out_dir / "PBIInspectorPNG"
        stale_folder.mkdir(parents=True, exist_ok=True)
        (stale_folder / "stale-id.png").write_bytes(b"stale")
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = True

        run_inspector(Args())

        assert not stale_folder.exists()

    @mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run")
    def test_run_inspector_leaves_no_folder_untouched_when_none_existed(
        self, mock_run, tmp_path: Path, monkeypatch
    ):
        """First-ever run against a fresh native_out: nothing to clear, no error."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "SalesReport.Report"
        artifact.mkdir()
        rules = tmp_path / "rules.json"
        rules.write_text("[]", encoding="utf-8")
        inspector = tmp_path / "PBIRInspectorCLI"
        inspector.write_text("fake", encoding="utf-8")
        inspector.chmod(0o755)
        output = tmp_path / "out.json"
        native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
        native_dir.mkdir(parents=True, exist_ok=True)
        (native_dir / "native.json").write_text("[]", encoding="utf-8")
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        class Args:
            artifact_path = str(artifact)
            rules_path = str(rules)
            inspector_path = str(inspector)
            output_path = str(output)
            emit_html = True

        exit_code = run_inspector(Args())

        assert exit_code == 0

