"""Contract tests for the Playwright validation config loader."""

from __future__ import annotations

import json
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
    assert config.timeout_seconds == 180
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


# --------------------------------------------------------------------------- #
# Auto-discovering .env at the repository root (Config Consolidation §8)
# --------------------------------------------------------------------------- #


@pytest.mark.playwright
def test_load_config_auto_discovers_env_at_repo_root(tmp_path, monkeypatch):
    """No --env-file: a .env at the repo root (cwd) is discovered automatically."""
    monkeypatch.delenv("PLAYWRIGHT_ENV_FILE", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "PLAYWRIGHT_WORKSPACE_ID=auto-ws\nPLAYWRIGHT_REPORT_ID=auto-rpt\n",
        encoding="utf-8",
    )

    config = load_config(None, required=False)

    assert config.workspace_id == "auto-ws"
    assert config.report_id == "auto-rpt"


@pytest.mark.playwright
def test_load_config_returns_empty_when_no_env_file_discovered(tmp_path, monkeypatch):
    """No --env-file and no .env at the repo root: behaves as if nothing was set."""
    monkeypatch.delenv("PLAYWRIGHT_ENV_FILE", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_WORKSPACE_ID", raising=False)
    monkeypatch.chdir(tmp_path)

    config = load_config(None, required=False)

    assert config.workspace_id == ""


@pytest.mark.playwright
def test_load_config_explicit_env_file_overrides_auto_discovery(tmp_path, monkeypatch):
    """--env-file PATH is used instead of the auto-discovered repo-root .env."""
    monkeypatch.delenv("PLAYWRIGHT_ENV_FILE", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PLAYWRIGHT_WORKSPACE_ID=auto-ws\n", encoding="utf-8")
    custom = tmp_path / "custom.env"
    custom.write_text("PLAYWRIGHT_WORKSPACE_ID=custom-ws\n", encoding="utf-8")

    config = load_config(custom, required=False)

    assert config.workspace_id == "custom-ws"


@pytest.mark.playwright
def test_discovered_env_secrets_never_appear_in_test_case_dict(tmp_path, monkeypatch):
    """A discovered .env's credentials never leak into to_test_case_dict()."""
    monkeypatch.delenv("PLAYWRIGHT_ENV_FILE", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("FABRIC_TENANT_ID", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=auto-ws",
                "FABRIC_CLIENT_ID=super-secret-id",
                "FABRIC_CLIENT_SECRET=super-secret-value",
                "FABRIC_TENANT_ID=super-secret-tenant",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(None, required=False)
    test_case_dict = config.to_test_case_dict()

    assert "super-secret-value" not in json.dumps(test_case_dict)
    assert "client_secret" not in test_case_dict
    assert "client_id" not in test_case_dict
    assert "tenant_id" not in test_case_dict
