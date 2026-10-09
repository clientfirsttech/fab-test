"""Remote connection and worker semantics for generated Python report tests."""

import argparse
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from fab_test.scripts._config import ConfigError
from fab_test.scripts.playwright_validation.execution_config import ExecutionConfig
from fab_test.scripts.playwright_validation.execution_runtime import (
    browser_connection_options,
    execution_failure,
    missing_runner_message,
    resolve_workers,
    service_environment,
)

pytestmark = pytest.mark.playwright


def test_local_needs_no_service_credentials(tmp_path):
    assert service_environment(ExecutionConfig(), tmp_path / "missing.env") == {}
    assert browser_connection_options(ExecutionConfig(), {}, "run") is None


def test_service_process_environment_wins_over_env_file(tmp_path, monkeypatch):
    path = tmp_path / "service.env"
    path.write_text("PLAYWRIGHT_SERVICE_URL=wss://example.test/browsers\nPLAYWRIGHT_SERVICE_ACCESS_TOKEN=file-token\n")
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "process-token")
    monkeypatch.delenv("PLAYWRIGHT_SERVICE_URL", raising=False)
    settings = service_environment(ExecutionConfig(backend="azure"), path)
    assert settings["PLAYWRIGHT_SERVICE_ACCESS_TOKEN"] == "process-token"
    assert settings["PLAYWRIGHT_SERVICE_URL"] == "wss://example.test/browsers"


def test_azure_connection_uses_verified_contract():
    options = browser_connection_options(
        ExecutionConfig(backend="azure", connection={"os": "windows", "timeout_ms": 45000}),
        {"PLAYWRIGHT_SERVICE_URL": "wss://example.test/browsers", "PLAYWRIGHT_SERVICE_ACCESS_TOKEN": "test-token"},
        "run-id",
    )
    assert parse_qs(urlsplit(options["endpoint"]).query) == {
        "runId": ["run-id"], "os": ["windows"],
        "sourceType": ["PlaywrightWorkspacesTestRun"], "api-version": ["2025-09-01"],
    }
    assert options["headers"]["Authorization"] == "Bearer test-token"
    assert options["timeout"] == 45000
    assert "test-token" not in options["endpoint"]


def test_missing_service_token_names_the_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", "wss://example.test/browsers")
    with pytest.raises(ValueError, match="PLAYWRIGHT_SERVICE_ACCESS_TOKEN"):
        service_environment(ExecutionConfig(backend="azure"), tmp_path / "missing.env")


@pytest.mark.parametrize("url", ["https://example.test", "wss://user:password@example.test", "wss://example.test?token=value"])
def test_unsafe_service_endpoint_does_not_echo_credentials(tmp_path, monkeypatch, url):
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", url)
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "private-value")
    with pytest.raises(ConfigError, match="PLAYWRIGHT_SERVICE_URL") as raised:
        service_environment(ExecutionConfig(backend="azure"), tmp_path / "missing.env")
    assert "private-value" not in str(raised.value)
    assert url not in str(raised.value)


