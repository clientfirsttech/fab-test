"""Contract tests for the Azure Identity-backed service client."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts.playwright_validation.fabric_service_client import (
    FabricServiceClient,
    FabricServiceClientError,
    ServicePrincipalCredentials,
    _authenticate_ambient,
    _authenticate_service_principal,
    build_fabric_service_client,
    credential_failure_detail,
)
from fab_test.scripts.playwright_validation.resolver import ServiceResolutionError


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
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_service_principal",
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


def test_build_client_fails_without_credentials(monkeypatch, tmp_path) -> None:
    """Given no credentials and no usable ambient credential, should fail."""
    for var in (
        "FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
        "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(tmp_path / "absent.env"))
    with patch(
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_ambient",
        side_effect=FabricServiceClientError("no ambient credential"),
    ), pytest.raises(ServiceResolutionError) as exc_info:
        build_fabric_service_client(
            tenant_id="",
            client_id="",
            client_secret="",
        )
    message = str(exc_info.value)
    assert message.startswith("not signed in to Fabric. Run `az login`")
    assert "FABRIC_TENANT_ID" in message
    # The search order is -v detail, not part of the one-line error.
    assert "Tried" not in message
    assert "DefaultAzureCredential" not in message


def _ambient_failure() -> ServiceResolutionError:
    """The error build_fabric_service_client raises after a failed ambient sign-in."""
    sdk = RuntimeError("DefaultAzureCredential failed to retrieve a token.\nAzureCliCredential: run az login")
    wrapped = FabricServiceClientError("no ambient credential")
    wrapped.__cause__ = sdk
    error = ServiceResolutionError("not signed in to Fabric.")
    error.__cause__ = wrapped
    return error


def test_credential_failure_detail_is_empty_at_default_verbosity() -> None:
    assert credential_failure_detail(_ambient_failure(), 0) == []


def test_credential_failure_detail_names_the_search_at_v() -> None:
    lines = credential_failure_detail(_ambient_failure(), 1)
    assert len(lines) == 1
    assert lines[0].startswith("tried: FABRIC_*")


def test_credential_failure_detail_adds_the_sdk_report_at_vv() -> None:
    lines = credential_failure_detail(_ambient_failure(), 2)
    assert "AzureCliCredential: run az login" in lines


def test_credential_failure_detail_ignores_other_resolution_errors() -> None:
    """A partial service principal is not an ambient failure; no search detail."""
    assert credential_failure_detail(ServiceResolutionError("Missing ..."), 2) == []


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
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_service_principal",
        return_value="token",
    ):
        client = build_fabric_service_client(env_file=env_file)

    assert client._credentials.tenant_id == "env-tenant"
    assert client._credentials.client_id == "env-client"
    assert client._credentials.client_secret == "env-secret"


def test_build_client_without_an_env_file_searches_like_the_credential_probe(
    tmp_path: Path, monkeypatch
) -> None:
    """Given no env_file, should read the same default .env that probe_credentials
    reports from, not skip it and authenticate as the ambient identity -- which
    made `auth status` verify one identity and test reachability as another."""
    for var in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "FABRIC_TENANT_ID=env-tenant\nFABRIC_CLIENT_ID=env-client\nFABRIC_CLIENT_SECRET=env-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(env_file))

    with patch(
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_service_principal",
        return_value="token",
    ), patch(
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_ambient",
        side_effect=AssertionError("must not fall back to ambient when the default .env has a service principal"),
    ):
        client = build_fabric_service_client()

    assert client._credentials.client_id == "env-client"


def test_list_items_uses_fabric_api(
    client: FabricServiceClient,
) -> None:
    """Given a Fabric REST items response, should return normalized items."""
    with patch(
        "fab_test.scripts.playwright_validation.fabric_service_client.requests.request"
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
        "fab_test.scripts.playwright_validation.fabric_service_client.requests.request"
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
        "fab_test.scripts.playwright_validation.fabric_service_client.requests.request",
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
        "fab_test.scripts.playwright_validation.fabric_service_client.requests.request",
        side_effect=_fake_request,
    ):
        reports = client.get_dependent_reports("ws-1", "sm-1")

    assert reports == []


def test_get_dependent_reports_raises_on_other_errors(
    client: FabricServiceClient,
) -> None:
    """Given a non-404 REST error, should raise FabricServiceClientError."""
    with patch(
        "fab_test.scripts.playwright_validation.fabric_service_client.requests.request"
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
        "fab_test.scripts.playwright_validation.fabric_service_client.requests.request"
    ) as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not json"
        mock_response.json.side_effect = ValueError("bad json")
        mock_request.return_value = mock_response

        with pytest.raises(FabricServiceClientError) as exc_info:
            client._rest_request("GET", "/test")

    assert "Non-JSON response" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# Ambient (DefaultAzureCredential) fallback (Config Consolidation §9)
# --------------------------------------------------------------------------- #


def _clear_service_principal_env(monkeypatch):
    for var in (
        "FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
        "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    # The default .env search would otherwise find a developer's real
    # .fab-test/.env and supply the very variables this helper clears.
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(Path(__file__).parent / "no-such.env"))


def test_authenticate_ambient_uses_default_azure_credential() -> None:
    """Given azure-identity is available, uses DefaultAzureCredential."""
    mock_credential = MagicMock()
    mock_credential.get_token.return_value.token = "ambient-token"

    with patch("azure.identity.DefaultAzureCredential", return_value=mock_credential):
        token = _authenticate_ambient()

    assert token == "ambient-token"
    mock_credential.get_token.assert_called_once()


def test_authenticate_ambient_wraps_client_authentication_error() -> None:
    """A failed ambient credential chain raises FabricServiceClientError, not the raw azure-core error."""
    from azure.core.exceptions import ClientAuthenticationError

    mock_credential = MagicMock()
    mock_credential.get_token.side_effect = ClientAuthenticationError("no credential available")

    with patch("azure.identity.DefaultAzureCredential", return_value=mock_credential), pytest.raises(
        FabricServiceClientError
    ):
        _authenticate_ambient()


def test_authenticate_ambient_silences_the_sdk_warning_and_restores_the_level() -> None:
    """The chain's nine-credential WARNING must not reach stderr; the level is put back after."""
    import logging

    from azure.core.exceptions import ClientAuthenticationError

    identity_logger = logging.getLogger("azure.identity")
    seen: list[int] = []

    def _fail(*_args, **_kwargs):
        seen.append(logging.getLogger("azure.identity._credentials.chained").getEffectiveLevel())
        raise ClientAuthenticationError("no credential available")

    mock_credential = MagicMock()
    mock_credential.get_token.side_effect = _fail
    before = identity_logger.level

    with patch("azure.identity.DefaultAzureCredential", return_value=mock_credential), pytest.raises(
        FabricServiceClientError
    ):
        _authenticate_ambient()

    assert seen == [logging.ERROR]
    assert identity_logger.level == before


