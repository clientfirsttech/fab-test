"""Test-matrix discovery: report pages, page-scoped bookmarks, RLS roles.

Split out of ``invoke_playwright.py`` (Playwright Test Matrix Discovery
epic): discovering what to test and minting the per-role embed tokens that
follow from it is a different concern from the orchestration wrapper that
calls it, and combining them pushed that file over the source-module hard
budget in ``tests/test_module_budget.py``.
"""

from __future__ import annotations

import argparse
import dataclasses
from typing import Any

from .config import PlaywrightValidationConfig
from .embed_config import build_embed_config
from .fabric_service_client import build_fabric_service_client
from .power_bi_api import PowerBiApiError, get_embed_context
from .service_client import FabricRestClient, FabricToken, ServiceClientError
from .test_cases import DiscoveredBookmark, DiscoveredPage


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message."""
    print(message)


def _discover_pages(
    rest_client: FabricRestClient,
    workspace_id: str,
    report_id: str,
) -> list[DiscoveredPage] | None:
    """Discover a report's pages and page-scoped bookmarks.

    Returns ``None`` (falling back to the legacy single-case shape) when the
    pages call itself fails -- most commonly a missing ``Report.Read.All``
    grant on the service principal. A bookmarks failure is non-fatal: pages
    are still worth testing without their bookmarks.
    """
    try:
        pages = rest_client.get_report_pages(workspace_id, report_id)
    except ServiceClientError as exc:
        log(
            "::warning::Could not discover report pages "
            f"({exc}); Report.Read.All is required for the service principal. "
            "Falling back to the default page. Pass --pages none to silence "
            "this warning."
        )
        return None
    if not pages:
        return None

    try:
        bookmarks = rest_client.get_report_bookmarks(workspace_id, report_id)
    except ServiceClientError as exc:
        log(f"::warning::Could not discover report bookmarks ({exc}).")
        bookmarks = []

    bookmarks_by_page: dict[str, list[DiscoveredBookmark]] = {}
    for bookmark in bookmarks:
        bookmarks_by_page.setdefault(bookmark.get("page_id", ""), []).append(
            DiscoveredBookmark(
                bookmark_id=bookmark["bookmark_id"],
                bookmark_name=bookmark["bookmark_name"],
            )
        )

    return [
        DiscoveredPage(
            page_id=page["page_id"],
            page_name=page["page_name"],
            bookmarks=bookmarks_by_page.get(page["page_id"], []),
        )
        for page in pages
    ]


def _discover_roles(
    rest_client: FabricRestClient,
    workspace_id: str,
    dataset_id: str,
) -> list[str] | None:
    """Discover RLS/OLS role names from the semantic model definition.

    Returns ``None`` (falling back to the single configured role) on
    failure or when the model has no roles.
    """
    try:
        roles = rest_client.get_semantic_model_roles(workspace_id, dataset_id)
    except ServiceClientError as exc:
        log(
            f"::warning::Could not discover semantic model roles ({exc}); "
            "SemanticModel.Read.All is required for the service principal. "
            "Falling back to PLAYWRIGHT_ROLE. Pass --roles none to silence "
            "this warning."
        )
        return None
    return roles or None


def resolve_discovery(
    config: PlaywrightValidationConfig,
    args: argparse.Namespace,
) -> tuple[list[DiscoveredPage] | None, list[str] | None]:
    """Discover the page/bookmark/role matrix unless overridden or disabled.

    An explicit ``--page-ids``/``--bookmark-ids`` (or ``PLAYWRIGHT_PAGE_IDS``/
    ``PLAYWRIGHT_BOOKMARK_IDS``) skips page/bookmark discovery entirely --
    it is a statement about what to test, not a filter over what was found.
    Role discovery only runs when RLS is in play (``config.use_rls``); with
    no roles requested there is nothing a role matrix would add.

    A paginated report has neither dimension -- RDL reports have no
    page/bookmark matrix -- so both are skipped outright rather than
    discovering an empty result the hard way.
    """
    if config.report_type == "paginated":
        return None, None

    discover_pages = not (config.page_ids or config.bookmark_ids) and getattr(
        args, "pages", "auto"
    ) != "none"
    discover_roles = config.use_rls and getattr(args, "roles", "auto") != "none"

    if not discover_pages and not discover_roles:
        return None, None

    try:
        client = build_fabric_service_client(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            cloud=config.cloud,
        )
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort, never
        # fatal: a run that cannot authenticate for discovery still runs the
        # default-page case rather than aborting.
        log(
            "::warning::Could not authenticate for test-matrix discovery "
            f"({exc}); running the default case only."
        )
        return None, None

    rest_client = FabricRestClient(
        FabricToken(access_token=client.access_token, cloud=config.cloud)
    )

    pages = (
        _discover_pages(rest_client, config.workspace_id, config.report_id)
        if discover_pages
        else None
    )
    roles = (
        _discover_roles(rest_client, config.workspace_id, config.dataset_id)
        if discover_roles
        else None
    )
    return pages, roles


def acquire_embed_configs(
    config: PlaywrightValidationConfig, roles: list[str]
) -> dict[str, dict[str, Any]]:
    """Mint one embed token per distinct role.

    An embed token carries its RLS identity, so a matrix spanning N roles
    needs N tokens -- reusing one token across roles would silently test
    every role under whichever identity was minted first.
    """
    embed_configs: dict[str, dict[str, Any]] = {}
    for role in roles:
        role_config = dataclasses.replace(config, role=role) if role else config
        try:
            embed_context = get_embed_context(role_config)
        except PowerBiApiError as exc:
            raise PowerBiApiError(
                f"role '{role or 'default'}': {exc}",
                status_code=exc.status_code,
                body=exc.body,
            ) from exc
        embed_configs[role] = build_embed_config(
            report_id=embed_context.report_id,
            embed_url=embed_context.embed_url,
            embed_token=embed_context.embed_token,
            report_type=config.report_type,
        ).to_dict()
    return embed_configs
