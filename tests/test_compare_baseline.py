"""Unit tests for scripts/compare_baseline.py."""

import json
import sys
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.compare_baseline import BaselineComparator, main


class TestBaselineComparator:
    """Tests for BaselineComparator."""

    def test_load_existing_baseline(self, tmp_path: Path):
        """Existing baseline JSON is loaded."""
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"version": "1.0.0"}))
        comparator = BaselineComparator(str(baseline))
        assert comparator.baseline["version"] == "1.0.0"

    def test_missing_baseline_raises(self, tmp_path: Path):
        """Missing baseline file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            BaselineComparator(str(tmp_path / "missing.json"))

    def test_compare_returns_success(self, tmp_path: Path):
        """Comparison returns a SUCCESS result structure."""
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"version": "1.0.0"}))
        comparator = BaselineComparator(str(baseline))
        result = comparator.compare("SalesModel_TEST", "workspace-123")
        assert result["comparison_status"] == "SUCCESS"
        assert result["artifact_name"] == "SalesModel_TEST"
        assert result["workspace_id"] == "workspace-123"
        assert result["differences"] == []


class TestMain:
    """Tests for the CLI entry point."""

    def test_main_success_exit(self, tmp_path: Path, monkeypatch):
        """Successful comparison exits 0 and writes JSON output."""
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"version": "1.0.0"}))
        output = tmp_path / "comparison-results.json"

        with pytest.raises(SystemExit) as exc_info:
            main()
        # main() without argv parses sys.argv, so invoke via subprocess-style patching.

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "compare_baseline.py",
                "--artifact-name",
                "SalesModel_TEST",
                "--workspace-id",
                "workspace-123",
                "--baseline-file",
                str(baseline),
                "--output-json",
                str(output),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["comparison_status"] == "SUCCESS"

    def test_main_failure_missing_baseline(self, tmp_path: Path, monkeypatch):
        """Missing baseline causes exit 1."""
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "compare_baseline.py",
                "--artifact-name",
                "SalesModel_TEST",
                "--workspace-id",
                "workspace-123",
                "--baseline-file",
                str(tmp_path / "missing.json"),
            ],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
