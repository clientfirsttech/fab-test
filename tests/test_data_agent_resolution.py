"""Resolution and discovery contracts for the Data Agent analyzer."""

from __future__ import annotations

import argparse

import pytest


class _FakeClient:
    def __init__(self, items):
        self._items = items

    def list_items(self, workspace_id: str, item_type: str):
        assert workspace_id == "00000000-0000-0000-0000-000000000001"
        assert item_type == "DataAgent"
        return list(self._items)


@pytest.mark.fab_test
def test_resolve_data_agent_url_names_visible_candidates_on_a_missing_agent():
    from fab_test.scripts._data_agent_resolution import resolve_data_agent_url
    from fab_test.scripts.playwright_validation.resolver import ServiceResolutionError

    client = _FakeClient(
        [
            {"id": "agent-1", "displayName": "Sales Agent"},
            {"id": "agent-2", "displayName": "Support Agent"},
        ]
    )

    with pytest.raises(ServiceResolutionError, match="Sales Agent") as raised:
        resolve_data_agent_url(client, "00000000-0000-0000-0000-000000000001", "Missing Agent")

    assert "Support Agent" in str(raised.value)


@pytest.mark.fab_test
def test_paired_service_artifacts_wraps_a_missing_agent_name_as_a_cli_error(monkeypatch, tmp_path):
    from fab_test.scripts import _data_agent_discovery as discovery
    from fab_test.scripts._service_export import ServiceExportError
    from fab_test.scripts._target import parse_target

    args = argparse.Namespace(
        mode="service",
        resolved_target=parse_target(
            "00000000-0000-0000-0000-000000000001.Workspace/Missing Agent.DataAgent"
        ),
        workspace_id="00000000-0000-0000-0000-000000000001",
    )
    monkeypatch.setattr(
        discovery,
        "build_service_client",
        lambda _args: _FakeClient([{"id": "agent-1", "displayName": "Sales Agent"}]),
    )

    with pytest.raises(ServiceExportError, match="Sales Agent") as raised:
        discovery.paired_service_artifacts(args, tmp_path, [])

    assert raised.value.code == 1


@pytest.mark.fab_test
def test_paired_service_artifacts_wraps_ambiguous_agent_names(monkeypatch, tmp_path):
    from fab_test.scripts import _data_agent_discovery as discovery
    from fab_test.scripts._service_export import ServiceExportError
    from fab_test.scripts._target import parse_target

    args = argparse.Namespace(
        mode="service",
        resolved_target=parse_target(
            "00000000-0000-0000-0000-000000000001.Workspace/Sales Agent.DataAgent"
        ),
        workspace_id="00000000-0000-0000-0000-000000000001",
    )
    monkeypatch.setattr(
        discovery,
        "build_service_client",
        lambda _args: _FakeClient(
            [
                {"id": "agent-1", "displayName": "Sales Agent"},
                {"id": "agent-2", "displayName": "Sales Agent"},
            ]
        ),
    )

    with pytest.raises(ServiceExportError, match="Multiple DataAgent items match 'Sales Agent'") as raised:
        discovery.paired_service_artifacts(args, tmp_path, [])

    assert raised.value.code == 1
