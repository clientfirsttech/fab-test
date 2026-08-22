"""Unit tests for scripts/smoke_test_orchestrator.py."""

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.analyzers]


from fabric_ci_cd_dataops.scripts.smoke_test_orchestrator import (
    bump_platform_content,
    bump_platform_files,
    platform_paths_for,
)


class TestPlatformPathsFor:
    """Tests for platform_paths_for selection."""

    def test_returns_semantic_model_path(self):
        """Given 'semantic-model', should return only the semantic model path."""
        paths = platform_paths_for("semantic-model")

        assert len(paths) == 1
        assert paths[0].name == ".platform"
        assert paths[0].parts[-2] == "SampleModel-PQLAssert.SemanticModel"

    def test_returns_report_path(self):
        """Given 'report', should return only the report path."""
        paths = platform_paths_for("report")

        assert len(paths) == 1
        assert paths[0].name == ".platform"
        assert paths[0].parts[-2] == "SampleModel-PQLAssert.Report"

    def test_returns_both_paths(self):
        """Given 'both', should return both artifact paths."""
        paths = platform_paths_for("both")

        assert len(paths) == 2
        names = {p.parts[-2] for p in paths}
        assert names == {
            "SampleModel-PQLAssert.SemanticModel",
            "SampleModel-PQLAssert.Report",
        }


class TestBumpPlatformContent:
    """Tests for bump_platform_content."""

    def test_adds_timestamp_to_config(self):
        """Given a .platform JSON string, should add _smokeTestTimestamp to config."""
        content = json.dumps(
            {
                "$schema": "https://example.com/schema.json",
                "metadata": {"type": "SemanticModel", "displayName": "Sample"},
                "config": {"version": "2.0", "logicalId": "abc-123"},
            },
            indent=2,
        )

        result = json.loads(bump_platform_content(content, "2026-08-05T12:00:00Z"))

        assert result["config"]["_smokeTestTimestamp"] == "2026-08-05T12:00:00Z"
        assert result["config"]["version"] == "2.0"
        assert result["config"]["logicalId"] == "abc-123"
        assert result["metadata"]["displayName"] == "Sample"

    def test_updates_existing_timestamp(self):
        """Given .platform already has timestamp, should update without duplication."""
        content = json.dumps(
            {
                "metadata": {"type": "SemanticModel"},
                "config": {
                    "version": "2.0",
                    "_smokeTestTimestamp": "2026-01-01T00:00:00Z",
                },
            },
            indent=2,
        )

        result = json.loads(bump_platform_content(content, "2026-08-05T12:00:00Z"))

        assert result["config"]["_smokeTestTimestamp"] == "2026-08-05T12:00:00Z"
        assert list(result["config"].keys()).count("_smokeTestTimestamp") == 1

    def test_preserves_trailing_newline(self):
        """Given input ends with newline, output should also end with newline."""
        content = '{"config":{}}\n'

        result = bump_platform_content(content, "2026-08-05T12:00:00Z")

        assert result.endswith("\n")

    def test_preserves_non_config_sections(self):
        """Given metadata and config sections, should preserve both exactly."""
        original = {
            "$schema": "https://example.com/schema.json",
            "metadata": {
                "type": "SemanticModel",
                "displayName": "SampleModel-PQLAssert",
            },
            "config": {
                "version": "2.0",
                "logicalId": "ff782ecf-4858-4e2a-b0dd-d301e814ce39",
            },
        }
        content = json.dumps(original, indent=2)

        result = json.loads(bump_platform_content(content, "2026-08-05T12:00:00Z"))

        assert result["metadata"] == original["metadata"]
        assert result["$schema"] == original["$schema"]


class TestBumpPlatformFiles:
    """Tests for bump_platform_files."""

    def test_bumps_multiple_platform_files(self, tmp_path: Path):
        """Given multiple .platform paths, should update each one."""
        model_platform = tmp_path / "model.platform"
        report_platform = tmp_path / "report.platform"
        model_platform.write_text('{"config":{"version":"1.0"}}', encoding="utf-8")
        report_platform.write_text(
            '{"metadata":{"type":"Report"},"config":{"version":"2.0"}}',
            encoding="utf-8",
        )

        bump_platform_files([model_platform, report_platform])

        model_data = json.loads(model_platform.read_text(encoding="utf-8"))
        report_data = json.loads(report_platform.read_text(encoding="utf-8"))
        assert "_smokeTestTimestamp" in model_data["config"]
        assert "_smokeTestTimestamp" in report_data["config"]
        assert model_data["config"]["version"] == "1.0"
        assert report_data["metadata"]["type"] == "Report"

    def test_bumps_only_report_platform(self, tmp_path: Path):
        """Given only a report .platform path, should update only that file."""
        report_platform = tmp_path / "report.platform"
        report_platform.write_text(
            '{"metadata":{"type":"Report"},"config":{}}', encoding="utf-8"
        )

        bump_platform_files([report_platform])

        report_data = json.loads(report_platform.read_text(encoding="utf-8"))
        assert "_smokeTestTimestamp" in report_data["config"]

    def test_dry_run_does_not_write(self, tmp_path: Path):
        """Given dry_run=True, should not modify files."""
        platform = tmp_path / "model.platform"
        original = '{"config":{"version":"1.0"}}'
        platform.write_text(original, encoding="utf-8")

        bump_platform_files([platform], dry_run=True)

        assert platform.read_text(encoding="utf-8") == original
