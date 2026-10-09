"""Contract tests: `doctor` finds a workspace everywhere the run itself does.

Scope
-----
`doctor` looked only at `--workspace-id` and an exported
`FABRIC_WORKSPACE_ID`, so it reported the Playwright family ❌ "no workspace
or credentials resolved" for a machine whose run succeeded -- the workspace
came from `workspace:` in fab-test.yml, or from `PLAYWRIGHT_WORKSPACE_ID` in
the `.env` file `fab-test init` scaffolds, both of which the run honors
(Playwright CI Guide epic, first live run 2026-09-26).

    pytest tests/test_doctor_workspace_sources.py
"""

from __future__ import annotations

import argparse

import pytest

from fab_test.scripts.fab_test_registry import check_readiness

_WS = "798dfd00-0081-45d3-a7a7-f74f62e57277"


@pytest.fixture(autouse=True)
def _service_principal_only(monkeypatch, tmp_path):
    """A full service principal in the environment and an empty .env, so
    only the workspace source under test varies."""
    monkeypatch.delenv("FABRIC_WORKSPACE_ID", raising=False)
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client-1")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "secret-1")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(env_file))
    return env_file


def _args(**overrides) -> argparse.Namespace:
    defaults = {"workspace_id": "", "file_config": {}}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.parametrize("analyzer", ["playwright", "dependencies"])
def test_a_workspace_in_fab_test_yml_makes_the_playwright_family_ready(analyzer):
    result = check_readiness(analyzer, _args(file_config={"workspace": "Sales Dev"}))
    assert result["ready"] is True


def test_a_workspace_in_fab_test_yml_makes_pql_test_ready():
    result = check_readiness("pql_test", _args(file_config={"workspace": "Sales Dev"}))
    assert result["ready"] is True


@pytest.mark.parametrize("analyzer", ["playwright", "dependencies"])
def test_playwright_workspace_id_in_the_env_file_makes_the_playwright_family_ready(
    analyzer, _service_principal_only
):
    _service_principal_only.write_text(f"PLAYWRIGHT_WORKSPACE_ID={_WS}\n", encoding="utf-8")
    result = check_readiness(analyzer, _args())
    assert result["ready"] is True


def test_playwright_workspace_id_does_not_count_for_pql_test(_service_principal_only, monkeypatch):
    """pql_test's run never reads PLAYWRIGHT_WORKSPACE_ID, so doctor must not
    call it ready on that basis."""
    monkeypatch.setattr("fab_test.scripts.fab_test_registry.desktop_ports", list)
    _service_principal_only.write_text(f"PLAYWRIGHT_WORKSPACE_ID={_WS}\n", encoding="utf-8")
    result = check_readiness("pql_test", _args())
    assert result["ready"] is False


def test_no_workspace_anywhere_is_still_not_ready():
    result = check_readiness("playwright", _args())
    assert result["ready"] is False
    assert "FABRIC_WORKSPACE_ID" in result["remediation"]
