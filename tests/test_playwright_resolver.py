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
        self._report_datasets: dict[tuple[str, str], str] = {}

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

    def add_report_dataset(
        self,
        workspace_id: str,
        report_id: str,
        dataset_id: str,
    ) -> None:
        """Bind a fake report to the semantic model it should resolve to."""
        self._report_datasets[(workspace_id, report_id)] = dataset_id

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
        """Return the fake dataset ID bound to the report, if any."""
        return self._report_datasets.get((workspace_id, report_id), "")


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


def test_resolve_item_no_match_names_candidates_in_the_message(env_file: Path) -> None:
    """The message itself names the items the workspace actually has.

    `resolve_item` used to attach `candidates=all_names` to the exception
    and then format a message that mentioned none of them -- a dead end
    while the CLI was holding the answer.
    """
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Sales Report")
    client.add_item("ws-dev", "Report", "rpt-2", "Marketing Report")
    resolved_env = resolve_environment("dev", env_path=env_file)

    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_item("ThinReport", "Report", resolved_env, client)

    message = str(exc_info.value)
    assert "Sales Report" in message
    assert "Marketing Report" in message


def test_resolve_item_no_match_says_so_when_workspace_has_no_items_of_that_type(
    env_file: Path,
) -> None:
    """An empty candidate list says so plainly rather than printing nothing."""
    client = FakeClient()
    resolved_env = resolve_environment("dev", env_path=env_file)

    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_item("ThinReport", "Report", resolved_env, client)

    message = str(exc_info.value)
    assert "no report items" in message.lower()


def test_resolve_item_no_match_caps_the_listed_candidates(env_file: Path) -> None:
    """Many items stay readable in an 80-column terminal -- the list is capped."""
    client = FakeClient()
    for i in range(20):
        client.add_item("ws-dev", "Report", f"rpt-{i}", f"Report {i}")
    resolved_env = resolve_environment("dev", env_path=env_file)

    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_item("Missing", "Report", resolved_env, client)

    message = str(exc_info.value)
    assert len(exc_info.value.candidates) == 20  # the exception still carries all of them
    listed_line = next(line for line in message.splitlines() if "Report 0" in line)
    assert len(listed_line) <= 80 or "more" in message.lower()


def test_resolve_item_no_match_lists_the_workspace_only_once(env_file: Path) -> None:
    """`list_items` is called once on the no-match path, not twice."""
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Other Report")
    resolved_env = resolve_environment("dev", env_path=env_file)

    calls = []
    real_list_items = client.list_items

    def counting_list_items(workspace_id, item_type):
        calls.append((workspace_id, item_type))
        return real_list_items(workspace_id, item_type)

    client.list_items = counting_list_items

    with pytest.raises(ServiceResolutionError):
        resolve_item("Missing", "Report", resolved_env, client)

    assert len(calls) == 1


def test_resolve_item_multiple_matches(env_file: Path) -> None:
    """Multiple matching items raise with candidate names."""
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Sales")
    client.add_item("ws-dev", "Report", "rpt-2", "Sales")
    resolved_env = resolve_environment("dev", env_path=env_file)

    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_item("Sales", "Report", resolved_env, client)
    assert "Multiple Report items match" in str(exc_info.value)


def test_resolve_report_uses_bound_dataset_id(env_file: Path) -> None:
    """Resolved report uses the semantic model it is actually bound to."""
    client = FakeClient()
    client.add_item("ws-dev", "Report", "rpt-1", "Sales Report")
    client.add_report_dataset("ws-dev", "rpt-1", "sm-1")
    resolved_env = resolve_environment("dev", env_path=env_file)

    report = resolve_report("Sales Report", resolved_env, client)
    assert report == ResolvedReport(
        workspace_id="ws-dev",
        report_id="rpt-1",
        report_name="Sales Report",
        semantic_model_id="sm-1",
        environment="dev",
    )


def test_resolve_report_falls_back_to_own_id_when_dataset_unknown(
    env_file: Path,
) -> None:
    """A report with no discoverable dataset falls back to its own ID."""
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


def test_resolve_environment_with_workspace_override_never_opens_environments_yml(
    tmp_path: Path,
) -> None:
    """A resolved workspace makes environments.yml optional (task 3).

    Passing a path to a file that does not exist proves the file is never
    opened: if it were, this would raise before the assertions run.
    """
    missing_env_path = tmp_path / "does-not-exist" / "environments.yml"

    resolved = resolve_environment(
        "dev", env_path=missing_env_path, workspace_id_override="ws-known"
    )

    assert resolved.workspace_id == "ws-known"
    assert resolved.environment == "dev"


def test_resolve_environment_without_override_still_reads_environments_yml(
    env_file: Path,
) -> None:
    """A repository that pins its workspace in environments.yml today is
    unaffected (backward-compat constraint)."""
    resolved = resolve_environment("dev", env_path=env_file)

    assert resolved.workspace_id == "ws-dev"


def test_resolve_environment_names_both_routes_when_neither_is_available(
    monkeypatch,
) -> None:
    """No workspace and no environments.yml names both ways to fix it."""
    from fabric_ci_cd_dataops.scripts import _metadata

    monkeypatch.setattr(
        _metadata,
        "resolve_environments_yml",
        lambda *a, **k: (_ for _ in ()).throw(
            _metadata.MetadataNotFoundError(
                Path("environments.yml"),
                [Path(".fab-test/metadata/environments.yml"), Path(".github/metadata/environments.yml")],
            )
        ),
    )
    import fabric_ci_cd_dataops.scripts.playwright_validation.resolver as resolver_module

    monkeypatch.setattr(
        resolver_module, "resolve_environments_yml", _metadata.resolve_environments_yml
    )

    with pytest.raises(ServiceResolutionError) as exc_info:
        resolve_environment("dev")

    message = str(exc_info.value)
    assert "workspace:" in message
    assert "environments.yml" in message


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
