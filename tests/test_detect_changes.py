"""Unit tests for scripts/detect_changes.py."""

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest


from fabric_ci_cd_dataops.scripts.detect_changes import (
    detect_artifact_type,
    group_changes_by_artifact,
    load_artifact_map,
    main,
)


class TestLoadArtifactMap:
    """Tests for load_artifact_map."""

    def test_loads_existing_map(self, tmp_path: Path):
        """Existing artifact-map.json is loaded."""
        metadata_dir = tmp_path / ".github" / "metadata"
        metadata_dir.mkdir(parents=True)
        map_path = metadata_dir / "artifact-map.json"
        map_path.write_text(json.dumps({".SemanticModel": "SemanticModel"}))

        result = load_artifact_map(tmp_path)
        assert result[".SemanticModel"] == "SemanticModel"

    def test_missing_map_exits(self, tmp_path: Path):
        """Missing artifact-map.json causes sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            load_artifact_map(tmp_path)
        assert exc_info.value.code == 1


class TestDetectArtifactType:
    """Tests for detect_artifact_type."""

    def test_known_extension(self):
        """Known extension resolves to mapped type."""
        mapping = {".SemanticModel": "SemanticModel", ".Report": "Report"}
        assert detect_artifact_type("SalesModel.SemanticModel", mapping) == "SemanticModel"

    def test_unknown_extension(self):
        """Unmapped extension returns Unknown."""
        assert detect_artifact_type("Readme.md", {}) == "Unknown"


class TestGroupChangesByArtifact:
    """Tests for group_changes_by_artifact."""

    def test_groups_files_under_artifacts(self):
        """Changed files under .fabric/artifacts are grouped by artifact root."""
        changed = [
            ".fabric/artifacts/SalesModel.SemanticModel/definition/model.tmdl",
            ".fabric/artifacts/SalesModel.SemanticModel/definition/tables.tmdl",
            ".fabric/artifacts/SalesReport.Report/definition/report.json",
        ]
        artifact_map = {
            ".SemanticModel": "SemanticModel",
            ".Report": "Report",
        }
        result = group_changes_by_artifact(changed, Path("."), artifact_map)

        assert len(result) == 2
        assert result[".fabric/artifacts/SalesModel.SemanticModel"]["type"] == "SemanticModel"
        assert len(result[".fabric/artifacts/SalesModel.SemanticModel"]["changed_files"]) == 2
        assert result[".fabric/artifacts/SalesReport.Report"]["type"] == "Report"

    def test_ignores_files_outside_artifacts(self):
        """Files outside .fabric/artifacts are ignored."""
        changed = ["scripts/deploy.py", ".github/workflows/ci.yml"]
        assert group_changes_by_artifact(changed, Path("."), {}) == {}


class TestMain:
    """Tests for the CLI entry point."""

    def test_main_writes_changed_artifacts_json(
        self, tmp_path: Path, monkeypatch
    ):
        """Main writes changed-artifacts.json with grouped artifacts."""
        monkeypatch.chdir(tmp_path)
        metadata_dir = tmp_path / ".github" / "metadata"
        metadata_dir.mkdir(parents=True)
        (metadata_dir / "artifact-map.json").write_text(
            json.dumps({".SemanticModel": "SemanticModel"})
        )

        changed = [
            ".fabric/artifacts/SalesModel.SemanticModel/definition/model.tmdl"
        ]
        argv = ["detect_changes.py"]
        with mock.patch("fabric_ci_cd_dataops.scripts.detect_changes.get_changed_files", return_value=changed):
            with mock.patch.object(sys, "argv", argv):
                with mock.patch.dict(os.environ, {"GITHUB_WORKSPACE": str(tmp_path)}, clear=False):
                    main()

        output = tmp_path / "changed-artifacts.json"
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["total_artifacts"] == 1
        assert data["changed_artifacts"][0]["name"] == "SalesModel.SemanticModel"
