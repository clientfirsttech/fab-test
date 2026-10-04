"""CLI contracts specific to the Data Agent analyzer."""

from __future__ import annotations

import json
import sys

import pytest


class _FakeClient:
    access_token = "unused"

    def __init__(self, items):
        self._items = items

    def list_items(self, workspace_id: str, item_type: str):
        assert workspace_id == "00000000-0000-0000-0000-000000000001"
        assert item_type == "DataAgent"
        return list(self._items)


def _argv(tmp_path, *extra: str) -> list[str]:
    return [
        "fab-test",
        "data-agent",
        "--workspace-id",
        "00000000-0000-0000-0000-000000000001",
        "--output-dir",
        str(tmp_path / "results"),
        "--dry-run",
        "--format",
        "json",
        *extra,
    ]


@pytest.mark.fab_test
def test_data_agent_workspace_enumeration_refuses_more_than_five_without_all_in_ci_json(
    monkeypatch, tmp_path, capsys
):
    from fab_test.scripts import _data_agent_discovery as discovery
    from fab_test.scripts import fab_test

    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        discovery,
        "build_service_client",
        lambda _args: _FakeClient(
            [{"id": f"agent-{index}", "displayName": f"Agent {index}"} for index in range(6)]
        ),
    )
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))

    code = fab_test.main()

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "--all" in captured.err


@pytest.mark.fab_test
def test_data_agent_workspace_enumeration_honors_the_all_flag(monkeypatch, tmp_path, capsys):
    from fab_test.scripts import _data_agent_discovery as discovery
    from fab_test.scripts import fab_test

    monkeypatch.setattr(
        discovery,
        "build_service_client",
        lambda _args: _FakeClient(
            [{"id": f"agent-{index}", "displayName": f"Agent {index}"} for index in range(6)]
        ),
    )
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, "--all"))

    code = fab_test.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert len(payload["artifacts"]) == 6


@pytest.mark.fab_test
def test_data_agent_cli_refuses_a_local_target(monkeypatch, tmp_path, capsys):
    from fab_test.scripts import fab_test

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test",
            "data-agent",
            "local/Sales",
            "--artifact-dir",
            str(tmp_path),
        ],
    )

    code = fab_test.main()

    captured = capsys.readouterr()
    assert code == 2
    assert "data_agent" in captured.err
    assert "Power BI Desktop instance" in captured.err
