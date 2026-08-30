"""Unit tests for scripts/invoke_pbir_a11y.py."""

import json
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [pytest.mark.a11y, pytest.mark.analyzers]

import fabric_ci_cd_dataops.scripts.invoke_pbir_a11y as invoke_pbir_a11y
from fabric_ci_cd_dataops.scripts._analyzer_envelope import ENVELOPE_REQUIRED_KEYS
from fabric_ci_cd_dataops.scripts.invoke_pbir_a11y import (
    _classify_a11y_result,
    _map_a11y_severity,
    build_a11y_command,
    extract_findings,
    log,
    main,
    parse_a11y_json,
    run_a11y,
    validate_path,
)


class TestLog:
    def test_log_routes_to_stdout_when_output_mode_absent(self, monkeypatch, capsys):
        monkeypatch.delenv("ANALYZER_OUTPUT_MODE", raising=False)
        log("hello")
        captured = capsys.readouterr()
        assert captured.out == "hello\n"
        assert captured.err == ""

    def test_log_routes_to_stderr_when_output_mode_json(self, monkeypatch, capsys):
        monkeypatch.setenv("ANALYZER_OUTPUT_MODE", "json")
        log("hello")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "hello\n"


class TestValidatePath:
    def test_missing_path_exits(self, tmp_path: Path):
        with pytest.raises(SystemExit) as exc_info:
            validate_path(str(tmp_path / "missing"), "thing")
        assert exc_info.value.code == 1

    def test_existing_path_resolved(self, tmp_path: Path):
        existing = tmp_path / "x"
        existing.mkdir()
        assert validate_path(str(existing), "thing") == existing.resolve()


class TestBuildA11yCommand:
    def test_command_structure(self, tmp_path: Path):
        a11y_path = tmp_path / "dist" / "cli.js"
        artifact = tmp_path / "SalesReport.Report"
        command = build_a11y_command("node", a11y_path, artifact, "fail")
        assert command == ["node", str(a11y_path), "check", str(artifact), "--json", "--fail-on", "fail"]

    def test_fail_on_is_forwarded_verbatim(self, tmp_path: Path):
        """A caller's --fail-on reaches pbir-a11y unchanged -- no fab-test-specific severity concept."""
        command = build_a11y_command("node", tmp_path / "cli.js", tmp_path / "R.Report", "warn")
        assert command[-1] == "warn"


class TestMapA11ySeverity:
    @pytest.mark.parametrize(
        "raw,expected",
        [("fail", "error"), ("warn", "warning"), ("info", "info"), ("pass", "info"), (None, "warning"), ("", "warning")],
    )
    def test_mapping(self, raw, expected):
        assert _map_a11y_severity(raw) == expected


_SAMPLE_RESULT = {
    "fileName": "R.Report",
    "pages": [
        {
            "page": {"id": "p1", "displayName": "Page 1", "hidden": False},
            "issues": [
                {
                    "id": "p1-title-missing",
                    "category": "pageTitles",
                    "severity": "warn",
                    "title": "No visible page title",
                    "detail": "Page has no title visual.",
                }
            ],
            "visuals": [
                {
                    "visual": {"id": "v1", "displayName": "Sales Card", "type": "cardVisual"},
                    "issues": [
                        {
                            "id": "v1-alt-missing",
                            "category": "altText",
                            "severity": "fail",
                            "title": "Missing alt text",
                            "detail": "Card has no alt text.",
                        }
                    ],
                }
            ],
        }
    ],
}


class TestParseA11yJson:
    def test_parses_valid_json(self):
        raw = json.dumps(_SAMPLE_RESULT)
        assert parse_a11y_json(raw)["fileName"] == "R.Report"

    def test_empty_stdout_returns_none(self):
        assert parse_a11y_json("") is None
        assert parse_a11y_json("   ") is None

    def test_invalid_json_returns_none(self):
        assert parse_a11y_json("not json") is None


