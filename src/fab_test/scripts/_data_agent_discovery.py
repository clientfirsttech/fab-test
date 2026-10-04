"""Discovery helpers for the data-agent analyzer."""

from __future__ import annotations

import re
from pathlib import Path

from ._data_agent_resolution import resolve_data_agent_item
from ._service_export import ServiceExportError, build_service_client
from ._target import target_from_args

ENUMERATION_LIMIT = 5
_UNSAFE = re.compile(r"[^\w.\- ]")


def _safe(name: str) -> str:
    return _UNSAFE.sub("_", name).strip().lstrip(".") or "item"


def _placeholder(output_dir: Path, workspace_id: str, item_name: str) -> Path:
    base = output_dir / "data_agent" / _safe(workspace_id) / "_unpaired"
    artifact = base / f"{item_name}.DataAgent"
    artifact.mkdir(parents=True, exist_ok=True)
    return artifact


def discover_data_agent_artifacts(discover, args, glob: str, output_dir: Path) -> list[Path]:
    """Discover local `.DataAgent` folders and pair them with the live scope."""
    discovered = discover(Path(args.artifact_dir), glob, target_from_args(args), output_dir=output_dir)
    if getattr(args, "mode", "repo") == "service":
        return paired_service_artifacts(args, output_dir, discovered)
    return discovered


def paired_service_artifacts(args, output_dir: Path, local_artifacts: list[Path]) -> list[Path]:
    """Return local or placeholder artifacts for the deployed agents in scope."""
    by_name = {artifact.stem: artifact for artifact in local_artifacts}
    target = target_from_args(args)
    client = build_service_client(args)
    workspace_id = getattr(args, "workspace_id", "")
    if target is not None and target.name:
        item = resolve_data_agent_item(client, workspace_id, target.name)
        return [by_name.get(item.display_name, _placeholder(output_dir, workspace_id, item.display_name))]
    items = client.list_items(workspace_id, "DataAgent")
    if len(items) > ENUMERATION_LIMIT and not getattr(args, "all_items", False):
        raise ServiceExportError(
            f"data_agent: {len(items)} DataAgent items in the workspace exceed the "
            f"{ENUMERATION_LIMIT}-agent limit; pass --all to proceed",
            2,
        )
    return [
        by_name.get(item.get("displayName", ""), _placeholder(output_dir, workspace_id, item.get("displayName", "")))
        for item in items
    ]
