"""Contract tests for Playwright Power BI API helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.config import PlaywrightValidationConfig
from fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api import (
    PowerBiApiError,
    ReportIdentity,
    _api_root_for,
    _authority_for,
    generate_embed_token,
    get_embed_context,
    get_report_embed_url,
)


@pytest.fixture
def config() -> PlaywrightValidationConfig:
    """Return a config pointing at a hypothetical report."""
    return PlaywrightValidationConfig(
        workspace_id="ws-1",
        report_id="rpt-1",
        report_name="Report",
        dataset_id="ds-1",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=30,
        headless=True,
    )


def test_authority_for_public_cloud() -> None:
    """Public cloud resolves to the commercial Microsoft login endpoint."""
    assert _authority_for("public") == "https://login.microsoftonline.com"


def test_authority_defaults_to_public_for_unknown_cloud() -> None:
    """Unknown clouds fall back to the public authority."""
    assert _authority_for("unknown") == "https://login.microsoftonline.com"


def test_api_root_for_public_cloud() -> None:
    """Public cloud resolves to the commercial Power BI API endpoint."""
    assert _api_root_for("public") == "https://api.powerbi.com"


def test_get_report_embed_url_success() -> None:
    """A successful report fetch returns the embedUrl."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"embedUrl": "https://app.powerbi.com/embed?rpt"}

    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.get",
        return_value=mock_response,
    ):
        url = get_report_embed_url("token", "ws-1", "rpt-1")

    assert url == "https://app.powerbi.com/embed?rpt"


def test_get_report_embed_url_raises_on_missing_url() -> None:
    """A response without embedUrl raises PowerBiApiError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(PowerBiApiError),
    ):
        get_report_embed_url("token", "ws-1", "rpt-1")


def test_get_report_embed_url_raises_on_http_error() -> None:
    """Non-200 responses raise PowerBiApiError with status code."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not found"

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.get",
            return_value=mock_response,
        ),
        pytest.raises(PowerBiApiError) as exc_info,
    ):
        get_report_embed_url("token", "ws-1", "rpt-1")

    assert exc_info.value.status_code == 404


def test_generate_embed_token_success() -> None:
    """A successful token generation returns the token."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ):
        token = generate_embed_token("token", ReportIdentity("ws-1", "rpt-1", "ds-1"))

    assert token == "embed-token-1"


def test_generate_embed_token_includes_rls_identity() -> None:
    """When RLS is enabled and user_name/role are provided, identities are included."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token(
            "token",
            ReportIdentity("ws-1", "rpt-1", "ds-1"),
            use_rls=True,
            user_name="u1",
            role="Viewer",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["identities"] == [
        {"username": "u1", "roles": ["Viewer"], "datasets": ["ds-1"]}
    ]


def test_generate_embed_token_omits_identity_when_rls_disabled() -> None:
    """When RLS is disabled, identities are omitted even if user_name/role are set."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token(
            "token",
            ReportIdentity("ws-1", "rpt-1", "ds-1"),
            use_rls=False,
            user_name="u1",
            role="Viewer",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert "identities" not in payload


def test_generate_embed_token_raises_on_http_error() -> None:
    """Non-200 token generation raises PowerBiApiError."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad request"

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.post",
            return_value=mock_response,
        ),
        pytest.raises(PowerBiApiError) as exc_info,
    ):
        generate_embed_token("token", ReportIdentity("ws-1", "rpt-1", "ds-1"))

    assert exc_info.value.status_code == 400


def test_get_embed_context_returns_all_fields(
    config: PlaywrightValidationConfig,
) -> None:
    """get_embed_context aggregates access token, embed URL, and embed token."""
    mock_token_response = MagicMock()
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {
        "embedUrl": "https://app.powerbi.com/embed?rpt",
    }
    mock_generate_response = MagicMock()
    mock_generate_response.status_code = 200
    mock_generate_response.json.return_value = {"token": "embed-token"}

    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {"access_token": "access-token"}

    with (
        patch("msal.ConfidentialClientApplication", return_value=mock_app),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.get",
            return_value=mock_token_response,
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api.requests.post",
            return_value=mock_generate_response,
        ),
    ):
        context = get_embed_context(config)

    assert context.report_id == "rpt-1"
    assert context.dataset_id == "ds-1"
    assert context.embed_url == "https://app.powerbi.com/embed?rpt"
    assert context.embed_token == "embed-token"