class TestExtractFindings:
    def test_flattens_page_and_visual_issues(self):
        findings = extract_findings(_SAMPLE_RESULT)
        assert len(findings) == 2

        page_finding = next(f for f in findings if f["rule"] == "p1-title-missing")
        assert page_finding["severity"] == "warning"
        assert page_finding["object"] == "Page 1"
        assert page_finding["category"] == "pageTitles"
        assert page_finding["page"] == "Page 1"
        assert page_finding["visual"] is None
        assert "[pageTitles]" in page_finding["message"]

        visual_finding = next(f for f in findings if f["rule"] == "v1-alt-missing")
        assert visual_finding["severity"] == "error"
        assert visual_finding["object"] == "Page 1 / Sales Card"
        assert visual_finding["visual"] == "Sales Card"

    def test_no_pages_yields_no_findings(self):
        assert extract_findings({"pages": []}) == []
        assert extract_findings({}) == []


class TestClassifyA11yResult:
    def test_no_findings_is_passed(self):
        outcome = _classify_a11y_result(0, [])
        assert outcome["status"] == "passed"
        assert outcome["has_errors"] is False

    def test_returncode_1_with_findings_is_failed(self):
        findings = [{"severity": "error"}]
        outcome = _classify_a11y_result(1, findings)
        assert outcome["status"] == "failed"
        assert outcome["has_errors"] is True

    def test_returncode_0_with_findings_is_warning_not_failure(self):
        """Findings below --fail-on's threshold don't fail the tool's own exit code;
        the envelope should agree, not force an error status the tool didn't report."""
        findings = [{"severity": "warning"}]
        outcome = _classify_a11y_result(0, findings)
        assert outcome["status"] == "warning"
        assert outcome["has_errors"] is False

    def test_returncode_2_is_a_tool_error_distinct_from_a_violation(self):
        """A bad/unreadable path (tool error) must not read as a rule violation,
        in either the envelope status or (via run_a11y) the process exit code."""
        outcome = _classify_a11y_result(2, [])
        assert outcome["status"] == "error"
        assert outcome["has_errors"] is True


