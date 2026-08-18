"""Contract tests for the Playwright validation config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.config import (
    PlaywrightValidationConfig,
    load_config,
)


@pytest.fixture
def temp_env_file(tmp_path: Path) -> Path:
    """Create a temporary .env file with valid Playwright settings."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "PLAYWRIGHT_REPORT_NAME=SalesReport",
                "PLAYWRIGHT_DATASET_ID=ds-1",
                "PLAYWRIGHT_PAGE_IDS=page1, page2",
                "PLAYWRIGHT_BOOKMARK_IDS=bmk1",
                "PLAYWRIGHT_USER_NAME=user@example.com",
                "PLAYWRIGHT_ROLE=Viewer",
                "PLAYWRIGHT_CLOUD=usgov",
                "PLAYWRIGHT_TIMEOUT_SECONDS=120",
                "PLAYWRIGHT_HEADLESS=false",
                "FABRIC_CLIENT_ID=client-1",
                "FABRIC_CLIENT_SECRET=secret-1",
                "FABRIC_TENANT_ID=tenant-1",
            ]
        ),
        encoding="utf-8",
    )
    return env_path


def test_load_config_from_env_file(temp_env_file: Path) -> None:
    config = load_config(temp_env_file)
    assert config == PlaywrightValidationConfig(
        workspace_id="ws-1",
        report_id="rpt-1",
        report_name="SalesReport",
        dataset_id="ds-1",
        page_ids=["page1", "page2"],
        bookmark_ids=["bmk1"],
        user_name="user@example.com",
        role="Viewer",
        use_rls=False,
        cloud="usgov",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=120,
        headless=False,
    )


def test_load_config_from_environment_overrides_env_file(
    temp_env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLAYWRIGHT_REPORT_NAME", "OverriddenReport")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "env-client")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("FABRIC_TENANT_ID", "env-tenant")

    config = load_config(temp_env_file)
    assert config.report_name == "OverriddenReport"
    assert config.client_id == "env-client"
    assert config.client_secret == "env-secret"
    assert config.headless is False


def test_load_config_defaults_when_optional_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "PLAYWRIGHT_REPORT_NAME=Report",
                "PLAYWRIGHT_DATASET_ID=ds-1",
                "FABRIC_CLIENT_ID=client-1",
                "FABRIC_CLIENT_SECRET=secret-1",
                "FABRIC_TENANT_ID=tenant-1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)

    config = load_config(env_path)
    assert config.page_ids == []
    assert config.bookmark_ids == []
    assert config.cloud == "public"
    assert config.timeout_seconds == 60
    assert config.headless is True
    assert config.user_name == ""
    assert config.role == ""


def test_load_config_falls_back_to_fabric_service_principal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When FABRIC_CLIENT_* is absent, FABRIC_SERVICE_PRINCIPAL_* is used."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "PLAYWRIGHT_REPORT_NAME=Report",
                "PLAYWRIGHT_DATASET_ID=ds-1",
                "FABRIC_SERVICE_PRINCIPAL_ID=sp-id",
                "FABRIC_SERVICE_PRINCIPAL_SECRET=sp-secret",
                "FABRIC_TENANT_ID=tenant-1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FABRIC_CLIENT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_SECRET", raising=False)

    config = load_config(env_path)
    assert config.client_id == "sp-id"
    assert config.client_secret == "sp-secret"


def test_load_config_missing_required_raises() -> None:
    with pytest.raises(ValueError) as exc_info:
        # Provide an empty env file path that does not exist and has no env vars.
        load_config(Path("/nonexistent/.env"))
    missing = str(exc_info.value)
    assert "PLAYWRIGHT_WORKSPACE_ID" in missing
    assert "FABRIC_CLIENT_SECRET / FABRIC_SERVICE_PRINCIPAL_SECRET" in missing


def test_load_config_not_required_allows_missing() -> None:
    config = load_config(Path("/nonexistent/.env"), required=False)
    assert config.workspace_id == ""
    assert config.client_secret == ""
