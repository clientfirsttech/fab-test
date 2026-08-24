"""Fallback service client implementations for Fabric item and dependency lookups.

Provides a thin abstraction over the Fabric REST API so resolver logic stays
testable without live service access.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import requests

from .config import _api_root_for, _fabric_api_root_for


class ServiceClientError(Exception):
    """Raised when a service client operation fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(frozen=True)
class FabricToken:
    """Access token and tenant/cloud context for Fabric REST calls."""

    access_token: str
    cloud: str = "public"


def _api_headers(token: FabricToken) -> dict[str, str]:
    """Return standard Fabric REST API headers."""
    return {
        "Authorization": f"Bearer {token.access_token}",
        "Content-Type": "application/json",
    }


def _decode_payload(payload: str) -> dict[str, Any] | None:
    """Base64-decode and JSON-parse a ``getDefinition`` part payload."""
    try:
        decoded = base64.b64decode(payload).decode("utf-8")
        return json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _bookmark_page_id(bookmark: dict[str, Any]) -> str:
    """Return the page a bookmark targets from its exploration state."""
    return str(bookmark.get("explorationState", {}).get("activeSection", ""))


def _flatten_bookmark_entry(entry: dict[str, Any]) -> list[dict[str, str]]:
    """Expand one bookmark-index entry into testable bookmarks.

    A bookmark group carries no state of its own -- only its ``children``
    do -- so a group is expanded into its children rather than tested as a
    bookmark itself.
    """
    children = entry.get("children")
    if children:
        return [
            {
                "bookmark_id": child.get("name", ""),
                "bookmark_name": child.get("displayName", child.get("name", "")),
                "page_id": _bookmark_page_id(child),
            }
            for child in children
        ]
    return [
        {
            "bookmark_id": entry.get("name", ""),
            "bookmark_name": entry.get("displayName", entry.get("name", "")),
            "page_id": _bookmark_page_id(entry),
        }
    ]


def _decode_bookmark_index(payload: str) -> list[dict[str, str]]:
    """Parse the legacy flat ``definition/bookmarks.json`` shape."""
    data = _decode_payload(payload)
    if not data:
        return []
    return [
        bookmark
        for entry in data.get("bookmarks", [])
        for bookmark in _flatten_bookmark_entry(entry)
    ]


def _decode_bookmark_file(payload: str) -> dict[str, str] | None:
    """Parse one PBIR ``definition/bookmarks/<name>.bookmark.json`` part.

    A bookmark *group*'s own file lists its children rather than carrying
    exploration state itself, so it is skipped here -- each child gets its
    own ``*.bookmark.json`` part, which this function is called on
    separately.
    """
    data = _decode_payload(payload)
    if not data or data.get("children"):
        return None
    return {
        "bookmark_id": data.get("name", ""),
        "bookmark_name": data.get("displayName", data.get("name", "")),
        "page_id": _bookmark_page_id(data),
    }


