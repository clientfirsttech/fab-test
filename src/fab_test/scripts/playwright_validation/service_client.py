"""Fallback service client implementations for Fabric item and dependency lookups.

Provides a thin abstraction over the Fabric REST API so resolver logic stays
testable without live service access.
"""

from __future__ import annotations

import base64
import json
import re
import time
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
    """Base64-decode and JSON-parse a ``getDefinition`` part payload.

    PBIR JSON parts (bookmark files included) are frequently written with a
    UTF-8 BOM -- see the same fix in ``invoke_pbir_inspector.py``. Plain
    ``.decode("utf-8")`` leaves the BOM in the string and ``json.loads``
    raises, which this function swallows and returns ``None`` for -- so a
    BOM-prefixed bookmark silently vanished from discovery with no warning
    logged anywhere. ``utf-8-sig`` strips the BOM before ``json.loads`` sees
    it, matching the non-BOM case exactly.
    """
    try:
        decoded = base64.b64decode(payload).decode("utf-8-sig")
        return json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


_VIRTUAL_SERVER_DATASET = re.compile(
    r"sobe_wowvirtualserver-([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


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


def _decode_report_json_bookmarks(payload: str) -> list[dict[str, str]]:
    """Parse bookmarks out of a legacy ``report.json`` definition part.

    A report that has never been converted to the PBIR folder format ships
    as a single ``report.json`` whose ``config`` -- usually an embedded JSON
    *string*, occasionally an object -- carries the same ``bookmarks`` array
    ``definition/bookmarks.json`` holds in the flat shape. Every report in a
    classic workspace looks like this, so without this path bookmark
    discovery returns nothing and the whole bookmark dimension silently
    drops out of the test matrix.
    """
    data = _decode_payload(payload)
    if not data:
        return []
    config = data.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            return []
    if not isinstance(config, dict):
        return []
    return [
        bookmark
        for entry in config.get("bookmarks", [])
        for bookmark in _flatten_bookmark_entry(entry)
    ]


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
        if response.status_code == 202:
            return self._poll_long_running_operation(response)
        try:
            return response.json()
        except ValueError as exc:
            raise ServiceClientError(
                f"Non-JSON response from Fabric REST API: {url}",
                status_code=response.status_code,
                body=response.text,
            ) from exc

    def _poll_long_running_operation(
        self, initial_response: requests.Response
    ) -> dict[str, Any]:
        """Poll a Fabric long-running operation (HTTP 202) to completion.

        Fabric's ``getDefinition`` endpoints (reports and semantic models
        alike) never return the definition inline -- a 202 with a
        ``Location`` header and an empty body is the *only* response, with
        ``Retry-After`` naming the poll interval. Without this, ``_request``
        handed callers ``None`` for every getDefinition call: silently
        emptying bookmark discovery (masked because ``get_report_bookmarks``
        only catches 404s) and crashing ``get_semantic_model_roles`` outright
        on ``None.get(...)``. Once the operation's own status reaches
        ``Succeeded``, the actual payload lives at ``{operation}/result`` --
        a second fetch, per the Fabric LRO contract.
        """
        operation_url = initial_response.headers.get("Location")
        if not operation_url:
            raise ServiceClientError(
                "Long-running operation response had no Location header",
                status_code=initial_response.status_code,
                body=initial_response.text,
            )
        headers = _api_headers(self._token)
        retry_after = float(initial_response.headers.get("Retry-After", "1"))
        deadline = time.monotonic() + max(self._timeout * 4, 60)

        while True:
            time.sleep(retry_after)
            status_response = requests.get(
                operation_url, headers=headers, timeout=self._timeout
            )
            if status_response.status_code >= 400:
                raise ServiceClientError(
                    "Long-running operation status check failed "
                    f"(HTTP {status_response.status_code}): {operation_url}",
                    status_code=status_response.status_code,
                    body=status_response.text,
                )
            status_data = status_response.json()
            status = status_data.get("status", "")
            if status == "Succeeded":
                break
            if status == "Failed":
                raise ServiceClientError(
                    f"Long-running operation failed: {status_data.get('error')}",
                    status_code=status_response.status_code,
                    body=status_response.text,
                )
            if time.monotonic() > deadline:
                raise ServiceClientError(
                    f"Long-running operation timed out: {operation_url}"
                )
            retry_after = float(
                status_response.headers.get("Retry-After", retry_after)
            )

        result_response = requests.get(
            f"{operation_url}/result", headers=headers, timeout=self._timeout
        )
        if result_response.status_code >= 400:
            raise ServiceClientError(
                "Fetching long-running operation result failed "
                f"(HTTP {result_response.status_code}): {operation_url}/result",
                status_code=result_response.status_code,
                body=result_response.text,
            )
        try:
            return result_response.json()
        except ValueError as exc:
            raise ServiceClientError(
                f"Non-JSON result from long-running operation: {operation_url}/result",
                status_code=result_response.status_code,
                body=result_response.text,
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
        ``*.bookmark.json`` file per bookmark, the PBIR shape), a flat
        ``definition/bookmarks.json`` for older exports, and the bookmarks
        embedded in a legacy ``report.json``'s ``config`` -- the shape every
        report in a classic (non-PBIR) workspace still has. ``page_id`` comes
        from each bookmark's ``explorationState.activeSection`` so a
        bookmark can be paired with the one page it belongs to instead of
        every page in the report. Falls back to an empty list when the
        definition or no bookmark parts are found.

        Uses the Fabric REST API's item-based ``getDefinition`` (same root
        and path shape as ``get_semantic_model_roles`` below), not the
        legacy Power BI ``/v1.0/myorg/groups/...`` surface -- that surface
        has no ``getDefinition`` route for reports and 404s outright.
        """
        try:
            data = self._request(
                "POST",
                f"/v1/workspaces/{workspace_id}/reports/{report_id}/getDefinition",
                api_root=_fabric_api_root_for(self._token.cloud),
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
            elif path == "report.json":
                bookmarks.extend(
                    _decode_report_json_bookmarks(part.get("payload", ""))
                )
        return bookmarks

    def get_report_dataset_ids(self, workspace_id: str, report_id: str) -> list[str]:
        """Return the Power BI datasets a (paginated) report's data sources query.

        A paginated report deployed with no local ``.rdl`` has nowhere else
        its dataset is recorded -- the report-metadata lookup returns no
        ``datasetId`` for one -- and ``GenerateToken`` refuses a paginated
        token without it ("At least one dataset is required"). Its
        ``datasources`` name each Power BI dataset as the catalog of a
        ``sobe_wowvirtualserver-<id>`` connection, the same shape a local
        ``.rdl``'s ``ConnectString`` carries.
        """
        data = self._request(
            "GET", f"/v1.0/myorg/groups/{workspace_id}/reports/{report_id}/datasources"
        )
        dataset_ids: list[str] = []
        for source in data.get("value", []):
            database = source.get("connectionDetails", {}).get("database", "")
            match = _VIRTUAL_SERVER_DATASET.fullmatch(database)
            if match and match.group(1) not in dataset_ids:
                dataset_ids.append(match.group(1))
        return dataset_ids

    def get_item_definition(
        self, workspace_id: str, item_id: str, *, definition_format: str = ""
    ) -> list[dict[str, str]]:
        """Return an item's definition parts via Fabric ``getDefinition``.

        The export seam read-only test inputs are materialized from
        (Service Targeting epic). Each part is ``{"path", "payload"}`` with a
        base64 payload. ``definition_format`` selects ``TMDL`` for a semantic
        model or ``PBIR`` for a report.
        """
        data = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/items/{item_id}/getDefinition",
            api_root=_fabric_api_root_for(self._token.cloud),
            params={"format": definition_format} if definition_format else None,
        )
        return [
            {"path": part.get("path", ""), "payload": part.get("payload", "")}
            for part in data.get("definition", {}).get("parts", [])
        ]

    def get_paginated_report_definition(self, workspace_id: str, report_id: str) -> str:
        """Return a deployed paginated report's ``.rdl`` text, or ``""``.

        The definition that actually renders -- and, for a report that
        exists nowhere locally, the only place its declared parameters and
        their valid-values queries can be read from.
        """
        data = self._request(
            "POST",
            f"/v1/workspaces/{workspace_id}/items/{report_id}/getDefinition",
            api_root=_fabric_api_root_for(self._token.cloud),
        )
        for part in data.get("definition", {}).get("parts", []):
            if part.get("path", "").lower().endswith(".rdl"):
                try:
                    return base64.b64decode(part.get("payload", "")).decode("utf-8-sig")
                except (ValueError, UnicodeDecodeError):
                    return ""
        return ""

    def execute_dax_query(
        self, workspace_id: str, dataset_id: str, query: str
    ) -> list[dict[str, Any]]:
        """Run one DAX query against a dataset and return its result rows.

        Needs the tenant's "Dataset Execute Queries REST API" setting on for
        the service principal; a caller treats a failure as "no values
        known", not as a reason the run cannot continue.
        """
        data = self._request(
            "POST",
            f"/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}/executeQueries",
            json_payload={"queries": [{"query": query}]},
        )
        results = data.get("results") or [{}]
        tables = results[0].get("tables") or [{}]
        return list(tables[0].get("rows") or [])

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
        syntax. Falls back to a live ``INFO.ROLES()`` DAX query over the
        model's XMLA endpoint (``_discover_roles_via_xmla``) when that finds
        nothing -- a 404 (no PBIP/Git-integration-enabled definition to
        download) or an empty parts list are the same fact: this path never
        found a role, not that the model has none.
        """
        try:
            data = self._request(
                "POST",
                f"/v1/workspaces/{workspace_id}/semanticModels/"
                f"{semantic_model_id}/getDefinition",
                api_root=_fabric_api_root_for(self._token.cloud),
            )
        except ServiceClientError as exc:
            if exc.status_code != 404:
                raise
            data = None

        roles: list[str] = []
        if data is not None:
            for part in data.get("definition", {}).get("parts", []):
                path = part.get("path", "")
                if path.startswith("definition/roles/") and path.endswith(".tmdl"):
                    roles.append(path.rsplit("/", 1)[-1][: -len(".tmdl")])

        if roles:
            return roles
        return self._discover_roles_via_xmla(workspace_id, semantic_model_id)

    def get_workspace_name(self, workspace_id: str) -> str:
        """Return a workspace's display name from its GUID.

        The XMLA endpoint addresses a workspace by name
        (``powerbi://.../v1.0/myorg/<WorkspaceName>``), not GUID.
        """
        data = self._request("GET", f"/v1.0/myorg/groups/{workspace_id}")
        return str(data.get("name", ""))

    def get_dataset_name(self, workspace_id: str, dataset_id: str) -> str:
        """Return a dataset's display name from its GUID.

        The XMLA endpoint's ``Initial Catalog`` is the dataset's display
        name, not GUID.
        """
        data = self._request(
            "GET", f"/v1.0/myorg/groups/{workspace_id}/datasets/{dataset_id}"
        )
        return str(data.get("name", ""))

    def _discover_roles_via_xmla(
        self, workspace_id: str, semantic_model_id: str
    ) -> list[str]:
        """Fall back to a live ``INFO.ROLES()`` DAX query when the TMDL-based
        lookup above finds nothing -- the case for a semantic model that
        isn't PBIP/Git-integration-enabled, where ``getDefinition`` 404s and
        there is no role-file part path to read at all.

        The Power BI REST ``executeQueries`` API cannot run this query --
        Microsoft's own docs state plainly that ``INFO`` functions aren't
        supported there -- so this goes over the model's real XMLA endpoint
        via ADOMD.NET (``xmla_roles``) instead, exactly as a live query
        against the model would (e.g. from DAX query view).

        Raises ``ServiceClientError`` (matching the TMDL path's own failure
        shape) when the fallback itself can't run -- name resolution failing
        or ADOMD.NET/XMLA unavailable -- so "couldn't check" is never
        silently reported the same as "checked, found none."
        """
        from .xmla_roles import XmlaQueryError, execute_dax_query

        try:
            workspace_name = self.get_workspace_name(workspace_id)
            dataset_name = self.get_dataset_name(workspace_id, semantic_model_id)
        except ServiceClientError as exc:
            raise ServiceClientError(
                "Could not resolve workspace/dataset names for XMLA role "
                f"discovery: {exc}",
                status_code=exc.status_code,
                body=exc.body,
            ) from exc

        api_root = _api_root_for(self._token.cloud).replace("https://", "powerbi://")
        server = f"{api_root}/v1.0/myorg/{workspace_name}"
        try:
            rows = execute_dax_query(
                server,
                dataset_name,
                self._token.access_token,
                'EVALUATE SELECTCOLUMNS(INFO.ROLES(), "RoleName", [Name])',
            )
        except XmlaQueryError as exc:
            raise ServiceClientError(f"XMLA role discovery failed: {exc}") from exc

        return [str(row["RoleName"]) for row in rows if row.get("RoleName")]

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
