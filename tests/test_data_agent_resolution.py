"""Resolving a deployed Data Agent's API URL from its name or GUID (Data Agent Testing epic)."""

from __future__ import annotations

import pytest

from fab_test.scripts._data_agent_resolution import (
    data_agent_base_url,
    list_data_agents,
    resolve_data_agent,
    resolve_data_agent_url,
)
from fab_test.scripts.playwright_validation.resolver import ItemNotFoundError, ServiceResolutionError

pytestmark = pytest.mark.fab_test

WS = "00000000-0000-0000-0000-000000000001"
SALES = "11111111-1111-1111-1111-111111111111"
SUPPORT = "22222222-2222-2222-2222-222222222222"


class FakeClient:
    def __init__(self, items):
        self.items = items
        self.asked: list[tuple[str, str]] = []

    def list_items(self, workspace_id, item_type):
        self.asked.append((workspace_id, item_type))
        return list(self.items)


@pytest.fixture
def client():
    return FakeClient([
        {"id": SALES, "displayName": "Sales Agent"},
        {"id": SUPPORT, "displayName": "Support Agent"},
    ])


def test_given_an_item_should_build_the_assistants_endpoint_the_provider_calls():
    assert data_agent_base_url(WS, SALES) == (
        f"https://api.fabric.microsoft.com/v1/workspaces/{WS}/dataagents/{SALES}/aiassistant/openai"
    )


def test_given_a_name_should_resolve_it_among_data_agents_only(client):
    item = resolve_data_agent(client, WS, "Sales Agent")

    assert (item.item_id, item.display_name) == (SALES, "Sales Agent")
    assert client.asked == [(WS, "DataAgent")]


def test_given_a_name_with_the_item_suffix_should_resolve_it(client):
    assert resolve_data_agent(client, WS, "Sales Agent.DataAgent").item_id == SALES


def test_given_a_guid_should_resolve_by_id_even_when_names_collide():
    client = FakeClient([{"id": SALES, "displayName": "Sales Agent"},
                         {"id": SUPPORT, "displayName": "Sales Agent"}])

    assert resolve_data_agent(client, WS, SUPPORT.upper()).item_id == SUPPORT


def test_given_a_name_no_agent_has_should_list_the_workspaces_agents(client):
    with pytest.raises(ItemNotFoundError) as raised:
        resolve_data_agent(client, WS, "Missing Agent")

    assert "Sales Agent" in str(raised.value) and "Support Agent" in str(raised.value)


def test_given_two_agents_with_one_name_should_tell_them_apart_by_id_and_say_how_to_choose():
    client = FakeClient([{"id": SALES, "displayName": "Sales Agent"},
                         {"id": SUPPORT, "displayName": "Sales Agent"}])

    with pytest.raises(ServiceResolutionError) as raised:
        resolve_data_agent(client, WS, "Sales Agent")

    message = str(raised.value)
    assert SALES in message and SUPPORT in message
    assert "GUID" in message


def test_given_a_name_should_resolve_its_url(client):
    assert resolve_data_agent_url(client, WS, "Support Agent") == data_agent_base_url(WS, SUPPORT)


def test_given_a_workspace_should_list_its_agents_without_microsoft_generated_items():
    client = FakeClient([{"id": SALES, "displayName": "Sales Agent"},
                         {"id": SUPPORT, "displayName": "Report Usage Metrics Report"}])

    assert [item["displayName"] for item in list_data_agents(client, WS)] == ["Sales Agent"]
