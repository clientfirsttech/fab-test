"""Find a deployed Fabric Data Agent and build its API URL (Data Agent Testing epic).

The one place that knows the endpoint's shape, so people never hand-build
``.../dataagents/{id}/aiassistant/openai``. It reuses the Playwright
resolver's name matching and "no match" message (which lists the workspace's
agents), and adds what Data Agents need: a GUID is an item name too, and two
agents may share a display name.
"""

from __future__ import annotations

import re
from typing import Any

from .playwright_validation.resolver import (
    ItemNotFoundError,
    ResolvedEnvironment,
    ResolvedItem,
    ServiceClient,
    ServiceResolutionError,
    list_inventory,
    resolve_item,
)

ITEM_TYPE = "DataAgent"
_GUID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


def data_agent_base_url(workspace_id: str, item_id: str) -> str:
    """The live Assistants-compatible endpoint of one deployed Data Agent."""
    return f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/dataagents/{item_id}/aiassistant/openai"


def list_data_agents(client: ServiceClient, workspace_id: str) -> list[dict[str, Any]]:
    """The workspace's Data Agents, minus the usage-metrics items Microsoft creates."""
    return list_inventory(client, workspace_id, ITEM_TYPE)


def resolve_data_agent(client: ServiceClient, workspace_id: str, name: str) -> ResolvedItem:
    """Resolve ``name`` (a display name, with or without ``.DataAgent``, or a GUID) to one deployed agent.

    Raises ``ItemNotFoundError`` naming the agents the workspace has, or ``ServiceResolutionError`` naming
    the ids of agents that share the name; never an HTTP error.
    """
    environment = ResolvedEnvironment("service", workspace_id)
    if _GUID.match(name.strip()):
        wanted = name.strip().lower()
        for item in client.list_items(workspace_id, ITEM_TYPE):
            if str(item.get("id", "")).lower() == wanted:
                return ResolvedItem(workspace_id, ITEM_TYPE, item["id"], item.get("displayName", ""), "service")
    try:  # the shared resolver's suffix list has no .DataAgent, and every analyzer shares it
        return resolve_item(name.removesuffix(f".{ITEM_TYPE}"), ITEM_TYPE, environment, client)
    except ItemNotFoundError:
        raise
    except ServiceResolutionError as exc:  # the only other outcome of resolve_item: more than one match
        raise _ambiguous(client, workspace_id, name, exc) from None


def _ambiguous(client: ServiceClient, workspace_id: str, name: str, cause: ServiceResolutionError):
    wanted = name.removesuffix(f".{ITEM_TYPE}").strip().lower()
    twins = [i for i in client.list_items(workspace_id, ITEM_TYPE) if str(i.get("displayName", "")).lower() == wanted]
    listed = ", ".join(f"{i.get('displayName', '')} ({i.get('id', '')})" for i in twins)
    return ServiceResolutionError(
        f"Multiple {ITEM_TYPE} items match '{name}' in workspace {workspace_id}: {listed}. Pass the agent's GUID.",
        environment=cause.environment, workspace_id=workspace_id, item_type=ITEM_TYPE, candidates=cause.candidates,
    )


def resolve_data_agent_url(client: ServiceClient, workspace_id: str, name: str) -> str:
    """The API URL of the deployed Data Agent ``name`` (see `resolve_data_agent`)."""
    item = resolve_data_agent(client, workspace_id, name)
    return data_agent_base_url(item.workspace_id, item.item_id)