def test_worker_precedence(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_XDIST_WORKERS", "6")
    config = ExecutionConfig(workers=8)
    assert resolve_workers(config, 2) == 2
    assert resolve_workers(config) == 6
    monkeypatch.delenv("PLAYWRIGHT_XDIST_WORKERS")
    assert resolve_workers(config) == 8
    assert resolve_workers(ExecutionConfig()) == 4


@pytest.mark.parametrize("workers", [0, -1])
def test_invalid_explicit_worker_limit_is_refused(workers):
    with pytest.raises(ConfigError, match="workers"):
        resolve_workers(ExecutionConfig(), workers)


def test_unexecuted_case_is_a_tool_error_not_visual_failure(tmp_path):
    assert "did not execute" in execution_failure(1, [tmp_path / "case"])
    assert execution_failure(0, []) is None


def test_actual_case_failure_is_not_a_setup_error(tmp_path):
    case = tmp_path / "case"
    case.mkdir()
    (case / "result.json").write_text('{"status":"fail"}')
    assert execution_failure(1, [case]) is None
    assert "pytest" in execution_failure(4, [case])


def test_wrapper_refuses_missing_service_credentials_before_fabric(tmp_path, monkeypatch):
    from fab_test.scripts import invoke_playwright

    config = tmp_path / "azure.yml"
    config.write_text("backend: azure\n")
    monkeypatch.delenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", "wss://example.test/browsers")
    args = invoke_playwright.parse_args([
        "--playwright-config", str(config), "--env-file", str(tmp_path / "missing.env"),
    ])
    monkeypatch.setattr(invoke_playwright, "_build_config_from_args", lambda args: pytest.fail("Fabric was called"))
    assert invoke_playwright.run_playwright_validation(args) == 127


@pytest.mark.parametrize("selected", [False, True])
def test_native_reports_follow_selected_execution_root(tmp_path, selected):
    from fab_test.scripts.playwright_validation.execution_runtime import configure_pytest_execution

    command = ["pytest", "--html=old/index.html", "--junitxml=old/results.xml"]
    environment = {"PLAYWRIGHT_RESULTS_ROOT": str(tmp_path)}
    if selected:
        environment["FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG"] = "settings.yml"
    configure_pytest_execution(command, environment)
    if selected:
        assert f"--html={tmp_path / 'report' / 'index.html'}" in command
        assert f"--junitxml={tmp_path / 'report' / 'results.xml'}" in command
        assert "fab_test.scripts.playwright_validation.execution_plugin" in command
    else:
        assert command == ["pytest", "--html=old/index.html", "--junitxml=old/results.xml"]


def test_browser_connection_failure_withholds_raw_authorization():
    from playwright.sync_api import Error

    from fab_test.scripts.playwright_validation import execution_plugin

    def reject_connection(**kwargs):
        raise Error("response: 401 Authorization: Bearer private-test-token")

    launch = execution_plugin.ExecutionFixtures.launch_browser.__wrapped__(None, reject_connection)
    with pytest.raises(pytest.fail.Exception) as raised:
        launch()
    assert "HTTP 401" in str(raised.value)
    assert "private-test-token" not in str(raised.value)
    assert "Authorization" not in str(raised.value)


@pytest.mark.parametrize("selected", [False, True])
def test_selected_rerun_clears_old_case_evidence(tmp_path, selected):
    from argparse import Namespace

    from fab_test.scripts.playwright_validation.execution_runtime import apply_execution_environment

    case = tmp_path / "case"
    case.mkdir()
    screenshot = case / "screenshot.png"
    screenshot.write_bytes(b"old screenshot")
    args = Namespace(
        execution_config=ExecutionConfig(path=tmp_path / "local.yml" if selected else None),
        execution_environment={},
    )
    apply_execution_environment({}, args, [case])
    assert screenshot.exists() is not selected


def test_diagnostic_writer_redacts_service_and_embed_tokens_before_persistence(tmp_path, monkeypatch):
    from fab_test.scripts.playwright_validation.execution_runtime import write_execution_text

    monkeypatch.setenv("FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG", "settings.yml")
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "private-service-token")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "private-client-secret")
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIGS", '{"role":{"accessToken":"private-embed-token"}}')
    path = tmp_path / "diagnostics.txt"
    write_execution_text(path, "private-service-token private-client-secret private-embed-token")
    assert path.read_text() == "[REDACTED] [REDACTED] [REDACTED]"


