"""--headed and --slow-mo: visible browsers for local demonstrations."""

import json
import subprocess
import sys
from argparse import Namespace

import pytest

from fab_test.scripts._config import ConfigError
from fab_test.scripts.playwright_validation.execution_config import ExecutionConfig
from fab_test.scripts.playwright_validation.execution_runtime import (
    EXECUTION_LAUNCH,
    apply_execution_environment,
    configure_pytest_execution,
    launch_overrides,
)

pytestmark = pytest.mark.playwright

PLUGIN = "fab_test.scripts.playwright_validation.execution_plugin"


def test_facade_and_wrapper_accept_the_same_flags():
    from fab_test.scripts.fab_test_parser import build_parser
    from fab_test.scripts.invoke_playwright import parse_args

    facade = build_parser().parse_args(["playwright", "--headed", "--slow-mo", "500"])
    wrapper = parse_args(["--headed", "--slow-mo", "500"])
    assert facade.headed is wrapper.headed is True
    assert facade.slow_mo == wrapper.slow_mo == 500


def test_flags_are_off_by_default_and_not_forwarded(tmp_path):
    from fab_test.scripts.fab_test_parser import build_parser
    from fab_test.scripts.fab_test_registry import build_playwright_command

    args = build_parser().parse_args(["playwright"])
    assert args.headed is False and args.slow_mo is None
    command = build_playwright_command(tmp_path / "Sales.Report", args, tmp_path / "results")
    assert "--headed" not in command and "--slow-mo" not in command


def test_builder_forwards_the_flags(tmp_path):
    from fab_test.scripts.fab_test_parser import build_parser
    from fab_test.scripts.fab_test_registry import build_playwright_command

    args = build_parser().parse_args(["playwright", "--headed", "--slow-mo", "250"])
    command = build_playwright_command(tmp_path / "Sales.Report", args, tmp_path / "results")
    assert "--headed" in command
    assert command[command.index("--slow-mo") + 1] == "250"


def test_local_overrides_hold_only_what_was_asked():
    local = ExecutionConfig()
    assert launch_overrides(Namespace(headed=False, slow_mo=None), local) == {}
    assert launch_overrides(Namespace(headed=True, slow_mo=None), local) == {"headless": False}
    assert launch_overrides(Namespace(headed=False, slow_mo=300), local) == {"slow_mo": 300}


def test_negative_slow_mo_is_refused():
    with pytest.raises(ConfigError, match="slow-mo"):
        launch_overrides(Namespace(headed=False, slow_mo=-1), ExecutionConfig())


def test_azure_ignores_the_flags_and_says_so(capsys):
    azure = ExecutionConfig(backend="azure")
    assert launch_overrides(Namespace(headed=True, slow_mo=100), azure) == {}
    assert "Azure-hosted" in capsys.readouterr().err


def test_overrides_reach_the_child_environment_and_are_cleared_otherwise():
    environment = {EXECUTION_LAUNCH: "stale"}
    apply_execution_environment(environment, Namespace(execution_config=ExecutionConfig(), execution_launch={}))
    assert EXECUTION_LAUNCH not in environment
    args = Namespace(execution_config=ExecutionConfig(), execution_launch={"headless": False})
    apply_execution_environment(environment, args)
    assert json.loads(environment[EXECUTION_LAUNCH]) == {"headless": False}


def test_overrides_load_the_plugin_without_relocating_native_reports():
    command = ["pytest", "--html=old/index.html"]
    configure_pytest_execution(command, {EXECUTION_LAUNCH: '{"headless": false}'})
    assert command == ["pytest", "--html=old/index.html", "-p", PLUGIN]


def test_no_overrides_leaves_the_command_alone():
    command = ["pytest", "--html=old/index.html"]
    configure_pytest_execution(command, {})
    assert command == ["pytest", "--html=old/index.html"]


def test_plugin_applies_overrides_with_no_yaml_selected(tmp_path, monkeypatch):
    (tmp_path / "test_probe.py").write_text(
        "def test_probe(browser_type_launch_args):\n"
        "    assert browser_type_launch_args['headless'] is False\n"
        "    assert browser_type_launch_args['slow_mo'] == 250\n"
    )
    monkeypatch.delenv("FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG", raising=False)
    monkeypatch.setenv(EXECUTION_LAUNCH, '{"headless": false, "slow_mo": 250}')
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_probe.py"), "-q", "-p", "no:cacheprovider", "-p", PLUGIN],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )
    assert result.returncode == 0, result.stdout[-1500:]


def test_cli_overrides_win_over_yaml_launch_settings(tmp_path, monkeypatch):
    config = tmp_path / "local.yml"
    config.write_text("launch:\n  headless: true\n  slow_mo: 10\n")
    (tmp_path / "test_probe.py").write_text(
        "def test_probe(browser_type_launch_args):\n"
        "    assert browser_type_launch_args['headless'] is False\n"
        "    assert browser_type_launch_args['slow_mo'] == 10\n"
    )
    monkeypatch.setenv("FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG", str(config))
    monkeypatch.setenv(EXECUTION_LAUNCH, '{"headless": false}')
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_probe.py"), "-q", "-p", "no:cacheprovider", "-p", PLUGIN],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )
    assert result.returncode == 0, result.stdout[-1500:]
