"""Unit tests for scripts/detect_changes.py."""

import json
import os
import sys
from pathlib import Path
from unittest import mock

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

    def test_a_fab_test_override_wins(self, tmp_path: Path):
        """The documented override directory reaches this loader too.

        It held a fourth private copy of the map loader, so `.fab-test/`
        resolved for the rulesets and not here.
        """
        for layer, artifact_type in ((".github", "Legacy"), (".fab-test", "Override")):
            metadata_dir = tmp_path / layer / "metadata"
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "artifact-map.json").write_text(
                json.dumps({".SemanticModel": artifact_type})
            )

        assert load_artifact_map(tmp_path)[".SemanticModel"] == "Override"

    def test_missing_map_falls_back_to_the_packaged_copy(self, tmp_path: Path):
        """It used to exit 1, which cannot be right for a pip install.

        This loader runs from workflows inside a checkout today, so the exit
        was survivable -- but it is the same map three other callers already
        answer from the packaged copy, and disagreeing about that is the
        defect.
        """
        result = load_artifact_map(tmp_path)

        assert result[".SemanticModel"] == "SemanticModel"


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
        result = group_changes_by_artifact(changed, artifact_map)

        assert len(result) == 2
        assert result[".fabric/artifacts/SalesModel.SemanticModel"]["type"] == "SemanticModel"
        assert len(result[".fabric/artifacts/SalesModel.SemanticModel"]["changed_files"]) == 2
        assert result[".fabric/artifacts/SalesReport.Report"]["type"] == "Report"

    def test_ignores_files_outside_artifacts(self):
        """Files outside .fabric/artifacts are ignored."""
        changed = ["scripts/deploy.py", ".github/workflows/ci.yml"]
        assert group_changes_by_artifact(changed, {}) == {}


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
        with (
            mock.patch("fabric_ci_cd_dataops.scripts.detect_changes.get_changed_files", return_value=changed),
            mock.patch.object(sys, "argv", argv),
            mock.patch.dict(os.environ, {"GITHUB_WORKSPACE": str(tmp_path)}, clear=False),
        ):
            main()

        output = tmp_path / "changed-artifacts.json"
        assert output.exists()
        data = json.loads(output.read_text())
        assert data["total_artifacts"] == 1
        assert data["changed_artifacts"][0]["name"] == "SalesModel.SemanticModel"
