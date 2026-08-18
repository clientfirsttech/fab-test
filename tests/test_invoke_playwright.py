"""Contract tests for the invoke_playwright wrapper."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Match the import path used by invoke_playwright.py so exception classes compare
# equal when patched.
from fabric_ci_cd_dataops.scripts.invoke_playwright import (
    _build_config_from_args,
    _build_env_for_pytest,
    _parse_pytest_summary,
    _write_findings,
    main,
    parse_args,
)
from fabric_ci_cd_dataops.scripts.playwright_validation.config import PlaywrightValidationConfig
from fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api import EmbedContext, PowerBiApiError
from fabric_ci_cd_dataops.scripts.playwright_validation.resolver import ResolvedEnvironment, ResolvedReport


@pytest.fixture
def config() -> PlaywrightValidationConfig:
    """Return a minimal config for wrapper tests."""
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
        timeout_seconds=60,
        headless=True,
    )


def test_parse_args_requires_no_arguments() -> None:
    """The wrapper can be invoked with no CLI arguments."""
    args = parse_args([])
    assert args.env_file is None
    assert args.output_path is None
    assert args.verbose == 0


def test_parse_args_picks_up_env_file_and_output_path() -> None:
    """CLI flags are parsed into the namespace."""
    args = parse_args(["--env-file", ".env", "--output-path", "out.json", "-vv"])
    assert args.env_file == ".env"
    assert args.output_path == "out.json"
    assert args.verbose == 2


def test_write_findings_empty_on_success() -> None:
    """No findings are emitted when the run succeeds."""
    from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import TestCase

    case = TestCase(
        test_case="Report_default-page_no-bookmark",
        report_name="Report",
        report_id="rpt-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="ds-1",
        user_name="",
        role="",
    )
    assert _write_findings([case], success=True, message="") == []


def test_write_findings_on_failure() -> None:
    """Each case becomes an error finding when the run fails."""
    from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import TestCase

    case = TestCase(
        test_case="Report_default-page_no-bookmark",
        report_name="Report",
        report_id="rpt-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="ds-1",
        user_name="",
        role="",
    )
    findings = _write_findings([case], success=False, message="render timeout")

    assert len(findings) == 1
    assert findings[0]["rule"] == "visual_load_failed"
    assert findings[0]["severity"] == "error"
    assert findings[0]["object"] == "Report_default-page_no-bookmark"
    assert findings[0]["message"] == "render timeout"


def test_build_env_for_pytest_sets_expected_vars(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """The pytest environment includes CSV path, embed config, timeout,
    and results root."""

    from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import generate_test_cases

    cases = generate_test_cases(config)
    embed_config = {"type": "report", "id": "rpt-1"}

    env = _build_env_for_pytest(config, cases, embed_config, tmp_path)

    assert env["PLAYWRIGHT_TEST_CASES"] == str((tmp_path / "test-cases.csv").resolve())
    assert env["PLAYWRIGHT_EMBED_CONFIG"] == '{"type": "report", "id": "rpt-1"}'
    assert env["PLAYWRIGHT_TIMEOUT_MS"] == "60000"
    assert env["PLAYWRIGHT_HEADLESS"] == "true"
    assert env["PLAYWRIGHT_RESULTS_ROOT"] == str(tmp_path.resolve())


def test_parse_pytest_summary_extracts_short_summary() -> None:
    """The pytest short summary line is extracted from stdout."""
    stdout = "some output\n1 passed in 1.23s"
    assert _parse_pytest_summary(stdout) == "1 passed in 1.23s"


def test_main_writes_envelope_and_returns_zero_on_success(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """A successful pytest run writes a passed envelope and returns 0."""
    output_path = tmp_path / "envelope.json"
    embed_context = EmbedContext(
        embed_url="https://app.powerbi.com/embed",
        embed_token="token",
        report_id="rpt-1",
        dataset_id="ds-1",
    )
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="1 passed in 1.0s",
        stderr="",
    )

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.get_embed_context", return_value=embed_context),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._run_pytest", return_value=completed),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 0
    assert output_path.exists()
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "passed"' in data


def test_main_writes_envelope_and_returns_one_on_failure(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """A failed pytest run writes a failed envelope and returns 1."""
    output_path = tmp_path / "envelope.json"
    embed_context = EmbedContext(
        embed_url="https://app.powerbi.com/embed",
        embed_token="token",
        report_id="rpt-1",
        dataset_id="ds-1",
    )
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="1 failed in 1.0s",
        stderr="",
    )

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.get_embed_context", return_value=embed_context),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._run_pytest", return_value=completed),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 1
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "failed"' in data


def test_main_returns_one_on_api_error(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """A Power BI API error writes an error envelope and returns 1."""
    output_path = tmp_path / "envelope.json"

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.get_embed_context",
            side_effect=PowerBiApiError("boom", 400),
        ),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 1
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "error"' in data
    assert "boom" in data


def test_build_config_from_args_uses_service_client_for_artifact() -> None:
    """--artifact resolves the deployed report via the Fabric service client."""
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
        report_id="rpt-resolved",
        report_name="Resolved Report",
        semantic_model_id="ds-resolved",
        environment="DEV",
    )
    client = object()

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_environment") as mock_env,
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_report", return_value=resolved) as mock_report,
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.build_fabric_service_client",
            return_value=client,
        ) as mock_client,
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV",
            workspace_id="ws-resolved",
        )
        args = parse_args(
            ["--artifact", "Resolved Report", "--env", "dev", "--env-file", ".env"]
        )
        result = _build_config_from_args(args)

    assert result.workspace_id == "ws-resolved"
    assert result.report_id == "rpt-resolved"
    assert result.report_name == "Resolved Report"
    assert result.dataset_id == "ds-resolved"
    mock_client.assert_called_once()
    mock_env.assert_called_once_with(
        "dev",
        workspace_id_override="",
    )
    mock_report.assert_called_once_with(
        "Resolved Report", mock_env.return_value, client
    )


def test_build_config_loads_config_without_required_ids_for_artifact() -> None:
    """Static report IDs are not required when --artifact performs service lookup."""
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
        report_id="rpt-resolved",
        report_name="Resolved Report",
        semantic_model_id="ds-resolved",
        environment="DEV",
    )

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config",
            return_value=config,
        ) as mock_load,
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_environment") as mock_env,
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_report", return_value=resolved),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.build_fabric_service_client"),
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV",
            workspace_id="ws-resolved",
        )
        args = parse_args(
            ["--artifact", "Resolved Report", "--env", "dev"]
        )
        _build_config_from_args(args)

    mock_load.assert_called_once_with(None, required=False)