def test_build_client_falls_back_to_ambient_when_no_service_principal_vars(monkeypatch) -> None:
    """No service-principal variables set at all: DefaultAzureCredential is attempted and used."""
    _clear_service_principal_env(monkeypatch)

    with patch(
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_ambient",
        return_value="ambient-token",
    ):
        client = build_fabric_service_client(tenant_id="", client_id="", client_secret="")

    assert client.credential_source == "ambient:DefaultAzureCredential"


def test_build_client_prefers_service_principal_over_ambient(monkeypatch) -> None:
    """A fully-configured service principal is used directly -- ambient auth is never attempted."""
    _clear_service_principal_env(monkeypatch)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("_authenticate_ambient must not be called when a service principal is configured")

    with patch(
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_ambient",
        side_effect=_fail_if_called,
    ), patch(
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_service_principal",
        return_value="sp-token",
    ):
        client = build_fabric_service_client(
            tenant_id="t", client_id="c", client_secret="s"
        )

    assert client.credential_source == "service-principal"


def test_build_client_partial_service_principal_does_not_fall_back_to_ambient(monkeypatch) -> None:
    """A partially-configured service principal (a likely typo) fails outright, not silently via ambient."""
    _clear_service_principal_env(monkeypatch)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("_authenticate_ambient must not be called for a partial service principal")

    with patch(
        "fab_test.scripts.playwright_validation.fabric_service_client._authenticate_ambient",
        side_effect=_fail_if_called,
    ), pytest.raises(ServiceResolutionError) as exc_info:
        build_fabric_service_client(tenant_id="t", client_id="", client_secret="")

    assert "Missing Fabric service principal credentials" in str(exc_info.value)


def test_from_access_token_never_exposes_the_token_itself() -> None:
    """The client's public credential_source is a label, never the token value."""
    client = FabricServiceClient.from_access_token(
        "super-secret-token", credential_source="ambient:DefaultAzureCredential"
    )

    assert client.credential_source == "ambient:DefaultAzureCredential"
    assert "super-secret-token" not in repr(client)
    assert "super-secret-token" not in str(vars(client).get("credential_source", ""))
