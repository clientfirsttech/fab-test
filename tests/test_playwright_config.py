"""Contract tests for the Playwright validation config loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fab_test.scripts.playwright_validation.config import (
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
                "PLAYWRIGHT_REPORT_TYPE=report",
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
        report_type="report",
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
    """Given no fab-test.yml in scope, should default every optional field --
    isolated from a contributor's local, gitignored fab-test.yml at the repo
    root (which typically pins a real playwright_user_name), or this test would
    pass or fail depending on what that unrelated file happens to hold."""
    monkeypatch.chdir(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "PLAYWRIGHT_REPORT_NAME=Report",
                "PLAYWRIGHT_DATASET_ID=ds-1",
                "PLAYWRIGHT_REPORT_TYPE=report",
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
                "PLAYWRIGHT_REPORT_TYPE=report",
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


def test_load_config_defaults_report_type_to_auto_when_not_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PLAYWRIGHT_REPORT_TYPE unset defaults to "auto" -- detected later from
    the artifact name at resolution time, not required upfront -- whenever
    the caller isn't in static .env-only mode (required=False, e.g. the
    --artifact/--env service-resolved path)."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "PLAYWRIGHT_DATASET_ID=ds-1",
                "FABRIC_CLIENT_ID=client-1",
                "FABRIC_CLIENT_SECRET=secret-1",
                "FABRIC_TENANT_ID=tenant-1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PLAYWRIGHT_REPORT_TYPE", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_RENDER_WAIT_SECONDS", raising=False)

    config = load_config(env_path, required=False)

    assert config.report_type == "auto"
    assert config.render_wait_seconds == 20


def test_load_config_required_mode_still_needs_an_explicit_report_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Static .env-only mode (required=True: workspace/report/dataset IDs
    supplied directly, no artifact name) has nothing to auto-detect the
    report type from, so it stays required there even though --artifact
    mode no longer needs it."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "PLAYWRIGHT_DATASET_ID=ds-1",
                "FABRIC_CLIENT_ID=client-1",
                "FABRIC_CLIENT_SECRET=secret-1",
                "FABRIC_TENANT_ID=tenant-1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PLAYWRIGHT_REPORT_TYPE", raising=False)

    with pytest.raises(ValueError, match="PLAYWRIGHT_REPORT_TYPE"):
        load_config(env_path)


def test_load_config_reads_report_type_and_render_wait_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PLAYWRIGHT_REPORT_TYPE=paginated and PLAYWRIGHT_RENDER_WAIT_SECONDS load."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "FABRIC_CLIENT_ID=client-1",
                "FABRIC_CLIENT_SECRET=secret-1",
                "FABRIC_TENANT_ID=tenant-1",
                "PLAYWRIGHT_REPORT_TYPE=paginated",
                "PLAYWRIGHT_RENDER_WAIT_SECONDS=15",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(env_path)

    assert config.report_type == "paginated"
    assert config.render_wait_seconds == 15


def test_load_config_paginated_does_not_require_dataset_id(
    tmp_path: Path,
) -> None:
    """A paginated report has no bound semantic model, so no dataset_id is required."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "PLAYWRIGHT_WORKSPACE_ID=ws-1",
                "PLAYWRIGHT_REPORT_ID=rpt-1",
                "FABRIC_CLIENT_ID=client-1",
                "FABRIC_CLIENT_SECRET=secret-1",
                "FABRIC_TENANT_ID=tenant-1",
                "PLAYWRIGHT_REPORT_TYPE=paginated",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(env_path)  # required=True by default; must not raise

    assert config.dataset_id == ""


def test_load_config_missing_dataset_id_still_required_for_interactive_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly-declared interactive report still requires a dataset_id."""
    monkeypatch.setenv("PLAYWRIGHT_REPORT_TYPE", "report")
    with pytest.raises(ValueError) as exc_info:
        load_config(Path("/nonexistent/.env"))
    assert "PLAYWRIGHT_DATASET_ID" in str(exc_info.value)


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


def test_user_name_falls_back_to_the_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given no PLAYWRIGHT_USER_NAME, should take the effective-identity user
    from fab-test.yml, so an RLS run needs no per-caller environment variable."""
    monkeypatch.delenv("PLAYWRIGHT_USER_NAME", raising=False)
    (tmp_path / "fab-test.yml").write_text(
        "playwright_user_name: analyst@example.com\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    config = load_config(env_file=str(tmp_path / "missing.env"), required=False)

    assert config.user_name == "analyst@example.com"


def test_environment_user_name_wins_over_the_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given both, should keep the released environment variable winning --
    a workflow that sets it today must not start reading someone else's file."""
    monkeypatch.setenv("PLAYWRIGHT_USER_NAME", "ci@example.com")
    (tmp_path / "fab-test.yml").write_text(
        "playwright_user_name: analyst@example.com\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    config = load_config(env_file=str(tmp_path / "missing.env"), required=False)

    assert config.user_name == "ci@example.com"


def test_user_name_is_empty_when_no_source_supplies_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given neither source, should stay empty rather than invent an identity."""
    monkeypatch.delenv("PLAYWRIGHT_USER_NAME", raising=False)
    monkeypatch.chdir(tmp_path)

    config = load_config(env_file=str(tmp_path / "missing.env"), required=False)

    assert config.user_name == ""
