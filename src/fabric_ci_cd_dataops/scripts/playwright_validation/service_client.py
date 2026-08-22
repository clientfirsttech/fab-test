"""Fallback service client implementations for Fabric item and dependency lookups.

Provides a thin abstraction over the Fabric REST API so resolver logic stays
testable without live service access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .config import _api_root_for


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
        params: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a Fabric REST API request and return the JSON body."""
        api_root = _api_root_for(self._token.cloud)
        url = f"{api_root}{path}"
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
        """Return bookmarks from the report's PBIP-style definition.

        Downloads the report definition and parses ``definition/bookmarks.json``.
        Falls back to an empty list when the definition or bookmarks file is
        unavailable.
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

        for part in data.get("definition", {}).get("parts", []):
            if part.get("path") == "definition/bookmarks.json":
                import base64
                import json

                payload = part.get("payload", "")
                try:
                    decoded = base64.b64decode(payload).decode("utf-8")
                    bookmarks = json.loads(decoded)
                except (ValueError, UnicodeDecodeError):
                    return []
                return [
                    {
                        "bookmark_id": bookmark.get("name", ""),
                        "bookmark_name": bookmark.get(
                            "displayName", bookmark.get("name", "")
                        ),
                    }
                    for bookmark in bookmarks.get("bookmarks", [])
                ]
        return []

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
