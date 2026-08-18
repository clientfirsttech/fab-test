"""Contract tests for the Azure Identity-backed service client."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client import (
    FabricServiceClient,
    FabricServiceClientError,
    ServicePrincipalCredentials,
    _authenticate_service_principal,
    build_fabric_service_client,
)
from fabric_ci_cd_dataops.scripts.playwright_validation.resolver import ServiceResolutionError


@pytest.fixture
def credentials() -> ServicePrincipalCredentials:
    """Return deterministic service principal credentials."""
    return ServicePrincipalCredentials(
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret-789",
    )


@pytest.fixture
def client(credentials: ServicePrincipalCredentials) -> FabricServiceClient:
    """Return a FabricServiceClient with mocked auth."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client._authenticate_service_principal",
        return_value="fake-token",
    ):
        return FabricServiceClient(credentials)


def test_authenticate_service_principal_uses_azure_identity() -> None:
    """Given valid credentials, should return an access token."""
    mock_credential = MagicMock()
    mock_credential.get_token.return_value.token = "token-from-azure"

    with patch(
        "azure.identity.ClientSecretCredential",
        return_value=mock_credential,
    ):
        token = _authenticate_service_principal(
            ServicePrincipalCredentials(
                tenant_id="t",
                client_id="c",
                client_secret="s",
            )
        )

    assert token == "token-from-azure"
    mock_credential.get_token.assert_called_once()


def test_build_client_fails_without_credentials() -> None:
    """Given no credentials, should fail with actionable guidance."""
    with pytest.raises(ServiceResolutionError) as exc_info:
        build_fabric_service_client(
            tenant_id="",
            client_id="",
            client_secret="",
        )
    assert "Missing Fabric service principal credentials" in str(exc_info.value)


def test_build_client_reads_env_file(tmp_path: Path) -> None:
    """Given credentials in an env file, should build a client."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "FABRIC_TENANT_ID=env-tenant\n"
        "FABRIC_CLIENT_ID=env-client\n"
        "FABRIC_CLIENT_SECRET=env-secret\n",
        encoding="utf-8",
    )

    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client._authenticate_service_principal",
        return_value="token",
    ):
        client = build_fabric_service_client(env_file=env_file)

    assert client._credentials.tenant_id == "env-tenant"
    assert client._credentials.client_id == "env-client"
    assert client._credentials.client_secret == "env-secret"


def test_list_items_uses_fabric_api(
    client: FabricServiceClient,
) -> None:
    """Given a Fabric REST items response, should return normalized items."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client.requests.request"
    ) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [
                {
                    "id": "item-1",
                    "displayName": "Sales Report",
                    "type": "Report",
                },
                {
                    "id": "item-2",
                    "displayName": "Sales Model",
                    "type": "SemanticModel",
                },
            ]
        }
        mock_request.return_value = mock_response

        items = client.list_items("ws-1", "Report")

    assert len(items) == 1
    assert items[0]["id"] == "item-1"
    assert items[0]["displayName"] == "Sales Report"
    assert items[0]["type"] == "Report"
    assert items[0]["workspaceId"] == "ws-1"
    call_args = mock_request.call_args
    assert call_args is not None
    assert "api.fabric.microsoft.com" in call_args.args[1]


def test_get_dependent_reports_normalizes_rest_response(
    client: FabricServiceClient,
) -> None:
    """Given a dependents REST response, should return normalized reports."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client.requests.request"
    ) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [
                {
                    "id": "rpt-1",
                    "name": "Sales Report",
                    "groupId": "ws-1",
                },
                {
                    "id": "rpt-2",
                    "name": "Marketing Report",
                    "groupId": "ws-2",
                },
            ]
        }
        mock_request.return_value = mock_response

        reports = client.get_dependent_reports("ws-1", "sm-1")

    assert len(reports) == 2
    assert reports[0]["id"] == "rpt-1"
    assert reports[0]["workspaceId"] == "ws-1"
    assert reports[1]["workspaceId"] == "ws-2"


def test_get_dependent_reports_falls_back_to_reports_on_404(
    client: FabricServiceClient,
) -> None:
    """Given a 404 from dependents API, should derive dependents from reports."""
    responses = iter([
        {"status_code": 404, "text": "Not found", "json": {}},
        {
            "status_code": 200,
            "text": "",
            "json": {
                "value": [
                    {
                        "id": "rpt-1",
                        "name": "Sales Report",
                        "datasetId": "sm-1",
                    },
                    {
                        "id": "rpt-2",
                        "name": "Other Report",
                        "datasetId": "sm-2",
                    },
                ]
            },
        },
    ])

    def _fake_request(*_args: object, **_kwargs: object) -> MagicMock:
        resp = next(responses)
        mock_response = MagicMock()
        mock_response.status_code = resp["status_code"]
        mock_response.text = resp["text"]
        mock_response.json.return_value = resp["json"]
        return mock_response

    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client.requests.request",
        side_effect=_fake_request,
    ):
        reports = client.get_dependent_reports("ws-1", "sm-1")

    assert len(reports) == 1
    assert reports[0]["id"] == "rpt-1"
    assert reports[0]["displayName"] == "Sales Report"
    assert reports[0]["workspaceId"] == "ws-1"


def test_get_dependent_reports_returns_empty_when_fallback_has_no_matches(
    client: FabricServiceClient,
) -> None:
    """Given no reports reference the semantic model, should return empty."""
    responses = iter([
        {"status_code": 404, "text": "Not found", "json": {}},
        {
            "status_code": 200,
            "text": "",
            "json": {
                "value": [
                    {
                        "id": "rpt-2",
                        "name": "Other Report",
                        "datasetId": "sm-2",
                    },
                ]
            },
        },
    ])

    def _fake_request(*_args: object, **_kwargs: object) -> MagicMock:
        resp = next(responses)
        mock_response = MagicMock()
        mock_response.status_code = resp["status_code"]
        mock_response.text = resp["text"]
        mock_response.json.return_value = resp["json"]
        return mock_response

    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client.requests.request",
        side_effect=_fake_request,
    ):
        reports = client.get_dependent_reports("ws-1", "sm-1")

    assert reports == []


def test_get_dependent_reports_raises_on_other_errors(
    client: FabricServiceClient,
) -> None:
    """Given a non-404 REST error, should raise FabricServiceClientError."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client.requests.request"
    ) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error"
        mock_request.return_value = mock_response

        with pytest.raises(FabricServiceClientError) as exc_info:
            client.get_dependent_reports("ws-1", "sm-1")

    assert exc_info.value.status_code == 500


def test_rest_request_raises_on_non_json(
    client: FabricServiceClient,
) -> None:
    """Given a non-JSON success response, should raise FabricServiceClientError."""
    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.fabric_service_client.requests.request"
    ) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not json"
        mock_response.json.side_effect = ValueError("bad json")
        mock_request.return_value = mock_response

        with pytest.raises(FabricServiceClientError) as exc_info:
            client._rest_request("GET", "/test")

    assert "Non-JSON response" in str(exc_info.value)
