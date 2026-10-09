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
import json
import os
import re
from typing import Any

from .config import PlaywrightValidationConfig
from .embed_config import build_embed_config
from .fabric_service_client import build_fabric_service_client
from .power_bi_api import PowerBiApiError, get_embed_context
from .rdl_datasource import RdlReportParameter, parse_rdl_report_parameters_text
from .service_client import FabricRestClient, FabricToken, ServiceClientError
from .test_cases import DiscoveredBookmark, DiscoveredPage

_WORKFLOW_PREFIX = re.compile(r"^::(?:notice|warning)::")


def log(message: str) -> None:
    """Print a progress line, with its ``::notice::``/``::warning::`` prefix only in CI.

    fab-test hands the wrapper its terminal under ``--format text``, so the
    prefix used to reach a laptop verbatim. CI is the parent's definition
    (``GITHUB_ACTIONS`` or ``CI``), so the two never disagree.
    """
    in_ci = os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI")
    print(message if in_ci else _WORKFLOW_PREFIX.sub("", message))


# What the current report's discovery could not cover. Discovery is
# best-effort -- a failed lookup still renders, with one role or no
# parameters -- so each gap is recorded here and becomes a warning-level
# finding, rather than a narrower run reading as a plain pass. Reset as each
# report's discovery starts; drained when its envelope is written.
_coverage_limits: list[str] = []


def reset_coverage_limits() -> None:
    """Forget the previous report's gaps."""
    _coverage_limits.clear()


def apply_coverage_limits(envelope: dict[str, Any], report_name: str) -> None:
    """Add a `coverage_limited` warning per gap; a pass becomes a warning, a failure stays one."""
    envelope["findings"] = list(envelope.get("findings") or []) + [
        {"rule": "coverage_limited", "severity": "warning", "object": report_name, "message": gap}
        for gap in _coverage_limits
    ]
    if _coverage_limits and envelope.get("status") == "passed":
        envelope["status"] = "warning"
    _coverage_limits.clear()


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
        _coverage_limits.append(
            f"RLS roles were not discovered ({exc}), so only the configured role was tested; grant "
            "SemanticModel.Read.All, or pass --roles none to test without roles deliberately"
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
    Role discovery runs when RLS is in play -- ``config.use_rls``, or an
    effective-identity user being configured at all; with neither, there is
    nothing a discovered role could be embedded with.

    A paginated report has neither dimension -- RDL reports have no
    page/bookmark matrix -- so both are skipped outright rather than
    discovering an empty result the hard way.
    """
    reset_coverage_limits()  # first for every report, paginated included
    if config.report_type == "paginated":
        return None, None

    discover_pages = not (config.page_ids or config.bookmark_ids) and getattr(
        args, "pages", "auto"
    ) != "none"
    # An effective-identity user is enough on its own: it is what a role can
    # actually be tested with, and requiring PLAYWRIGHT_USE_RLS as well is how
    # a secured model ends up silently tested under one identity while its
    # roles go unexercised. With no identity configured there is nothing a
    # discovered role could be embedded with, so nothing is asked for.
    rls_in_play = config.use_rls or bool(config.user_name)
    discover_roles = rls_in_play and getattr(args, "roles", "auto") != "none"

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


@dataclasses.dataclass(frozen=True)
class PaginatedPlan:
    """What a paginated report's cases need beyond its baseline config.

    ``dataset_id`` is the one ``GenerateToken`` must be given (from the
    local ``.rdl`` when there was one, else from the report's datasources).
    ``parameter_sets`` holds at most one set -- the first valid value of each
    single-value parameter and the first two of each multi-value one, a
    multi-value parameter repeated once per value, the embed SDK's
    ``parameterValues`` shape -- and is empty when the report declares no
    parameter a value could be picked for.
    """

    dataset_id: str
    parameter_sets: list[list[dict[str, str]]]


def _declared_parameters(
    config: PlaywrightValidationConfig, rest_client: FabricRestClient
) -> list[RdlReportParameter]:
    """Return the report's parameters: from its local .rdl, else its deployed one."""
    try:
        declared = json.loads(config.report_parameters or "[]")
    except json.JSONDecodeError:
        declared = []
    if declared:
        return [
            RdlReportParameter(
                name=entry.get("name", ""),
                multi_value=bool(entry.get("multi_value")),
                values_query=entry.get("values_query", ""),
                value_column=entry.get("value_column", ""),
                static_values=tuple(entry.get("static_values") or ()),
            )
            for entry in declared
            if entry.get("name")
        ]
    try:
        definition = rest_client.get_paginated_report_definition(
            config.workspace_id, config.report_id
        )
    except ServiceClientError as exc:
        log(f"::warning::Could not read the paginated report's definition ({exc}); testing it with no parameters.")
        _coverage_limits.append(
            f"the paginated report's parameters were not read ({exc}), so it was tested with none; "
            "run with --artifact-dir pointing at its local .rdl to test its parameters"
        )
        return []
    return parse_rdl_report_parameters_text(definition)


def _valid_values(
    parameter: RdlReportParameter,
    rest_client: FabricRestClient,
    config: PlaywrightValidationConfig,
    dataset_id: str,
) -> list[str]:
    """Return a parameter's valid values in the order the report offers them."""
    if parameter.static_values:
        return list(parameter.static_values)
    if not (parameter.values_query and parameter.value_column and dataset_id):
        return []
    try:
        rows = rest_client.execute_dax_query(
            config.dataset_workspace_id or config.workspace_id,
            dataset_id,
            parameter.values_query,
        )
    except ServiceClientError as exc:
        log(
            f"::warning::Could not query valid values for parameter '{parameter.name}' "
            f"({exc}); the \"Dataset Execute Queries REST API\" tenant setting must allow "
            "the service principal. Testing the report with no parameters."
        )
        _coverage_limits.append(
            f"no valid values for parameter '{parameter.name}' ({exc}), so it was tested with no parameters; "
            'allow the service principal under the "Dataset Execute Queries REST API" tenant setting'
        )
        return []
    values: list[str] = []
    for row in rows:
        value = row.get(parameter.value_column)
        if value is not None and str(value) not in values:
            values.append(str(value))
    return values


def resolve_paginated_plan(config: PlaywrightValidationConfig) -> PaginatedPlan:
    """Resolve a paginated report's dataset and the parameter set to test.

    Best-effort like the interactive discovery above: a report whose plan
    cannot be resolved is still tested, with whatever the config already
    had and no parameterized case.
    """
    fallback = PaginatedPlan(dataset_id=config.dataset_id, parameter_sets=[])
    try:
        client = build_fabric_service_client(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            cloud=config.cloud,
        )
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort, never fatal
        log(f"::warning::Could not authenticate for paginated report discovery ({exc}).")
        return fallback
    rest_client = FabricRestClient(
        FabricToken(access_token=client.access_token, cloud=config.cloud)
    )

    dataset_id = config.dataset_id
    if not dataset_id:
        try:
            found = rest_client.get_report_dataset_ids(config.workspace_id, config.report_id)
        except ServiceClientError as exc:
            log(f"::warning::Could not read the paginated report's data sources ({exc}).")
            found = []
        dataset_id = found[0] if found else ""

    parameter_set: list[dict[str, str]] = []
    for parameter in _declared_parameters(config, rest_client):
        values = _valid_values(parameter, rest_client, config, dataset_id)
        parameter_set.extend(
            {"name": parameter.name, "value": value}
            for value in values[: 2 if parameter.multi_value else 1]
        )
    return PaginatedPlan(
        dataset_id=dataset_id, parameter_sets=[parameter_set] if parameter_set else []
    )


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
