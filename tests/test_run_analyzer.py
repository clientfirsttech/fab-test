"""Unit tests for scripts/run_analyzer.py."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

from fabric_ci_cd_dataops.scripts.run_analyzer import AnalyzerRunner, main


class TestAnalyzerRunner:
    """Tests for AnalyzerRunner."""

    def test_load_metadata_file_not_found(self):
        """Raise when metadata file does not exist."""
        with pytest.raises(FileNotFoundError):
            AnalyzerRunner("/nonexistent/analyzers.json")

    def test_get_analyzer_config_unknown(self, sample_analyzers_metadata: Path):
        """Raise for unknown analyzer."""
        runner = AnalyzerRunner(str(sample_analyzers_metadata))
        with pytest.raises(ValueError, match="Analyzer 'unknown' not found"):
            runner.get_analyzer_config("unknown")

    def test_build_command_substitution(self, sample_analyzers_metadata: Path):
        """Placeholder substitution works for command arguments."""
        runner = AnalyzerRunner(str(sample_analyzers_metadata))
        config = runner.get_analyzer_config("fake_analyzer")
        command = runner.build_command(
            config,
            artifact_name="SalesModel",
            artifact_path=".fabric/artifacts/SalesModel.SemanticModel",
            workspace_id="workspace-123",
            environment="dev",
            output_path="out.json",
        )
        assert command == [
            "python",
            "-c",
            "print('SalesModel .fabric/artifacts/SalesModel.SemanticModel')",
        ]

    def test_run_analyzer_success(self, sample_analyzers_metadata: Path, tmp_path: Path):
        """Successful analyzer execution returns success."""
        runner = AnalyzerRunner(str(sample_analyzers_metadata))
        result = runner.run_analyzer(
            analyzer_name="fake_analyzer",
            artifact_name="SalesModel",
            artifact_path=".fabric/artifacts/SalesModel.SemanticModel",
            artifact_type="SemanticModel",
        )
        assert result["success"] is True
        assert result["exit_code"] == 0
        assert "SalesModel" in result["stdout"]
        assert result["analyzer"] == "fake_analyzer"

    def test_run_analyzer_failure(self, sample_analyzers_metadata: Path):
        """Non-zero exit code returns failure."""
        runner = AnalyzerRunner(str(sample_analyzers_metadata))
        result = runner.run_analyzer(
            analyzer_name="failing_analyzer",
            artifact_name="SalesModel",
            artifact_path=".fabric/artifacts/SalesModel.SemanticModel",
            artifact_type="SemanticModel",
        )
        assert result["success"] is False
        assert result["exit_code"] == 1

    def test_run_analyzer_missing_command(self, sample_analyzers_metadata: Path):
        """Missing analyzer command is reported as failure."""
        runner = AnalyzerRunner(str(sample_analyzers_metadata))
        result = runner.run_analyzer(
            analyzer_name="missing_analyzer",
            artifact_name="SalesModel",
            artifact_path=".fabric/artifacts/SalesModel.SemanticModel",
            artifact_type="SemanticModel",
        )
        assert result["success"] is False
        assert "not found" in result["stderr"]

    def test_run_analyzer_dry_run(self, sample_analyzers_metadata: Path):
        """Dry run does not execute command and reports success."""
        runner = AnalyzerRunner(str(sample_analyzers_metadata))
        result = runner.run_analyzer(
            analyzer_name="fake_analyzer",
            artifact_name="SalesModel",
            artifact_path=".fabric/artifacts/SalesModel.SemanticModel",
            artifact_type="SemanticModel",
            dry_run=True,
        )
        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["stdout"] == "[DRY RUN] No output"

    def test_run_analyzer_output_json(
        self, sample_analyzers_metadata: Path, tmp_path: Path, capsys
    ):
        """Writing runner results to JSON file works via main entry point."""
        output_file = tmp_path / "result.json"
        argv = [
            "run_analyzer.py",
            "--analyzer",
            "fake_analyzer",
            "--artifact-name",
            "SalesModel",
            "--artifact-path",
            ".fabric/artifacts/SalesModel.SemanticModel",
            "--artifact-type",
            "SemanticModel",
            "--metadata-path",
            str(sample_analyzers_metadata),
            "--output-json",
            str(output_file),
        ]
        with mock.patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        assert output_file.exists()
        saved = json.loads(output_file.read_text(encoding="utf-8"))
        assert saved["success"] is True
        assert saved["analyzer"] == "fake_analyzer"


class TestMain:
    """Tests for run_analyzer.py main entry point."""

    def test_main_success(self, sample_analyzers_metadata: Path, monkeypatch):
        """Main exits with 0 on successful analyzer run."""
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_analyzer.py",
                "--analyzer",
                "fake_analyzer",
                "--artifact-name",
                "SalesModel",
                "--artifact-path",
                ".fabric/artifacts/SalesModel.SemanticModel",
                "--artifact-type",
                "SemanticModel",
                "--metadata-path",
                str(sample_analyzers_metadata),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_main_failure(self, sample_analyzers_metadata: Path, monkeypatch):
        """Main exits with 1 on analyzer failure."""
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "run_analyzer.py",
                "--analyzer",
                "failing_analyzer",
                "--artifact-name",
                "SalesModel",
                "--artifact-path",
                ".fabric/artifacts/SalesModel.SemanticModel",
                "--artifact-type",
                "SemanticModel",
                "--metadata-path",
                str(sample_analyzers_metadata),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
