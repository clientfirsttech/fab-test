"""Contract tests: a known workspace is enough to resolve a named report.

Scope
-----
README documents `fab-test playwright --artifact NAME --workspace-id WS` as
the no-config path, but both the discovery fallback and the subprocess's
config builder refused to proceed without `--env` -- "No environment given,
so there is nothing to resolve 'NAME' against" -- even though
`resolve_environment` short-circuits the moment a workspace override is
supplied and never needs the label at all (Playwright CI Guide epic, first
live run 2026-09-26).

    pytest tests/test_playwright_workspace_without_env.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from fab_test.scripts.fab_test_execution import _playwright_remote_target
from fab_test.scripts.invoke_playwright import _build_config_from_args, parse_args
from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig
from fab_test.scripts.playwright_validation.resolver import (
    ResolvedReport,
    ServiceResolutionError,
)

_WS = "798dfd00-0081-45d3-a7a7-f74f62e57277"


@pytest.fixture(autouse=True)
def _no_ambient_scope(monkeypatch):
    monkeypatch.delenv("FABRIC_ENVIRONMENT", raising=False)
    monkeypatch.delenv("FABRIC_WORKSPACE_ID", raising=False)


def _discovery_args(**overrides) -> argparse.Namespace:
    defaults = {
        "artifact": "Sales",
        "target": None,
        "environment": "",
        "workspace_id": "",
        "file_config": {},
        "artifact_dir": ".",
        "output_dir": "fab-test-results",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _config(workspace_id: str = "") -> PlaywrightValidationConfig:
    return PlaywrightValidationConfig(
        workspace_id=workspace_id,
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


def _resolved() -> ResolvedReport:
    return ResolvedReport(
        workspace_id=_WS,
        report_id="rpt-1",
        report_name="Sales",
        semantic_model_id="ds-1",
        environment="",
    )


def _build(argv: list[str], config: PlaywrightValidationConfig):
    with (
        patch("fab_test.scripts.invoke_playwright.load_config", return_value=config),
        patch("fab_test.scripts.invoke_playwright.build_fabric_service_client"),
        patch(
            "fab_test.scripts.invoke_playwright.resolve_report",
            return_value=_resolved(),
        ) as mock_resolve,
    ):
        result = _build_config_from_args(parse_args(argv))
    return result, mock_resolve


class TestRemoteTargetDiscovery:
    def test_a_workspace_flag_stands_in_for_an_environment(self):
        args = _discovery_args(workspace_id=_WS)
        assert _playwright_remote_target(args) == Path("Sales")

    def test_an_ambient_workspace_variable_stands_in_for_an_environment(self, monkeypatch):
        monkeypatch.setenv("FABRIC_WORKSPACE_ID", _WS)
        assert _playwright_remote_target(_discovery_args()) == Path("Sales")

    def test_a_workspace_in_fab_test_yml_stands_in_for_an_environment(self):
        args = _discovery_args(file_config={"workspace": "Sales Dev"})
        assert _playwright_remote_target(args) == Path("Sales")

    def test_neither_a_workspace_nor_an_environment_still_resolves_nothing(self):
        assert _playwright_remote_target(_discovery_args()) is None


class TestConfigFromArgs:
    def test_a_workspace_flag_resolves_the_report_without_an_environment(self):
        result, mock_resolve = _build(
            ["--artifact", "Sales", "--workspace-id", _WS], _config()
        )
        resolved_env = mock_resolve.call_args.args[1]
        assert resolved_env.workspace_id == _WS
        assert result.report_id == "rpt-1"

    def test_a_workspace_from_the_env_file_resolves_without_an_environment(self):
        result, mock_resolve = _build(["--artifact", "Sales"], _config(workspace_id=_WS))
        resolved_env = mock_resolve.call_args.args[1]
        assert resolved_env.workspace_id == _WS
        assert result.report_id == "rpt-1"

    def test_neither_a_workspace_nor_an_environment_names_every_fix(self):
        with pytest.raises(ServiceResolutionError) as exc:
            _build(["--artifact", "Sales"], _config())
        message = str(exc.value)
        assert "--env" in message
        assert "--workspace-id" in message
        assert "FABRIC_WORKSPACE_ID" in message
