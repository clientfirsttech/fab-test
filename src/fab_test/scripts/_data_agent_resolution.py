"""Resolve deployed Fabric Data Agent endpoints."""

from __future__ import annotations

from .playwright_validation.resolver import (
    ResolvedEnvironment,
    ResolvedItem,
    ServiceResolutionError,
    resolve_item,
)

DATA_AGENT_API_VERSION = "2024-05-01-preview"


def data_agent_base_url(workspace_id: str, item_id: str) -> str:
    """Return the live assistant endpoint for one deployed Data Agent."""
    return (
        "https://api.fabric.microsoft.com/v1/workspaces/"
        f"{workspace_id}/dataagents/{item_id}/aiassistant/openai"
    )


def resolve_data_agent_item(client, workspace_id: str, name: str) -> ResolvedItem:
    """Resolve ``name`` to a unique deployed Data Agent in ``workspace_id``."""
    return resolve_item(name, "DataAgent", ResolvedEnvironment("service", workspace_id), client)


def resolve_data_agent_url(client, workspace_id: str, name: str) -> str:
    """Resolve ``name`` to its live assistant endpoint URL."""
    try:
        item = resolve_data_agent_item(client, workspace_id, name)
    except ServiceResolutionError as exc:
        visible = exc.candidates or [
            item.get("displayName", "")
            for item in client.list_items(workspace_id, "DataAgent")
        ]
        if visible and "Closest candidates:" not in str(exc):
            shown = ", ".join(visible[:10])
            more = f", and {len(visible) - 10} more" if len(visible) > 10 else ""
            raise ServiceResolutionError(
                f"{exc} Visible Data Agents: {shown}{more}.",
                environment=exc.environment,
                workspace_id=exc.workspace_id,
                item_type=exc.item_type,
                candidates=visible,
            ) from exc
        raise
    return data_agent_base_url(item.workspace_id, item.item_id)