class TestRunA11y:
    def test_missing_artifact_path_exits(self, tmp_path: Path):
        class Args:
            artifact_path = str(tmp_path / "missing")
            a11y_path = str(tmp_path / "cli.js")
            output_path = str(tmp_path / "out.json")
            fail_on = None

        with pytest.raises(SystemExit) as exc_info:
            run_a11y(Args())
        assert exc_info.value.code == 1

    def test_missing_a11y_path_exits(self, tmp_path: Path):
        artifact = tmp_path / "R.Report"
        artifact.mkdir()

        class Args:
            artifact_path = str(artifact)
            a11y_path = str(tmp_path / "missing-cli.js")
            output_path = str(tmp_path / "out.json")
            fail_on = None

        with pytest.raises(SystemExit) as exc_info:
            run_a11y(Args())
        assert exc_info.value.code == 1

    def test_node_not_found_writes_error_envelope(self, tmp_path: Path, monkeypatch):
        artifact = tmp_path / "R.Report"
        artifact.mkdir()
        tool_path = tmp_path / "cli.js"
        tool_path.write_text("//", encoding="utf-8")
        output = tmp_path / "out.json"

        monkeypatch.setattr(invoke_pbir_a11y.shutil, "which", lambda _name: None)

        class Args:
            artifact_path = str(artifact)
            a11y_path = str(tool_path)
            output_path = str(output)
            fail_on = None

        exit_code = run_a11y(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "error"
        assert "node" in data["message"].lower()

    def _args(self, artifact, tool_path, output, fail_on=None):
        class Args:
            artifact_path = str(artifact)
            a11y_path = str(tool_path)
            output_path = str(output)

        Args.fail_on = fail_on
        return Args()

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.shutil.which", return_value="node")
    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.subprocess.run")
    def test_run_passes_with_no_findings(self, mock_run, _mock_which, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "R.Report"
        artifact.mkdir()
        a11y_path = tmp_path / "cli.js"
        a11y_path.write_text("//", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"pages": []}), stderr="")

        exit_code = run_a11y(self._args(artifact, a11y_path, output))
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["findings"] == []
        assert set(ENVELOPE_REQUIRED_KEYS) <= set(data.keys())

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.shutil.which", return_value="node")
    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.subprocess.run")
    def test_run_fails_with_error_findings(self, mock_run, _mock_which, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "R.Report"
        artifact.mkdir()
        a11y_path = tmp_path / "cli.js"
        a11y_path.write_text("//", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.return_value = mock.Mock(returncode=1, stdout=json.dumps(_SAMPLE_RESULT), stderr="")

        exit_code = run_a11y(self._args(artifact, a11y_path, output))
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 2

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.shutil.which", return_value="node")
    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.subprocess.run")
    def test_run_reports_tool_error_distinctly_from_findings(self, mock_run, _mock_which, tmp_path: Path, monkeypatch):
        """Exit code 2 (bad/unreadable path) is a tool error, never a rule violation."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "R.Report"
        artifact.mkdir()
        a11y_path = tmp_path / "cli.js"
        a11y_path.write_text("//", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.return_value = mock.Mock(returncode=2, stdout="", stderr="fatal: bad path")

        exit_code = run_a11y(self._args(artifact, a11y_path, output))
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "error"
        assert data["findings"] == []

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.shutil.which", return_value="node")
    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.subprocess.run")
    def test_run_forwards_fail_on_to_the_command(self, mock_run, _mock_which, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "R.Report"
        artifact.mkdir()
        a11y_path = tmp_path / "cli.js"
        a11y_path.write_text("//", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"pages": []}), stderr="")

        run_a11y(self._args(artifact, a11y_path, output, fail_on="warn"))
        called_command = mock_run.call_args[0][0]
        assert called_command[-2:] == ["--fail-on", "warn"]

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.shutil.which", return_value="node")
    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.subprocess.run")
    def test_run_uses_utf8_explicitly_for_subprocess_decoding(self, mock_run, _mock_which, tmp_path: Path, monkeypatch):
        """Node writes UTF-8 regardless of platform; a locale-default decode
        corrupts non-ASCII output (discovered live: 'Card · fields' via
        the default Windows console codepage)."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "R.Report"
        artifact.mkdir()
        a11y_path = tmp_path / "cli.js"
        a11y_path.write_text("//", encoding="utf-8")
        output = tmp_path / "out.json"

        mock_run.return_value = mock.Mock(returncode=0, stdout=json.dumps({"pages": []}), stderr="")

        run_a11y(self._args(artifact, a11y_path, output))
        assert mock_run.call_args.kwargs["encoding"] == "utf-8"

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.shutil.which", return_value="node")
    @mock.patch(
        "fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_run_handles_a_run_time_missing_node(self, _mock_run, _mock_which, tmp_path: Path, monkeypatch):
        """A cached tool resolves fine at doctor-probe time, but the machine
        actually running the check may still lack node -- must not traceback."""
        monkeypatch.chdir(tmp_path)
        artifact = tmp_path / "R.Report"
        artifact.mkdir()
        a11y_path = tmp_path / "cli.js"
        a11y_path.write_text("//", encoding="utf-8")
        output = tmp_path / "out.json"

        exit_code = run_a11y(self._args(artifact, a11y_path, output))
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "error"


class TestMain:
    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.run_a11y", return_value=0)
    def test_main_accepts_verbose_flag(self, mock_run_a11y, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["invoke_pbir_a11y.py", "--artifact-path", "x", "--a11y-path", "y", "--verbose"],
        )
        assert main() == 0
        args = mock_run_a11y.call_args[0][0]
        assert args.verbose is True

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pbir_a11y.run_a11y", return_value=1)
    def test_main_returns_run_a11y_code(self, _mock_run_a11y, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["invoke_pbir_a11y.py", "--artifact-path", "x", "--a11y-path", "y"],
        )
        assert main() == 1
