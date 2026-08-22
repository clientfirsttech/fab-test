"""Metadata-driven resolution of Fabric environments and service items.

Resolves canonical environment labels and workspace IDs from
``environments.yml`` -- from `.fab-test/metadata/` or `.github/metadata/` --
and normalizes artifact names to deployed
item identities. Resolution is intentionally offline: callers that need service
lookups supply a client implementing the small ``ServiceClient`` protocol.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from .._metadata import MetadataNotFoundError, resolve_environments_yml


class ServiceResolutionError(Exception):
    """Raised when an environment or service item cannot be resolved."""

    def __init__(
        self,
        message: str,
        *,
        environment: str = "",
        workspace_id: str = "",
        item_type: str = "",
        candidates: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.environment = environment
        self.workspace_id = workspace_id
        self.item_type = item_type
        self.candidates = candidates or []


class WorkspaceNotFoundError(ServiceResolutionError):
    """No workspace matches the name. Exit 1: a real lookup failure."""


class AmbiguousWorkspaceError(ServiceResolutionError):
    """More than one workspace matches. Exit 2: the invocation is unusable
    as written, and passing a GUID resolves it.
    """


class ServiceClient(Protocol):
    """Minimal protocol for service-backed item/dependency lookups."""

    def list_items(
        self,
        workspace_id: str,
        item_type: str,
    ) -> list[dict[str, Any]]: ...

    def get_dependent_reports(
        self,
        workspace_id: str,
        semantic_model_id: str,
    ) -> list[dict[str, Any]]: ...

    def list_workspaces(self) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ResolvedEnvironment:
    """Canonical environment and workspace identity."""

    environment: str
    workspace_id: str


@dataclass(frozen=True)
class ResolvedItem:
    """A deployed Fabric item resolved from its artifact name."""

    workspace_id: str
    item_type: str
    item_id: str
    display_name: str
    environment: str


@dataclass(frozen=True)
class ResolvedReport:
    """A report plus its semantic-model dependency, ready for Playwright."""

    workspace_id: str
    report_id: str
    report_name: str
    semantic_model_id: str
    environment: str


def _load_environments(path: Path | None = None) -> dict[str, Any]:
    """Load and return the parsed environments.yml mapping.

    An explicit ``path`` still wins -- ``--env-path`` and the impact
    manifest both supply one. Without it the metadata layers are searched
    (Environments Metadata Layers §3); this module used to hold its own
    copy of the repo-root rule and the hardcoded `.github/metadata/` path.
    """
    if path is None:
        try:
            path = resolve_environments_yml().path
        except MetadataNotFoundError as exc:
            raise ServiceResolutionError(str(exc)) from exc
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError as exc:
        raise ServiceResolutionError(
            f"Environments metadata not found: {path}",
        ) from exc
    except yaml.YAMLError as exc:
        raise ServiceResolutionError(
            f"Invalid environments.yml: {exc}",
        ) from exc

    if not isinstance(data, dict) or "environments" not in data:
        raise ServiceResolutionError(
            "environments.yml must contain an 'environments' mapping",
        )
    return data["environments"]


def resolve_environment(
    env: str,
    *,
    env_path: Path | None = None,
    workspace_id_override: str = "",
) -> ResolvedEnvironment:
    """Resolve a canonical environment label and workspace ID.

    Args:
        env: Environment label, case-insensitive (e.g. ``dev`` or ``PROD``).
        env_path: Optional path to environments.yml.
        workspace_id_override: Optional explicit workspace ID that takes
            precedence over the metadata value while preserving the environment.

    Returns:
        ``ResolvedEnvironment`` with canonical label and workspace ID.

    Raises:
        ServiceResolutionError: If the environment is unknown or workspace ID
            is missing and no override is supplied.
    """
    environments = _load_environments(env_path)
    canonical = env.lower()

    for name, config in environments.items():
        if name.lower() == canonical:
            workspace_id = workspace_id_override or config.get("workspace_id", "")
            if not workspace_id:
                raise ServiceResolutionError(
                    f"Environment '{name}' has no workspace_id. "
                    "Set it in environments.yml or supply --workspace-id.",
                    environment=name,
                )
            return ResolvedEnvironment(
                environment=name,
                workspace_id=workspace_id,
            )

    raise ServiceResolutionError(
        f"Unknown environment '{env}'. Known environments: "
        f"{', '.join(environments)}.",
        environment=env,
    )


def _normalize_name(name: str) -> str:
    """Strip the Fabric type suffix from an artifact display name."""
    suffixes = (".SemanticModel", ".Report")
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


_GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _normalize_workspace_name(name: str) -> str:
    """Fold a workspace display name for comparison.

    Deliberately more forgiving than `_normalize_name`, which is exact:
    an item name usually arrives copied from a folder on disk, whereas a
    workspace name is typed by hand into a shell, where case and stray
    spaces are noise rather than signal.
    """
    return name.strip().casefold()


def resolve_workspace_id(client: ServiceClient, name_or_id: str) -> str:
    """Return the workspace ID for a display name, or a GUID unchanged.

    The counterpart to `resolve_item`, which already resolves an item name
    *within* a workspace: this resolves the workspace half of a
    ``Sales Dev.Workspace/Sales.SemanticModel`` target.

    A value that is already a GUID short-circuits the lookup rather than
    confirming it -- confirming would cost a round trip and turn a
    perfectly valid ID into a failure whenever the identity cannot list
    workspaces.
    """
    candidate = name_or_id.strip()
    if _GUID_PATTERN.match(candidate):
        return candidate

    workspaces = client.list_workspaces()
    normalized = _normalize_workspace_name(candidate)
    matches = [
        workspace
        for workspace in workspaces
        if _normalize_workspace_name(workspace.get("displayName", "")) == normalized
    ]

    if not matches:
        visible = [w.get("displayName", "") for w in workspaces]
        visible_note = ", ".join(visible) if visible else "none visible to this identity"
        raise WorkspaceNotFoundError(
            f"No workspace named '{candidate}'. Visible workspaces: {visible_note}.",
            candidates=visible,
        )

    if len(matches) > 1:
        ids = [w.get("id", "") for w in matches]
        raise AmbiguousWorkspaceError(
            f"Multiple workspaces are named '{candidate}': {', '.join(ids)}. "
            f"Use the ID instead of the name.",
            candidates=ids,
        )

    return matches[0]["id"]


def resolve_item(
    name: str,
    item_type: str,
    resolved_env: ResolvedEnvironment,
    client: ServiceClient,
) -> ResolvedItem:
    """Resolve a single deployed item by normalized display name and type.

    Args:
        name: Artifact or item name, with or without a Fabric type suffix.
        item_type: Fabric item type (e.g. ``Report``, ``SemanticModel``).
        resolved_env: Resolved environment containing workspace ID.
        client: Service client that lists items in the workspace.

    Returns:
        ``ResolvedItem`` for the unique matching item.

    Raises:
        ServiceResolutionError: If no item matches or multiple items match.
    """
    normalized = _normalize_name(name)
    candidates = [
        item
        for item in client.list_items(resolved_env.workspace_id, item_type)
        if _normalize_name(item.get("displayName", "")) == normalized
        or item.get("displayName", "") == name
    ]

    if not candidates:
        all_names = [
            item.get("displayName", "")
            for item in client.list_items(resolved_env.workspace_id, item_type)
        ]
        raise ServiceResolutionError(
            f"No {item_type} matching '{name}' in workspace "
            f"{resolved_env.workspace_id}.",
            environment=resolved_env.environment,
            workspace_id=resolved_env.workspace_id,
            item_type=item_type,
            candidates=all_names,
        )

    if len(candidates) > 1:
        names = [item.get("displayName", "") for item in candidates]
        raise ServiceResolutionError(
            f"Multiple {item_type} items match '{name}' in workspace "
            f"{resolved_env.workspace_id}: {', '.join(names)}.",
            environment=resolved_env.environment,
            workspace_id=resolved_env.workspace_id,
            item_type=item_type,
            candidates=names,
        )

    item = candidates[0]
    return ResolvedItem(
        workspace_id=resolved_env.workspace_id,
        item_type=item_type,
        item_id=item["id"],
        display_name=item.get("displayName", normalized),
        environment=resolved_env.environment,
    )


def resolve_report(
    name: str,
    resolved_env: ResolvedEnvironment,
    client: ServiceClient,
) -> ResolvedReport:
    """Resolve a report and infer its dataset/semantic-model dependency."""
    resolved = resolve_item(name, "Report", resolved_env, client)
    dataset_id = resolved.item_id  # Fallback when dependency API unavailable.
    return ResolvedReport(
        workspace_id=resolved.workspace_id,
        report_id=resolved.item_id,
        report_name=resolved.display_name,
        semantic_model_id=dataset_id,
        environment=resolved.environment,
    )


def resolve_semantic_model_dependents(
    name: str,
    resolved_env: ResolvedEnvironment,
    client: ServiceClient,
    *,
    allowed_workspace_ids: set[str] | None = None,
) -> list[ResolvedReport]:
    """Resolve a semantic model and return in-scope dependent reports.

    Args:
        name: Artifact or item name of the semantic model.
        resolved_env: Resolved environment containing workspace ID.
        client: Service client for item/dependency lookups.
        allowed_workspace_ids: Optional set of workspace IDs to include
            dependencies from outside the target workspace. Defaults to the
            target workspace only.

    Returns:
        List of ``ResolvedReport`` objects, one per in-scope dependent report.
    """
    resolved = resolve_item(name, "SemanticModel", resolved_env, client)
    scope = allowed_workspace_ids or {resolved_env.workspace_id}

    reports: list[ResolvedReport] = []
    for dep in client.get_dependent_reports(
        resolved_env.workspace_id,
        resolved.item_id,
    ):
        report_workspace = dep.get("workspaceId", resolved_env.workspace_id)
        if report_workspace not in scope:
            continue
        reports.append(
            ResolvedReport(
                workspace_id=report_workspace,
                report_id=dep["id"],
                report_name=dep.get("displayName", dep["id"]),
                semantic_model_id=resolved.item_id,
                environment=resolved_env.environment,
            )
        )
    return reports
