"""Contract tests for the Playwright impact manifest builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.impact import (
    ImpactManifest,
    build_impact_manifest,
    load_changed_artifacts,
)
from fabric_ci_cd_dataops.scripts.playwright_validation.resolver import (
    ResolvedReport,
    ServiceResolutionError,
)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """Create a minimal environments.yml for impact tests."""
    env_path = tmp_path / "environments.yml"
    env_path.write_text(
        """
environments:
  dev:
    description: "Development"
    workspace_id: "ws-dev"
    allowed_branches:
      - develop
    promotion_target: test
""",
        encoding="utf-8",
    )
    return env_path


class FakeClient:
    """In-memory service client for deterministic impact tests."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._dependents: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def add_item(
        self,
        workspace_id: str,
        item_type: str,
        item_id: str,
        display_name: str,
    ) -> None:
        """Add a fake item to the client."""
        key = (workspace_id, item_type)
        self._items.setdefault(key, []).append(
            {"id": item_id, "displayName": display_name, "type": item_type}
        )

    def add_dependent(
        self,
        workspace_id: str,
        semantic_model_id: str,
        report_id: str,
        display_name: str,
    ) -> None:
        """Add a fake dependent report."""
        key = (workspace_id, semantic_model_id)
        self._dependents.setdefault(key, []).append(
            {
                "id": report_id,
                "displayName": display_name,
                "type": "Report",
                "workspaceId": workspace_id,
            }
        )

    def list_items(
        self,
        workspace_id: str,
        item_type: str,
    ) -> list[dict[str, Any]]:
        """Return fake items for the workspace/type."""
        return list(self._items.get((workspace_id, item_type), []))

    def get_dependent_reports(
        self,
        workspace_id: str,
        semantic_model_id: str,
    ) -> list[dict[str, Any]]:
        """Return fake dependent reports."""
        return list(self._dependents.get((workspace_id, semantic_model_id), []))

    def get_report_dataset_id(self, workspace_id: str, report_id: str) -> str:
        """Not exercised by the impact-analysis path; protocol filler."""
        return ""


@pytest.fixture
def changed_artifacts(tmp_path: Path) -> Path:
    """Create a changed-artifacts.json file for impact tests."""
    path = tmp_path / "changed-artifacts.json"
    path.write_text(
        """
{
  "changed_artifacts": [
    {
      "name": "Sales Model",
      "type": "SemanticModel",
      "path": "SalesModel.SemanticModel"
    },
    {
      "name": "Sales Report",
      "type": "Report",
      "path": "SalesReport.Report"
    },
    {
      "name": "Notebook",
      "type": "Notebook",
      "path": "Notebook.Notebook"
    }
  ]
}
""",
        encoding="utf-8",
    )
    return path


def test_load_changed_artifacts(changed_artifacts: Path) -> None:
    """Changed artifacts are loaded as a list."""
    artifacts = load_changed_artifacts(changed_artifacts)
    assert len(artifacts) == 3
    assert artifacts[0]["type"] == "SemanticModel"


def test_build_impact_manifest_deduplicates(
    env_file: Path,
    changed_artifacts: Path,
) -> None:
    """Reports reached via multiple paths are deduplicated with reasons."""
    client = FakeClient()
    client.add_item("ws-dev", "SemanticModel", "sm-1", "Sales Model")
    client.add_item("ws-dev", "Report", "rpt-1", "Sales Report")
    client.add_dependent("ws-dev", "sm-1", "rpt-1", "Sales Report")

    manifest = build_impact_manifest(
        changed_artifacts, "dev", client, env_path=env_file
    )

    assert len(manifest.reports) == 1
    entry = manifest.reports[0]
    assert entry.report_id == "rpt-1"
    assert len(entry.reasons) == 2
    assert "depends on Sales Model" in entry.reasons
    assert "changed report Sales Report" in entry.reasons


def test_build_impact_manifest_skips_unsupported(
    env_file: Path,
    changed_artifacts: Path,
) -> None:
    """Unsupported artifact types are recorded as skipped."""
    client = FakeClient()
    client.add_item("ws-dev", "SemanticModel", "sm-1", "Sales Model")
    client.add_item("ws-dev", "Report", "rpt-1", "Sales Report")
    client.add_dependent("ws-dev", "sm-1", "rpt-1", "Sales Report")

    manifest = build_impact_manifest(
        changed_artifacts, "dev", client, env_path=env_file
    )

    assert any("Notebook" in skipped for skipped in manifest.skipped)


def test_build_impact_manifest_missing_workspace(
    env_file: Path,
    changed_artifacts: Path,
) -> None:
    """Missing workspace metadata fails before service calls."""
    env_file.write_text(
        """
environments:
  dev:
    description: "Development"
    workspace_id: ""
    allowed_branches:
      - develop
    promotion_target: test
""",
        encoding="utf-8",
    )
    client = FakeClient()

    with pytest.raises(ServiceResolutionError) as exc_info:
        build_impact_manifest(changed_artifacts, "dev", client, env_path=env_file)
    assert "workspace_id" in str(exc_info.value)


def test_impact_manifest_write(tmp_path: Path) -> None:
    """The manifest writes a JSON file with the expected shape."""
    manifest = ImpactManifest()
    manifest.add_report(
        ResolvedReport(
            workspace_id="ws-dev",
            report_id="rpt-1",
            report_name="Sales Report",
            semantic_model_id="sm-1",
            environment="dev",
        ),
        "depends on Sales Model",
    )
    manifest.skip_artifact("Notebook", "Notebook")

    path = tmp_path / "impact.json"
    manifest.write(path)

    data = path.read_text(encoding="utf-8")
    assert '"total": 1' in data
    assert '"report_id": "rpt-1"' in data
    assert "Notebook" in data
