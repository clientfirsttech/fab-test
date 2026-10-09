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


def test_given_the_runner_installed_should_not_stop_the_run(monkeypatch):
    monkeypatch.setattr(execution_runtime, "missing_runner_message", lambda: None)
    assert fab_test_registry.preflight_error("playwright", argparse.Namespace()) is None


def test_given_the_runner_missing_doctor_should_report_playwright_not_ready(runner_missing):
    ready = {"ready": True, "resolved_path": None, "reason": "workspace configured", "remediation": None}
    result = execution_runtime.execution_readiness(ready, "playwright", argparse.Namespace())
    assert result["ready"] is False
    assert 'pip install "cft-fab-test[playwright]"' in result["remediation"]


def test_given_another_analyzer_should_not_check_the_playwright_runner(runner_missing):
    ready = {"ready": True, "resolved_path": None, "reason": "", "remediation": None}
    assert execution_runtime.execution_readiness(ready, "bpa", argparse.Namespace())["ready"] is True
