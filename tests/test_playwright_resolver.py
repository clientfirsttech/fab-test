"""Contract tests for the Playwright service resolver."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.resolver import (
    ResolvedItem,
    ResolvedReport,
    ServiceResolutionError,
    resolve_environment,
    resolve_item,
    resolve_report,
    resolve_semantic_model_dependents,
)


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    """Create a minimal environments.yml for resolver tests."""
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
  prod:
    description: "Production"
    workspace_id: "ws-prod"
    allowed_branches:
      - main
    promotion_target: null
""",
        encoding="utf-8",
    )
    return env_path


class FakeClient:
    """In-memory service client for deterministic resolver tests."""

    def __init__(self, items: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._items: dict[str, list[dict[str, Any]]] = items or {}
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
            {"id": report_id, "displayName": display_name, "type": "Report"}
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


def test_resolve_environment_case_insensitive(env_file: Path) -> None:
    """Environment labels are resolved case-insensitively."""
    resolved = resolve_environment("DEV", env_path=env_file)
    assert resolved.environment == "dev"
    assert resolved.workspace_id == "ws-dev"


def test_resolve_environment_override(env_file: Path) -> None:
    """An explicit workspace ID override is preserved."""
    resolved = resolve_environment(
        "prod", env_path=env_file, workspace_id_override="ws-override"
    )
    assert resolved.workspace_id == "ws-override"
    assert resolved.environment == "prod"


def test_resolve_environment_unknown(env_file: Path) -> None:
    """An unknown environment raises with known environments listed."""
    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_environment("staging", env_path=env_file)
    assert "staging" in str(exc_info.value)
    assert "dev" in str(exc_info.value)


def test_resolve_environment_missing_workspace(env_file: Path) -> None:
    """An environment without a workspace ID raises a clear error."""
    env_file.write_text(
        """
environments:
  empty:
    description: "Empty"
    workspace_id: ""
    allowed_branches:
      - develop
    promotion_target: test
""",
        encoding="utf-8",
    )
    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_environment("empty", env_path=env_file)
    assert "workspace_id" in str(exc_info.value)


def test_resolve_item_normalizes_suffix(env_file: Path) -> None:
    """An artifact name with a Fabric type suffix resolves to the item."""
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Sales Report")
    resolved_env = resolve_environment("dev", env_path=env_file)

    resolved = resolve_item("Sales Report.Report", "Report", resolved_env, client)
    assert resolved == ResolvedItem(
        workspace_id="ws-dev",
        item_type="Report",
        item_id="rpt-1",
        display_name="Sales Report",
        environment="dev",
    )


def test_resolve_item_no_match(env_file: Path) -> None:
    """No matching item raises with candidate names."""
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Other Report")
    resolved_env = resolve_environment("dev", env_path=env_file)

    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_item("Missing", "Report", resolved_env, client)
    assert "No Report matching 'Missing'" in str(exc_info.value)
    assert exc_info.value.candidates == ["Other Report"]


def test_resolve_item_multiple_matches(env_file: Path) -> None:
    """Multiple matching items raise with candidate names."""
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Sales")
    client.add_item("ws-dev", "Report", "rpt-2", "Sales")
    resolved_env = resolve_environment("dev", env_path=env_file)

    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_item("Sales", "Report", resolved_env, client)
    assert "Multiple Report items match" in str(exc_info.value)


def test_resolve_report_returns_dataset_fallback(env_file: Path) -> None:
    """Resolved report uses its own ID as dataset fallback."""
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Sales Report")
    resolved_env = resolve_environment("dev", env_path=env_file)

    report = resolve_report("Sales Report", resolved_env, client)
    assert report == ResolvedReport(
        workspace_id="ws-dev",
        report_id="rpt-1",
        report_name="Sales Report",
        semantic_model_id="rpt-1",
        environment="dev",
    )


def test_resolve_semantic_model_dependents(env_file: Path) -> None:
    """Dependent reports in scope are returned."""
    client = FakeClient()
    client.add_item("ws-dev", "SemanticModel", "sm-1", "Sales Model")
    client.add_dependent("ws-dev", "sm-1", "rpt-1", "Sales Report")
    resolved_env = resolve_environment("dev", env_path=env_file)

    reports = resolve_semantic_model_dependents(
        "Sales Model", resolved_env, client
    )
    assert len(reports) == 1
    assert reports[0].report_id == "rpt-1"
    assert reports[0].report_name == "Sales Report"


def test_resolve_semantic_model_dependents_excludes_out_of_scope(
    env_file: Path,
) -> None:
    """Cross-workspace dependents are excluded unless allow-listed."""
    client = FakeClient()
    client.add_item("ws-dev", "SemanticModel", "sm-1", "Sales Model")
    client._dependents[("ws-dev", "sm-1")] = [
        {
            "id": "rpt-2",
            "displayName": "Other Workspace Report",
            "type": "Report",
            "workspaceId": "ws-other",
        }
    ]
    resolved_env = resolve_environment("dev", env_path=env_file)

    reports = resolve_semantic_model_dependents(
        "Sales Model", resolved_env, client
    )
    assert reports == []


def test_resolve_semantic_model_dependents_with_allow_list(
    env_file: Path,
) -> None:
    """Cross-workspace dependents are included when explicitly allowed."""
    client = FakeClient()
    client.add_item("ws-dev", "SemanticModel", "sm-1", "Sales Model")
    client._dependents[("ws-dev", "sm-1")] = [
        {
            "id": "rpt-2",
            "displayName": "Other Workspace Report",
            "type": "Report",
            "workspaceId": "ws-other",
        }
    ]
    resolved_env = resolve_environment("dev", env_path=env_file)

    reports = resolve_semantic_model_dependents(
        "Sales Model",
        resolved_env,
        client,
        allowed_workspace_ids={"ws-dev", "ws-other"},
    )
    assert len(reports) == 1
    assert reports[0].workspace_id == "ws-other"
