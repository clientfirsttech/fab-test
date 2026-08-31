"""Contract tests for test-matrix discovery (pages, bookmarks, roles).

Always passes on any machine: `FabricRestClient` and
`build_fabric_service_client` are mocked, so no browser or live Power
BI/Fabric service is invoked.
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.config import PlaywrightValidationConfig
from fabric_ci_cd_dataops.scripts.playwright_validation.discovery import (
    _discover_pages,
    _discover_roles,
    acquire_embed_configs,
    resolve_discovery,
)
from fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api import (
    EmbedContext,
    PowerBiApiError,
)
from fabric_ci_cd_dataops.scripts.playwright_validation.service_client import ServiceClientError

_DISCOVERY = "fabric_ci_cd_dataops.scripts.playwright_validation.discovery"


def _config(**overrides) -> PlaywrightValidationConfig:
    defaults = {
        "workspace_id": "ws-1",
        "report_id": "rpt-1",
        "report_name": "SalesReport",
        "dataset_id": "ds-1",
        "page_ids": [],
        "bookmark_ids": [],
        "user_name": "",
        "role": "",
        "use_rls": False,
        "cloud": "public",
        "client_id": "client-1",
        "client_secret": "secret-1",
        "tenant_id": "tenant-1",
        "timeout_seconds": 60,
        "headless": True,
    }
    defaults.update(overrides)
    return PlaywrightValidationConfig(**defaults)


def _args(**overrides) -> argparse.Namespace:
    defaults = {"page_ids": None, "bookmark_ids": None, "pages": "auto", "roles": "auto"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_discover_pages_pairs_each_bookmark_with_its_own_page() -> None:
    """A bookmark's page_id from the API is used to attach it to that page,
    never to another page."""
    rest_client = MagicMock()
    rest_client.get_report_pages.return_value = [
        {"page_id": "page1", "page_name": "Page One"},
        {"page_id": "page2", "page_name": "Page Two"},
    ]
    rest_client.get_report_bookmarks.return_value = [
        {"bookmark_id": "bmk1", "bookmark_name": "Bookmark One", "page_id": "page1"},
    ]

    pages = _discover_pages(rest_client, "ws-1", "rpt-1")

    assert pages is not None
    assert [p.page_id for p in pages] == ["page1", "page2"]
    assert [b.bookmark_id for b in pages[0].bookmarks] == ["bmk1"]
    assert pages[1].bookmarks == []


def test_discover_pages_falls_back_to_none_when_pages_call_fails() -> None:
    """A pages-API failure (e.g. missing Report.Read.All) falls back to the
    legacy single-case shape rather than failing the run."""
    rest_client = MagicMock()
    rest_client.get_report_pages.side_effect = ServiceClientError(
        "forbidden", status_code=403
    )

    assert _discover_pages(rest_client, "ws-1", "rpt-1") is None


def test_discover_pages_survives_a_bookmarks_failure() -> None:
    """Pages are still worth testing even when bookmark discovery fails."""
    rest_client = MagicMock()
    rest_client.get_report_pages.return_value = [
        {"page_id": "page1", "page_name": "Page One"},
    ]
    rest_client.get_report_bookmarks.side_effect = ServiceClientError("forbidden")

    pages = _discover_pages(rest_client, "ws-1", "rpt-1")

    assert pages == [
        pages[0].__class__(page_id="page1", page_name="Page One", bookmarks=[])
    ]


def test_discover_roles_returns_none_on_failure() -> None:
    """A roles-API failure falls back to the single configured role."""
    rest_client = MagicMock()
    rest_client.get_semantic_model_roles.side_effect = ServiceClientError("forbidden")

    assert _discover_roles(rest_client, "ws-1", "ds-1") is None


def test_discover_roles_returns_none_when_model_has_no_roles() -> None:
    """No roles on the model is treated the same as a discovery failure --
    fall back to the single configured role, not an empty matrix."""
    rest_client = MagicMock()
    rest_client.get_semantic_model_roles.return_value = []

    assert _discover_roles(rest_client, "ws-1", "ds-1") is None


def test_resolve_discovery_skips_pages_when_page_ids_are_explicit() -> None:
    """An explicit --page-ids override skips discovery entirely -- it is a
    statement about what to test, not a filter over what was found."""
    config = _config(page_ids=["p1"])

    with patch(f"{_DISCOVERY}.build_fabric_service_client") as mock_build:
        pages, roles = resolve_discovery(config, _args())

    mock_build.assert_not_called()
    assert pages is None
    assert roles is None


def test_resolve_discovery_skips_entirely_for_paginated_reports() -> None:
    """A paginated report has neither a page nor a bookmark dimension, so
    discovery is skipped outright -- even with RLS on, which would
    otherwise trigger role discovery."""
    config = _config(report_type="paginated", use_rls=True)

    with patch(f"{_DISCOVERY}.build_fabric_service_client") as mock_build:
        pages, roles = resolve_discovery(config, _args())

    mock_build.assert_not_called()
    assert pages is None
    assert roles is None


def test_resolve_discovery_skips_roles_without_rls() -> None:
    """Role discovery only runs when RLS is in play."""
    config = _config(use_rls=False)

    with patch(f"{_DISCOVERY}.build_fabric_service_client") as mock_build:
        pages, roles = resolve_discovery(config, _args(pages="none"))

    mock_build.assert_not_called()
    assert pages is None
    assert roles is None


def test_resolve_discovery_falls_back_when_authentication_fails() -> None:
    """A discovery client that cannot authenticate runs the default case
    only, rather than aborting the whole run."""
    config = _config()

    with patch(
        f"{_DISCOVERY}.build_fabric_service_client",
        side_effect=RuntimeError("no network"),
    ):
        pages, roles = resolve_discovery(config, _args())

    assert pages is None
    assert roles is None


def test_resolve_discovery_reuses_the_authenticated_clients_token() -> None:
    """Discovery builds its Fabric REST client from the already-acquired
    access token rather than a second credential flow."""
    config = _config(use_rls=True)
    mock_service_client = MagicMock()
    mock_service_client.access_token = "reused-token"

    with (
        patch(f"{_DISCOVERY}.build_fabric_service_client", return_value=mock_service_client),
        patch(f"{_DISCOVERY}.FabricRestClient") as mock_rest_client_cls,
    ):
        mock_rest_client_cls.return_value.get_report_pages.return_value = []
        mock_rest_client_cls.return_value.get_semantic_model_roles.return_value = [
            "Manager"
        ]

        _pages, roles = resolve_discovery(config, _args())

    token_arg = mock_rest_client_cls.call_args[0][0]
    assert token_arg.access_token == "reused-token"
    assert roles == ["Manager"]


def test_acquire_embed_configs_mints_one_token_per_role() -> None:
    """A distinct embed context (and token) is minted per role."""
    config = _config()

    def fake_get_embed_context(cfg: PlaywrightValidationConfig) -> EmbedContext:
        return EmbedContext(
            embed_url="https://app.powerbi.com/embed",
            embed_token=f"token-{cfg.role}",
            report_id=cfg.report_id,
            dataset_id=cfg.dataset_id,
        )

    with patch(f"{_DISCOVERY}.get_embed_context", side_effect=fake_get_embed_context):
        configs = acquire_embed_configs(config, ["Manager", "Analyst"])

    assert configs["Manager"]["accessToken"] == "token-Manager"
    assert configs["Analyst"]["accessToken"] == "token-Analyst"


def test_acquire_embed_configs_omits_page_and_bookmark_for_paginated_reports() -> None:
    """A paginated report's minted embed config carries no pageName/bookmark
    key at all -- RDL reports have neither dimension."""
    config = _config(report_type="paginated")

    def fake_get_embed_context(cfg: PlaywrightValidationConfig) -> EmbedContext:
        return EmbedContext(
            embed_url="https://app.powerbi.com/embed",
            embed_token="token",
            report_id=cfg.report_id,
            dataset_id=cfg.dataset_id,
        )

    with patch(f"{_DISCOVERY}.get_embed_context", side_effect=fake_get_embed_context):
        configs = acquire_embed_configs(config, [""])

    assert "pageName" not in configs[""]
    assert "bookmark" not in configs[""]


def test_acquire_embed_configs_names_the_failing_role() -> None:
    """A token failure for one role says which role, not just "boom"."""
    config = _config()

    with (
        patch(
            f"{_DISCOVERY}.get_embed_context",
            side_effect=PowerBiApiError("boom", status_code=400),
        ),
        pytest.raises(PowerBiApiError, match="role 'Manager'"),
    ):
        acquire_embed_configs(config, ["Manager"])
