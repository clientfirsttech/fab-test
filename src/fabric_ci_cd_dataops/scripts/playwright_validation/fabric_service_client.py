"""Service client implementation using Azure Identity service principal auth.

Calls the Power BI and Fabric REST APIs directly with a service principal so
it works locally and in GitHub Actions. This avoids the ``semantic-link-labs``
package, which imports ``notebookutils`` and therefore only runs inside
Microsoft Fabric notebooks.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import _api_root_for, _fabric_api_root_for
from .resolver import ServiceClient, ServiceResolutionError

logger = logging.getLogger(__name__)


class FabricServiceClientError(Exception):
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
class ServicePrincipalCredentials:
    """Credentials for service-principal authentication."""

    tenant_id: str
    client_id: str
    client_secret: str
    cloud: str = "public"


def _authenticate_service_principal(
    credentials: ServicePrincipalCredentials,
) -> str:
    """Acquire an access token for the Power BI / Fabric REST API.

    Uses Azure Identity's ClientSecretCredential to acquire an access token
    for the Power BI / Fabric REST APIs.
    """
    try:
        from azure.identity import (
            ClientSecretCredential,  # type: ignore[import-untyped]
        )
    except ImportError as exc:
        raise FabricServiceClientError(
            "azure-identity is required for service-principal authentication."
        ) from exc

    resource = "https://analysis.windows.net/powerbi/api"
    credential = ClientSecretCredential(
        tenant_id=credentials.tenant_id,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
    )
    token = credential.get_token(f"{resource}/.default")
    return token.token


class FabricServiceClient(ServiceClient):
    """Client backed by Azure Identity auth and direct Fabric REST calls.

    Uses a service principal (``ClientSecretCredential``) to acquire tokens
    and calls the Power BI and Fabric REST APIs directly. This works locally
    and in GitHub Actions, unlike ``semantic-link-labs``, which requires the
    ``notebookutils`` module available only inside Microsoft Fabric notebooks.

    Implements the ``ServiceClient`` protocol so it can be dropped into the
    existing resolver and impact modules without changes to their logic.
    """

    def __init__(
        self,
        credentials: ServicePrincipalCredentials,
        *,
        timeout_seconds: int = 30,
    ) -> None:
        self._credentials = credentials
        self._timeout = timeout_seconds
        self._access_token = _authenticate_service_principal(credentials)
        self._api_root = _api_root_for(credentials.cloud)
        self._fabric_api_root = _fabric_api_root_for(credentials.cloud)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    def _rest_request(
        self,
        method: str,
        path: str,
        *,
        api_root: str = "",
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{api_root or self._api_root}{path}"
        response = requests.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            raise FabricServiceClientError(
                f"Fabric REST API error (HTTP {response.status_code}): {url}",
                status_code=response.status_code,
                body=response.text,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise FabricServiceClientError(
                f"Non-JSON response from Fabric REST API: {url}",
                status_code=response.status_code,
                body=response.text,
            ) from exc

    def list_items(
        self,
        workspace_id: str,
        item_type: str,
    ) -> list[dict[str, Any]]:
        """Return items in the Fabric workspace filtered by type."""
        data = self._rest_request(
            "GET",
            f"/v1/workspaces/{workspace_id}/items",
            api_root=self._fabric_api_root,
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

    def get_dependent_reports(
        self,
        workspace_id: str,
        semantic_model_id: str,
    ) -> list[dict[str, Any]]:
        """Return reports that depend on the given semantic model.

        Uses the Power BI ``dependents`` API first; Fabric workspaces often
        return 404 from that endpoint, so we fall back to enumerating reports
        in the workspace and matching each report's ``datasetId`` to the
        semantic model ID.
        """
        try:
            data = self._rest_request(
                "GET",
                (
                    f"/v1.0/myorg/groups/{workspace_id}/datasets/"
                    f"{semantic_model_id}/dependents"
                ),
            )
            return [
                {
                    "id": dep.get("id", ""),
                    "displayName": dep.get("name", ""),
                    "type": "Report",
                    "workspaceId": dep.get("groupId", workspace_id),
                }
                for dep in data.get("value", [])
            ]
        except FabricServiceClientError as exc:
            if exc.status_code != 404:
                raise

        # Fallback: Fabric workspaces do not expose the dependents API for
        # semantic models, but the reports endpoint lists each report's
        # datasetId, allowing us to derive dependents locally.
        reports = self._rest_request(
            "GET",
            f"/v1.0/myorg/groups/{workspace_id}/reports",
        )
        return [
            {
                "id": report.get("id", ""),
                "displayName": report.get("name", ""),
                "type": "Report",
                "workspaceId": workspace_id,
            }
            for report in reports.get("value", [])
            if report.get("datasetId") == semantic_model_id
        ]


def build_fabric_service_client(
    *,
    tenant_id: str = "",
    client_id: str = "",
    client_secret: str = "",
    cloud: str = "public",
    env_file: Path | str | None = None,
) -> FabricServiceClient:
    """Build a ``FabricServiceClient`` from explicit values or environment.

    Priority:
    1. Explicit arguments
    2. Environment variables (FABRIC_TENANT_ID, FABRIC_CLIENT_ID, ...)
    3. Optional .env file parsed without mutating ``os.environ``
    """
    from .config import _parse_env_file

    env_path = None
    if env_file is not None:
        env_path = Path(env_file).resolve()
        env_values = _parse_env_file(env_path)
    else:
        env_values = {}

    def _get(name: str, explicit: str) -> str:
        if explicit:
            return explicit
        env_value = os.getenv(name, "")
        if env_value:
            return env_value
        if env_path is not None:
            return env_values.get(name, "")
        return ""

    tenant_id = _get("FABRIC_TENANT_ID", tenant_id)
    client_id = _get("FABRIC_CLIENT_ID", client_id) or _get(
        "FABRIC_SERVICE_PRINCIPAL_ID", ""
    )
    client_secret = _get("FABRIC_CLIENT_SECRET", client_secret) or _get(
        "FABRIC_SERVICE_PRINCIPAL_SECRET", ""
    )

    missing = [
        name
        for name, value in {
            "FABRIC_TENANT_ID": tenant_id,
            "FABRIC_CLIENT_ID / FABRIC_SERVICE_PRINCIPAL_ID": client_id,
            "FABRIC_CLIENT_SECRET / FABRIC_SERVICE_PRINCIPAL_SECRET": client_secret,
        }.items()
        if not value
    ]
    if missing:
        raise ServiceResolutionError(
            "Missing Fabric service principal credentials: "
            f"{', '.join(missing)}. "
            "Provide them via arguments, environment, or --env-file."
        )

    credentials = ServicePrincipalCredentials(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        cloud=cloud,
    )
    return FabricServiceClient(credentials)
