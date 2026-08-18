"""Unit tests for scripts/invoke_pqlint.py."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [pytest.mark.pql_lint, pytest.mark.analyzers]


from fabric_ci_cd_dataops.scripts._analyzer_envelope import ENVELOPE_REQUIRED_KEYS
from fabric_ci_cd_dataops.scripts.invoke_pqlint import (
    build_command,
    main,
    parse_findings,
    run_pqlint,
    validate_path,
    write_results,
)


class TestValidatePath:
    """Tests for path validation."""

    def test_missing_path_exits(self, tmp_path: Path):
        """Missing artifact path exits with error."""
        missing = tmp_path / "missing"
        with pytest.raises(SystemExit) as exc_info:
            validate_path(str(missing), "Artifact path")
        assert exc_info.value.code == 1


class TestBuildCommand:
    """Tests for command builder."""

    def test_command_structure(self, tmp_path: Path):
        """Command includes the artifact path and output path."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        command = build_command(artifact, output_path=output)
        assert command[0] in {"pqlint", "python"}
        assert str(artifact) in command
        assert str(output) in command


class TestParseFindings:
    """Tests for output parsing."""

    def test_empty_string_returns_no_findings(self):
        """Empty output creates no findings."""
        assert parse_findings("") == []

    def test_dict_with_findings_key(self):
        """Findings are parsed when wrapped inside a dict."""
        raw = '{"findings":[{"rule":"PBI-001"}]}'
        assert parse_findings(raw) == [{"rule": "PBI-001"}]


class TestWriteResults:
    """Tests for result writer."""

    def test_results_written(self, tmp_path: Path):
        """Results JSON includes expected keys."""
        output_path = tmp_path / "results.json"
        artifact_path = tmp_path / "SalesModel.SemanticModel"
        artifact_path.mkdir()
        write_results(output_path=output_path, status="passed", findings=[], artifact_path=artifact_path, message="OK")
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["message"] == "OK"
        assert data["analyzer"] == "pqlint"
        assert data["findings"] == []

    def test_envelope_shape(self, tmp_path: Path):
        """Envelope contains every required key from the shared schema."""
        output_path = tmp_path / "envelope.json"
        write_results(output_path=output_path, status="passed", findings=[], artifact_path=tmp_path / "model", message="OK")
        data = json.loads(output_path.read_text(encoding="utf-8"))
        missing = ENVELOPE_REQUIRED_KEYS - data.keys()
        assert not missing, f"Envelope missing keys: {missing}"


class TestVerbosity:
    """Tests for ANALYZER_VERBOSITY handling in run_pqlint."""

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pqlint.subprocess.run")
    def test_summary_suppresses_header(self, mock_run, tmp_path: Path, monkeypatch, capsys):
        """Given ANALYZER_VERBOSITY=summary, wrapper prints no pqlint header."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(returncode=0, stdout='{"findings": []}', stderr="")

        class Args:
            artifact_path = str(artifact)
            output_path = str(output)
            subscription_key = ""

        exit_code = run_pqlint(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "pqlint" not in captured.out.lower()

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pqlint.subprocess.run")
    def test_debug_includes_command(self, mock_run, tmp_path: Path, monkeypatch, capsys):
        """Given ANALYZER_VERBOSITY=debug, wrapper prints the executed command."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(returncode=0, stdout='{"findings": []}', stderr="debug stderr")

        class Args:
            artifact_path = str(artifact)
            output_path = str(output)
            subscription_key = ""

        exit_code = run_pqlint(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Executing:" in captured.out
        assert "debug stderr" in captured.out


class TestRunPqlint:
    """Tests for run_pqlint entry function."""

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pqlint.subprocess.run")
    def test_run_passes_no_findings(self, mock_run, tmp_path: Path):
        """Successful execution creates a passed result."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(returncode=0, stdout='{"findings": []}', stderr="")

        class Args:
            artifact_path = str(artifact)
            output_path = str(output)
            subscription_key = ""

        exit_code = run_pqlint(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["findings"] == []

    @mock.patch("fabric_ci_cd_dataops.scripts.invoke_pqlint.subprocess.run")
    def test_run_fails_with_findings(self, mock_run, tmp_path: Path):
        """Failed execution writes a failed result with findings."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(returncode=1, stdout='{"findings": [{"rule": "PBI-001"}]}', stderr="")

        class Args:
            artifact_path = str(artifact)
            output_path = str(output)
            subscription_key = ""

        exit_code = run_pqlint(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 1


class TestMain:
    """Tests for main entry point."""

    def test_main_invokes_runner(self, tmp_path: Path, monkeypatch):
        """Main forwards CLI arguments to the wrapper."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        monkeypatch.setattr(sys, "argv", ["invoke_pqlint.py", "--artifact-path", str(artifact), "--output-path", str(output)])
        with mock.patch("fabric_ci_cd_dataops.scripts.invoke_pqlint.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout='{"findings": []}', stderr="")
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
