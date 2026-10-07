"""PLAYWRIGHT_HEADLESS=false shows the local browser window (lowest precedence)."""

import subprocess
import sys

import pytest

from fab_test.scripts.playwright_validation.execution_config import ExecutionConfig
from fab_test.scripts.playwright_validation.execution_runtime import (
    EXECUTION_LAUNCH,
    configure_pytest_execution,
    warn_ignored_headless,
)

pytestmark = pytest.mark.playwright

PLUGIN = "fab_test.scripts.playwright_validation.execution_plugin"


@pytest.mark.parametrize("value", ["false", "False", "FALSE"])
def test_headless_false_loads_the_plugin(value):
    command = ["pytest"]
    configure_pytest_execution(command, {"PLAYWRIGHT_HEADLESS": value})
    assert command == ["pytest", "-p", PLUGIN]


@pytest.mark.parametrize("environment", [{}, {"PLAYWRIGHT_HEADLESS": "true"}, {"PLAYWRIGHT_HEADLESS": ""}])
def test_default_and_true_leave_the_command_alone(environment):
    command = ["pytest"]
    configure_pytest_execution(command, environment)
    assert command == ["pytest"]


def _probe(tmp_path, monkeypatch, body, *, headless="false", yaml=None, launch=None):
    (tmp_path / "test_probe.py").write_text(f"def test_probe(browser_type_launch_args):\n    {body}\n")
    monkeypatch.delenv(EXECUTION_LAUNCH, raising=False)
    monkeypatch.delenv("FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", headless)
    if yaml:
        path = tmp_path / "config.yml"
        path.write_text(yaml)
        monkeypatch.setenv("FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG", str(path))
    if launch:
        monkeypatch.setenv(EXECUTION_LAUNCH, launch)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_probe.py"), "-q", "-p", "no:cacheprovider", "-p", PLUGIN],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )


def test_headless_false_launches_a_visible_browser(tmp_path, monkeypatch):
    result = _probe(tmp_path, monkeypatch, "assert browser_type_launch_args['headless'] is False")
    assert result.returncode == 0, result.stdout[-1500:]


def test_yaml_launch_setting_beats_the_environment(tmp_path, monkeypatch):
    result = _probe(
        tmp_path, monkeypatch, "assert browser_type_launch_args['headless'] is True",
        yaml="launch:\n  headless: true\n",
    )
    assert result.returncode == 0, result.stdout[-1500:]


def test_cli_override_beats_yaml_and_environment(tmp_path, monkeypatch):
    result = _probe(
        tmp_path, monkeypatch, "assert browser_type_launch_args['headless'] is False",
        headless="true", yaml="launch:\n  headless: true\n", launch='{"headless": false}',
    )
    assert result.returncode == 0, result.stdout[-1500:]


def test_azure_ignores_the_environment_setting(tmp_path, monkeypatch):
    result = _probe(
        tmp_path, monkeypatch, "assert browser_type_launch_args.get('headless') is not False", yaml="backend: azure\n",
    )
    assert result.returncode == 0, result.stdout[-1500:]


def test_azure_with_headless_false_warns_once(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / "service.env"
    env_file.write_text("PLAYWRIGHT_HEADLESS=false\n")
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)
    warn_ignored_headless(ExecutionConfig(backend="azure"), env_file)
    assert "Azure-hosted" in capsys.readouterr().err


@pytest.mark.parametrize("backend, value", [("azure", "true"), ("local", "false")])
def test_no_warning_unless_azure_and_headless_false(tmp_path, monkeypatch, capsys, backend, value):
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", value)
    warn_ignored_headless(ExecutionConfig(backend=backend), tmp_path / "missing.env")
    assert capsys.readouterr().err == ""