class FabricRestClient:
    """Client backed by direct Fabric REST API calls.

    Lists workspace items via ``GET /v1.0/myorg/groups/{workspaceId}/items`` and
    discovers dependent reports via the Power BI dependency API.
    """

    def __init__(self, token: FabricToken, timeout_seconds: int = 30) -> None:
        self._token = token
        self._timeout = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        api_root: str = "",
        params: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a Fabric REST API request and return the JSON body.

        ``api_root`` overrides the default Power BI root for calls that
        must go through the Fabric REST API instead (e.g. semantic model
        definitions), matching ``FabricServiceClient``'s ``_rest_request``.
        """
        url = f"{api_root or _api_root_for(self._token.cloud)}{path}"
        response = requests.request(
            method,
            url,
            headers=_api_headers(self._token),
            params=params,
            json=json_payload,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            raise ServiceClientError(
                f"Fabric REST API error (HTTP {response.status_code}): {url}",
                status_code=response.status_code,
                body=response.text,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceClientError(
                f"Non-JSON response from Fabric REST API: {url}",
                status_code=response.status_code,
                body=response.text,
            ) from exc

    def list_items(
        self,
        workspace_id: str,
        item_type: str,
    ) -> list[dict[str, Any]]:
        """Return items in the workspace filtered by type."""
        data = self._request(
            "GET",
            f"/v1.0/myorg/groups/{workspace_id}/items",
        )
        items = data.get("value", [])
        return [
            {
                "id": item.get("id", ""),
                "displayName": item.get("displayName", ""),
                "type": item.get("type", ""),
                "workspaceId": workspace_id,
            }
            for item in items
            if item.get("type", "").lower() == item_type.lower()
        ]

    def get_report_pages(
        self,
        workspace_id: str,
        report_id: str,
    ) -> list[dict[str, str]]:
        """Return pages for a report via Fabric ``GetPages`` API.

        Each page is returned with ``page_id`` and ``page_name`` keys.
        """
        data = self._request(
            "GET",
            f"/v1.0/myorg/groups/{workspace_id}/reports/{report_id}/pages",
        )
        return [
            {
                "page_id": page.get("name", ""),
                "page_name": page.get("displayName", page.get("name", "")),
            }
            for page in data.get("value", [])
        ]

    def get_report_bookmarks(
        self,
        workspace_id: str,
        report_id: str,
    ) -> list[dict[str, str]]:
        """Return bookmarks from the report's PBIR-style definition, each
        tagged with the page it targets.

        Reads every bookmark part under ``definition/bookmarks/`` (one
        ``*.bookmark.json`` file per bookmark, the PBIR shape) plus a flat
        ``definition/bookmarks.json`` for older exports. ``page_id`` comes
        from each bookmark's ``explorationState.activeSection`` so a
        bookmark can be paired with the one page it belongs to instead of
        every page in the report. Falls back to an empty list when the
        definition or no bookmark parts are found.
        """
        try:
            data = self._request(
                "POST",
                f"/v1.0/myorg/groups/{workspace_id}/reports/{report_id}/getDefinition",
            )
        except ServiceClientError as exc:
            if exc.status_code == 404:
                return []
            raise

        bookmarks: list[dict[str, str]] = []
        for part in data.get("definition", {}).get("parts", []):
            path = part.get("path", "")
            if path == "definition/bookmarks.json":
                bookmarks.extend(_decode_bookmark_index(part.get("payload", "")))
            elif path.startswith("definition/bookmarks/") and path.endswith(
                ".bookmark.json"
            ):
                bookmark = _decode_bookmark_file(part.get("payload", ""))
                if bookmark:
                    bookmarks.append(bookmark)
        return bookmarks

    def get_semantic_model_roles(
        self,
        workspace_id: str,
        semantic_model_id: str,
    ) -> list[str]:
        """Return RLS/OLS role names defined on the semantic model.

        Downloads the semantic model definition over the Fabric REST API and
        derives each role's name from its ``definition/roles/<RoleName>.tmdl``
        part path -- Power BI Desktop names each role file after the role
        itself, so the path is a reliable source without parsing TMDL role
        syntax. Falls back to an empty list when the definition is
        unavailable (e.g. a legacy, non-PBIP-enabled semantic model).
        """
        try:
            data = self._request(
                "POST",
                f"/v1/workspaces/{workspace_id}/semanticModels/"
                f"{semantic_model_id}/getDefinition",
                api_root=_fabric_api_root_for(self._token.cloud),
            )
        except ServiceClientError as exc:
            if exc.status_code == 404:
                return []
            raise

        roles = []
        for part in data.get("definition", {}).get("parts", []):
            path = part.get("path", "")
            if path.startswith("definition/roles/") and path.endswith(".tmdl"):
                roles.append(path.rsplit("/", 1)[-1][: -len(".tmdl")])
        return roles

    def get_dependent_reports(
        self,
        workspace_id: str,
        semantic_model_id: str,
    ) -> list[dict[str, Any]]:
        """Return reports that depend on the given semantic model.

        Uses the Power BI ``dependents`` API for semantic models. Falls back to
        an empty list when the API returns no data so callers can decide whether
        to fail.
        """
        try:
            data = self._request(
                "GET",
                f"/v1.0/myorg/groups/{workspace_id}/datasets/{semantic_model_id}/dependents",
            )
        except ServiceClientError as exc:
            if exc.status_code == 404:
                return []
            raise

        return [
            {
                "id": item.get("id", ""),
                "displayName": item.get("name") or item.get("displayName", ""),
                "type": "Report",
                "workspaceId": item.get("workspaceId", workspace_id),
            }
            for item in data.get("value", [])
        ]
