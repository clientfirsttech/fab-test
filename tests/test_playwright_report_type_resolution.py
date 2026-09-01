"""Contract tests for --report-type overriding auto-detection end to end.

Split out of test_invoke_playwright.py (module budget ratchet). resolve_report
itself is tested directly in test_playwright_resolver.py; this covers the
wrapper's CLI-flag plumbing on top of it (Playwright Report Type
Auto-Detection epic).
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


def test_build_config_from_args_report_type_flag_overrides_auto_detection() -> None:
    """--report-type forces the type, skipping auto-detection entirely --
    mirrors --dataset-id's override pattern."""
    config = PlaywrightValidationConfig(
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
    resolved = ResolvedReport(
        workspace_id="ws-resolved",
        report_id="rdl-resolved",
        report_name="Invoice RDL",
        semantic_model_id="",
        environment="DEV",
        report_type="paginated",
    )
    client = object()

    with (
        patch("fab_test.scripts.invoke_playwright.load_config", return_value=config),
        patch("fab_test.scripts.invoke_playwright.resolve_environment") as mock_env,
        patch("fab_test.scripts.invoke_playwright.resolve_report", return_value=resolved) as mock_report,
        patch(
            "fab_test.scripts.invoke_playwright.build_fabric_service_client",
            return_value=client,
        ),
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV",
            workspace_id="ws-resolved",
        )
        args = parse_args(
            [
                "--artifact",
                "Invoice RDL",
                "--env",
                "dev",
                "--env-file",
                ".env",
                "--report-type",
                "paginated",
            ]
        )
        result = _build_config_from_args(args)

    mock_report.assert_called_once_with(
        "Invoice RDL", mock_env.return_value, client, report_type="paginated"
    )
    assert result.report_type == "paginated"