def test_selected_azure_options_override_pytest_playwright_default(tmp_path, monkeypatch):
    import subprocess
    import sys

    (tmp_path / "test_probe.py").write_text(
        "def test_probe(connect_options):\n    assert any(key.endswith('endpoint') for key in connect_options)\n"
    )
    config = tmp_path / "azure.yml"
    config.write_text("backend: azure\n")
    monkeypatch.setenv("FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG", str(config))
    monkeypatch.setenv("FAB_TEST_PLAYWRIGHT_RUN_ID", "run")
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_URL", "wss://example.test/browsers")
    monkeypatch.setenv("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "test-token")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_probe.py"), "-q", "-p", "no:cacheprovider",
         "-p", "fab_test.scripts.playwright_validation.execution_plugin"],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )
    assert result.returncode == 0, result.stdout[-1500:]


def test_native_report_root_follows_envelope_not_custom_case_directory(tmp_path):
    from fab_test.scripts.playwright_validation.execution_runtime import configure_pytest_execution

    command = ["pytest", "--html=old/index.html", "--junitxml=old/results.xml"]
    report_root = tmp_path / "artifact" / "report"
    environment = {
        "FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG": "settings.yml",
        "PLAYWRIGHT_RESULTS_ROOT": str(tmp_path / "custom-cases"),
        "FAB_TEST_PLAYWRIGHT_REPORT_ROOT": str(report_root),
    }
    configure_pytest_execution(command, environment)
    assert f"--html={report_root / 'index.html'}" in command
    assert f"--junitxml={report_root / 'results.xml'}" in command


def test_playwright_extra_installs_every_runner_package():
    from fab_test.scripts.playwright_validation import execution_runtime

    pyproject = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert set(pyproject["project"]["optional-dependencies"]["playwright"]) == set(execution_runtime._RUNNER_MODULES)


def test_missing_runner_packages_are_named_with_the_install_command(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None if name in ("pytest", "xdist") else real(name))
    message = missing_runner_message()
    assert "pytest, pytest-xdist" in message
    assert 'pip install "cft-fab-test[playwright]"' in message


def test_installed_runner_packages_need_no_message():
    assert missing_runner_message() is None


def test_missing_runner_aborts_before_minting_a_token(tmp_path, monkeypatch):
    from fab_test.scripts import invoke_playwright
    from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig

    config = PlaywrightValidationConfig(
        workspace_id="ws-1", report_id="rpt-1", report_name="Report", dataset_id="ds-1",
        page_ids=[], bookmark_ids=[], user_name="", role="", use_rls=False, cloud="public",
        client_id="c", client_secret="s", tenant_id="t", timeout_seconds=60, headless=True,
    )
    monkeypatch.setattr(invoke_playwright, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(invoke_playwright, "resolve_discovery", lambda *a: (None, None))
    monkeypatch.setattr(invoke_playwright, "missing_runner_message", lambda: "need pytest")
    monkeypatch.setattr(invoke_playwright, "acquire_embed_configs", lambda *a: pytest.fail("token minted"))
    output = tmp_path / "envelope.json"
    assert invoke_playwright.main(["--env-file", ".env", "--output-path", str(output)]) == 1
    assert "need pytest" in output.read_text(encoding="utf-8")


def test_native_reports_follow_the_envelope_without_an_execution_config(tmp_path):
    """pytest's HTML/JUnit reports go beside the envelope, under --output-dir, for every run.

    Found live (Workspace Discovery, 2026-10-09): without an execution config they
    went to a fixed ./fab-test-results/playwright/report/ shared by every report.
    """
    from fab_test.scripts.playwright_validation.execution_runtime import (
        EXECUTION_REPORT_ROOT,
        apply_execution_environment,
        configure_pytest_execution,
    )

    report_root = tmp_path / "out" / "playwright" / "Sales" / "report"
    environment: dict[str, str] = {}
    apply_execution_environment(environment, argparse.Namespace(), report_root=report_root)
    assert environment[EXECUTION_REPORT_ROOT] == str(report_root)

    command = ["pytest", "--html=old/index.html", "--junitxml=old/results.xml"]
    configure_pytest_execution(command, environment)
    assert command == ["pytest", f"--html={report_root / 'index.html'}", f"--junitxml={report_root / 'results.xml'}"]
