"""Contract tests for Playwright Power BI API helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig
from fab_test.scripts.playwright_validation.power_bi_api import (
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
        "fab_test.scripts.playwright_validation.power_bi_api.requests.get",
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
            "fab_test.scripts.playwright_validation.power_bi_api.requests.get",
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
            "fab_test.scripts.playwright_validation.power_bi_api.requests.get",
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
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ):
        token = generate_embed_token("token", ReportIdentity("ws-1", "rpt-1", "ds-1"))

    assert token == "embed-token-1"


def test_generate_embed_token_target_workspaces_defaults_to_the_report_workspace() -> None:
    """With no dataset_workspace_id, targetWorkspaces names only the report's
    own workspace -- the shape verified live in the Playwright Embed Token
    Type epic, unchanged here."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token("token", ReportIdentity("ws-1", "rpt-1", "ds-1"))

    payload = mock_post.call_args.kwargs["json"]
    assert payload["targetWorkspaces"] == [{"id": "ws-1"}]


def test_generate_embed_token_names_both_workspaces_for_a_cross_workspace_dataset() -> None:
    """A dataset in a different workspace than its report -- common practice
    for a dataset shared across several reports -- must be named in
    targetWorkspaces too. Naming only the report's workspace produced a
    misleading "XMLA permissions are off" 400 for a cross-workspace RDL
    report's dataset (confirmed live) rather than the real problem, which
    GenerateToken never had enough information to name."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token(
            "token",
            ReportIdentity(
                "ws-report", "rdl-1", "ds-1", dataset_workspace_id="ws-dataset"
            ),
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["targetWorkspaces"] == [{"id": "ws-report"}, {"id": "ws-dataset"}]


def test_generate_embed_token_does_not_duplicate_a_matching_dataset_workspace() -> None:
    """dataset_workspace_id equal to the report's own workspace names it once."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token(
            "token",
            ReportIdentity("ws-1", "rdl-1", "ds-1", dataset_workspace_id="ws-1"),
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload["targetWorkspaces"] == [{"id": "ws-1"}]


def test_generate_embed_token_payload_is_minimal_for_a_paginated_report() -> None:
    """A paginated report's GenerateToken payload is deliberately minimal --
    reports/datasets only, no targetWorkspaces/accessLevel, matching a
    validated reference implementation. Its dataset entry does need one
    field an interactive report's never does: xmlaPermissions: "ReadOnly" --
    without it, GenerateToken succeeds but the token itself cannot connect
    to the dataset ("XMLA permissions are off"), regardless of
    targetWorkspaces, capacity tier, or which workspace anything lives in --
    all tried and all irrelevant; only this field cleared it (confirmed live
    and matching Microsoft's own "Embed paginated reports" documentation)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token(
            "token",
            ReportIdentity("ws-1", "rdl-1", "ds-1"),
            report_type="paginated",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert payload == {
        "reports": [{"id": "rdl-1"}],
        "datasets": [{"id": "ds-1", "xmlaPermissions": "ReadOnly"}],
    }


def test_generate_embed_token_interactive_dataset_has_no_xmla_permissions_field() -> None:
    """xmlaPermissions is paginated-specific -- an interactive report's
    dataset entry is unchanged."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token("token", ReportIdentity("ws-1", "rpt-1", "ds-1"))

    payload = mock_post.call_args.kwargs["json"]
    assert payload["datasets"] == [{"id": "ds-1"}]


def test_generate_embed_token_omits_datasets_when_none_bound() -> None:
    """No dataset_id at all (nothing bound, of either report type) omits
    the "datasets" key entirely rather than sending an entry with no id."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token("token", ReportIdentity("ws-1", "rdl-1", ""))

    payload = mock_post.call_args.kwargs["json"]
    assert "datasets" not in payload


def test_generate_embed_token_includes_rls_identity() -> None:
    """When RLS is enabled and user_name/role are provided, identities are included."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
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


def test_generate_embed_token_omits_identity_with_no_discovered_role() -> None:
    """`use_rls` and `user_name` alone are not enough to attach an identity
    -- `role` must also be present. This looks overly strict (a dataset can
    require a mandatory identity with no named role at all), and dropping
    the `role` requirement was tried and reverted: it made Power BI reject
    every *non*-RLS dataset with "shouldn't have effective identity" (an
    identity attached where none was wanted), while RLS-secured datasets
    whose role discovery failed still didn't get a working token either --
    they have real named roles that discovery isn't finding, so an empty
    "roles": [] was never going to satisfy them. See "Discover RLS roles
    for non-PBIP-enabled semantic models" in
    tasks/playwright-ci-guide-epic.md for the actual fix this needs."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
        return_value=mock_response,
    ) as mock_post:
        generate_embed_token(
            "token",
            ReportIdentity("ws-1", "rpt-1", "ds-1"),
            use_rls=True,
            user_name="u1",
            role="",
        )

    payload = mock_post.call_args.kwargs["json"]
    assert "identities" not in payload


def test_generate_embed_token_omits_identity_when_rls_disabled() -> None:
    """When RLS is disabled, identities are omitted even if user_name/role are set."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"token": "embed-token-1"}

    with patch(
        "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
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
            "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
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
            "fab_test.scripts.playwright_validation.power_bi_api.requests.get",
            return_value=mock_token_response,
        ),
        patch(
            "fab_test.scripts.playwright_validation.power_bi_api.requests.post",
            return_value=mock_generate_response,
        ),
    ):
        context = get_embed_context(config)

    assert context.report_id == "rpt-1"
    assert context.dataset_id == "ds-1"
    assert context.embed_url == "https://app.powerbi.com/embed?rpt"
    assert context.embed_token == "embed-token"
