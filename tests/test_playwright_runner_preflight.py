"""A missing Playwright runner is a setup problem (127), not failed cases (Standalone bug, 2026-09-29).

Without the `playwright` extra's pytest packages, `fab-test playwright` used
to write a `visual_load_failed` error for every case and exit 1 -- a missing
install read as a rendering verdict -- and `doctor` reported playwright ready.
Now the parent's preflight stops first with 127 naming the install command,
the same contract as every other missing tool, and `doctor` agrees.
"""

import argparse

import pytest

from fab_test.scripts import fab_test_registry
from fab_test.scripts.playwright_validation import execution_runtime

pytestmark = pytest.mark.playwright

MESSAGE = (
    "Playwright runs need pytest-html, which this environment does not have. "
    'Install them with: pip install "cft-fab-test[playwright]"'
)


@pytest.fixture
def runner_missing(monkeypatch):
    monkeypatch.setattr(execution_runtime, "missing_runner_message", lambda: MESSAGE)


def test_given_the_runner_missing_should_stop_before_the_run_with_127(runner_missing):
    message, code = fab_test_registry.preflight_error("playwright", argparse.Namespace())
    assert code == 127
    assert 'pip install "cft-fab-test[playwright]"' in message


def test_given_plan_only_should_not_need_the_runner(runner_missing):
    assert fab_test_registry.preflight_error("playwright", argparse.Namespace(plan_only=True)) is None


_SP_VARS = (
    "FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
    "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET", "PLAYWRIGHT_ENV_FILE",
)


@pytest.fixture
def runner_installed(monkeypatch, tmp_path):
    """Runner present, no service principal anywhere; returns args pointing at an empty .env."""
    monkeypatch.setattr(execution_runtime, "missing_runner_message", lambda: None)
    for name in _SP_VARS:
        monkeypatch.delenv(name, raising=False)
    return argparse.Namespace(playwright_env_file=str(tmp_path / "missing.env"))


def test_given_the_runner_and_a_service_principal_should_not_stop_the_run(runner_installed, monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "t")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "c")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "s")
    assert fab_test_registry.preflight_error("playwright", runner_installed) is None


def test_given_no_service_principal_should_stop_once_before_fanning_out_with_127(runner_installed):
    """Every artifact would refuse at the same check, so the parent says it once instead of N times."""
    message, code = fab_test_registry.preflight_error("playwright", runner_installed)
    assert code == 127
    assert "full service principal" in message
    assert "FABRIC_CLIENT_SECRET" in message


def test_given_a_partial_service_principal_should_name_what_is_missing(runner_installed, monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "t")
    message, code = fab_test_registry.preflight_error("playwright", runner_installed)
    assert code == 127
    assert "partially configured" in message


def test_given_the_service_principal_in_the_env_file_should_not_stop_the_run(runner_installed, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FABRIC_TENANT_ID=t\nFABRIC_CLIENT_ID=c\nFABRIC_CLIENT_SECRET=s\n", encoding="utf-8")
    runner_installed.playwright_env_file = str(env_file)
    assert fab_test_registry.preflight_error("playwright", runner_installed) is None


def test_given_plan_only_should_not_need_a_service_principal(runner_installed):
    runner_installed.plan_only = True
    assert fab_test_registry.preflight_error("playwright", runner_installed) is None


def test_given_the_runner_missing_doctor_should_report_playwright_not_ready(runner_missing):
    ready = {"ready": True, "resolved_path": None, "reason": "workspace configured", "remediation": None}
    result = execution_runtime.execution_readiness(ready, "playwright", argparse.Namespace())
    assert result["ready"] is False
    assert 'pip install "cft-fab-test[playwright]"' in result["remediation"]


def test_given_another_analyzer_should_not_check_the_playwright_runner(runner_missing):
    ready = {"ready": True, "resolved_path": None, "reason": "", "remediation": None}
    assert execution_runtime.execution_readiness(ready, "bpa", argparse.Namespace())["ready"] is True
