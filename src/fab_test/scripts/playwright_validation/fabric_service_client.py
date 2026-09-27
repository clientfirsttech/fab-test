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


def _authenticate_ambient() -> str:
    """Acquire an access token via whatever ambient Azure credential is
    available (``az login``, a managed identity, VS Code sign-in, an
    environment credential, ...), so a developer already signed in to Azure
    can skip service-principal secrets entirely.

    Raises FabricServiceClientError when azure-identity isn't installed or
    no credential in the chain succeeds -- never propagates the underlying
    azure-core exception directly, so callers only need to catch one type.
    """
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import-untyped]
    except ImportError as exc:
        raise FabricServiceClientError(
            "azure-identity is required for ambient credential authentication."
        ) from exc

    from azure.core.exceptions import ClientAuthenticationError  # type: ignore[import-untyped]

    resource = "https://analysis.windows.net/powerbi/api"
    try:
        token = DefaultAzureCredential().get_token(f"{resource}/.default")
    except ClientAuthenticationError as exc:
        raise FabricServiceClientError(
            "DefaultAzureCredential could not find a usable ambient credential."
        ) from exc
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
        self.credential_source = "service-principal"

    @classmethod
    def from_access_token(
        cls,
        access_token: str,
        *,
        cloud: str = "public",
        timeout_seconds: int = 30,
        credential_source: str = "ambient",
    ) -> FabricServiceClient:
        """Build a client from an already-acquired access token (e.g. from
        ``DefaultAzureCredential``), bypassing service-principal auth.

        ``credential_source`` is a plain label for the run manifest / logs --
        it never carries the token itself.
        """
        instance = cls.__new__(cls)
        instance._credentials = None
        instance._timeout = timeout_seconds
        instance._access_token = access_token
        instance._api_root = _api_root_for(cloud)
        instance._fabric_api_root = _fabric_api_root_for(cloud)
        instance.credential_source = credential_source
        return instance

    @property
    def access_token(self) -> str:
        """Return the already-acquired access token.

        Lets a caller that needs a second Fabric REST client (e.g. the
        pages/bookmarks/roles discovery in ``service_client.FabricRestClient``)
        reuse this client's auth instead of authenticating a second time.
        """
        return self._access_token

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

    def list_workspaces(self) -> list[dict[str, Any]]:
        """Return every workspace visible to the current identity.

        Backs `resolve_workspace_id`, so a target can name a workspace the
        way a person does rather than by GUID.
        """
        data = self._rest_request(
            "GET",
            "/v1/workspaces",
            api_root=self._fabric_api_root,
        )
        return [
            {"id": item.get("id", ""), "displayName": item.get("displayName", "")}
            for item in data.get("value", [])
        ]

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

    def get_report_dataset_id(self, workspace_id: str, report_id: str) -> str:
        """Return the semantic model (dataset) ID a report is bound to."""
        data = self._rest_request(
            "GET",
            f"/v1.0/myorg/groups/{workspace_id}/reports/{report_id}",
        )
        return str(data.get("datasetId", ""))


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
    4. Ambient Azure credential (``DefaultAzureCredential``) -- attempted
       only when *none* of the service-principal variables are set at all;
       a partially-set service principal (e.g. tenant_id but no secret) is
       treated as a mistake, not silently overridden by ambient auth.
    """
    from .config import _parse_env_file, resolve_env_file

    # The same search probe_credentials reports from, so `auth status` never
    # verifies one identity and then tests reachability as another.
    env_path = resolve_env_file(env_file)
    env_values = _parse_env_file(env_path)

    def _get(name: str, explicit: str) -> str:
        return explicit or os.getenv(name, "") or env_values.get(name, "")

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
    if not (tenant_id or client_id or client_secret):
        try:
            token = _authenticate_ambient()
        except FabricServiceClientError:
            pass
        else:
            return FabricServiceClient.from_access_token(
                token, cloud=cloud, credential_source="ambient:DefaultAzureCredential"
            )
        raise ServiceResolutionError(
            "No Fabric credentials found. Tried, in order: explicit arguments, "
            "environment variables (FABRIC_TENANT_ID/FABRIC_CLIENT_ID/FABRIC_CLIENT_SECRET "
            "or FABRIC_SERVICE_PRINCIPAL_ID/FABRIC_SERVICE_PRINCIPAL_SECRET), --env-file, "
            "and DefaultAzureCredential (az login, a managed identity, VS Code sign-in, "
            "an environment credential). Provide a service principal or sign in with "
            "`az login`."
        )

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
