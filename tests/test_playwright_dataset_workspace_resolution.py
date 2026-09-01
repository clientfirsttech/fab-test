"""Contract tests for resolving --dataset-workspace-id as a display name.

A value here may come straight from a paginated report's own .rdl file,
which records rd:PowerBIWorkspaceName -- a display name, not a GUID
(Paginated Report RDL Data Source Resolution epic). resolve_workspace_id
itself is tested directly in test_playwright_resolver.py; this covers
_build_config_from_args actually calling it rather than passing the raw
value straight into GenerateToken's payload.
"""

from __future__ import annotations

from unittest.mock import patch

from fab_test.scripts.invoke_playwright import (
    _build_config_from_args,
    parse_args,
)
from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig
from fab_test.scripts.playwright_validation.resolver import (
    ResolvedEnvironment,
    ResolvedReport,
)


def _base_config() -> PlaywrightValidationConfig:
    return PlaywrightValidationConfig(
        workspace_id="",
        report_id="",
        report_name="",
        dataset_id="",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=60,
        headless=True,
    )


def test_dataset_workspace_id_flag_is_resolved_as_a_display_name() -> None:
    """A workspace name (not a GUID) passed via --dataset-workspace-id --
    exactly what a .rdl file's rd:PowerBIWorkspaceName records -- is resolved
    to an ID using the same client already built for the report itself."""
    resolved = ResolvedReport(
        workspace_id="ws-report",
        report_id="rdl-1",
        report_name="Invoice RDL",
        semantic_model_id="ds-1",
        environment="DEV",
        report_type="paginated",
    )
    client = object()

    with (
        patch(
            "fab_test.scripts.invoke_playwright.load_config",
            return_value=_base_config(),
        ),
        patch(
            "fab_test.scripts.invoke_playwright.resolve_environment"
        ) as mock_env,
        patch(
            "fab_test.scripts.invoke_playwright.resolve_report",
            return_value=resolved,
        ),
        patch(
            "fab_test.scripts.invoke_playwright.build_fabric_service_client",
            return_value=client,
        ),
        patch(
            "fab_test.scripts.invoke_playwright.resolve_workspace_id",
            return_value="ws-dataset-resolved",
        ) as mock_resolve_workspace,
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV", workspace_id="ws-report"
        )
        args = parse_args(
            [
                "--artifact",
                "Invoice RDL",
                "--env",
                "dev",
                "--dataset-workspace-id",
                "visual-error-testing",
            ]
        )
        result = _build_config_from_args(args)

    mock_resolve_workspace.assert_called_once_with(client, "visual-error-testing")
    assert result.dataset_workspace_id == "ws-dataset-resolved"


def test_dataset_workspace_id_stays_empty_when_never_given() -> None:
    """No --dataset-workspace-id and no PLAYWRIGHT_DATASET_WORKSPACE_ID:
    nothing to resolve, and resolve_workspace_id is never called."""
    resolved = ResolvedReport(
        workspace_id="ws-report",
        report_id="rpt-1",
        report_name="Sales",
        semantic_model_id="ds-1",
        environment="DEV",
    )
    client = object()

    with (
        patch(
            "fab_test.scripts.invoke_playwright.load_config",
            return_value=_base_config(),
        ),
        patch(
            "fab_test.scripts.invoke_playwright.resolve_environment"
        ) as mock_env,
        patch(
            "fab_test.scripts.invoke_playwright.resolve_report",
            return_value=resolved,
        ),
        patch(
            "fab_test.scripts.invoke_playwright.build_fabric_service_client",
            return_value=client,
        ),
        patch(
            "fab_test.scripts.invoke_playwright.resolve_workspace_id"
        ) as mock_resolve_workspace,
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV", workspace_id="ws-report"
        )
        args = parse_args(["--artifact", "Sales", "--env", "dev"])
        result = _build_config_from_args(args)

    mock_resolve_workspace.assert_not_called()
    assert result.dataset_workspace_id == ""
