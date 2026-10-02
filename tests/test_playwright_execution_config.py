"""Selection and validation of optional browser execution settings."""

from pathlib import Path

import pytest

from fab_test.scripts._config import ConfigError
from fab_test.scripts.playwright_validation.execution_config import resolve_execution_config

pytestmark = pytest.mark.playwright


@pytest.fixture(autouse=True)
def clear_config_env(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_CONFIG_PATH", raising=False)


def write_config(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.write_text(content, encoding="utf-8")
    return path


def test_absent_config_preserves_local_defaults(tmp_path):
    config = resolve_execution_config(repo_root=tmp_path)
    assert config.backend == "local"
    assert config.path is None
    assert config.workers is None
    assert config.launch == {}
    assert config.context == {}
    assert config.origin == "default"


def test_flag_wins_over_environment_and_file(tmp_path, monkeypatch):
    explicit = write_config(tmp_path, "explicit.yml", "backend: azure\nworkers: 8\n")
    monkeypatch.setenv("PLAYWRIGHT_CONFIG_PATH", "missing.yml")
    config = resolve_execution_config(str(explicit), {"playwright_config": "also-missing.yml"}, tmp_path)
    assert config.path == explicit
    assert config.backend == "azure"
    assert config.workers == 8
    assert config.origin == "flag"


def test_environment_wins_over_file(tmp_path, monkeypatch):
    path = write_config(tmp_path, "env.yml", "workers: 2\n")
    monkeypatch.setenv("PLAYWRIGHT_CONFIG_PATH", str(path))
    config = resolve_execution_config(file_config={"playwright_config": "missing.yml"}, repo_root=tmp_path)
    assert config.path == path
    assert config.origin == "env:PLAYWRIGHT_CONFIG_PATH"


def test_file_setting_resolves_against_owning_directory(tmp_path):
    path = write_config(tmp_path, "local.yml", "backend: local\n")
    config = resolve_execution_config(file_config={"playwright_config": "local.yml"}, repo_root=tmp_path)
    assert config.path == path
    assert config.origin == "config:playwright_config"


def test_supported_browser_settings_are_retained(tmp_path):
    path = write_config(tmp_path, "azure.yml", (
        "backend: azure\nworkers: 12\n"
        "launch:\n  headless: true\n  args: [--disable-web-security]\n  slow_mo: 0\n"
        "context:\n  viewport: {width: 1280, height: 720}\n  locale: en-US\n"
        "connection:\n  os: linux\n  timeout_ms: 45000\n  expose_network: <loopback>\n"
    ))
    config = resolve_execution_config(str(path), repo_root=tmp_path)
    assert config.launch["args"] == ["--disable-web-security"]
    assert config.context["viewport"] == {"width": 1280, "height": 720}
    assert config.connection["timeout_ms"] == 45000


@pytest.mark.parametrize("content", [
    "backend: node\n",
    "workers: 0\n",
    "workers: true\n",
    "workers: auto\n",
    "workers: 1.5\n",
    "launch: []\n",
    "launch: {headless: nope}\n",
    "launch: {args: [1]}\n",
    "launch: {slow_mo: -1}\n",
    "context: {viewport: {width: 0, height: 720}}\n",
    "context: {color_scheme: purple}\n",
    "connection: {os: linux}\n",
    "backend: azure\nconnection: {os: macos}\n",
    "backend: azure\nconnection: {timeout_ms: false}\n",
    "backend: azure\nconnection: {expose_network: 123}\n",
    "backend: azure\nconnection: {headers: {Authorization: private-value}}\n",
    "PLAYWRIGHT_SERVICE_ACCESS_TOKEN: private-value\n",
    "test_dir: private-value\n",
    "reporter: private-value\n",
    "[private-value]\n",
    "access_token: [private-value\n",
])
def test_invalid_config_does_not_echo_values(tmp_path, content):
    path = write_config(tmp_path, "invalid.yml", content)
    with pytest.raises(ConfigError, match="playwright-config") as raised:
        resolve_execution_config(str(path), repo_root=tmp_path)
    assert "private-value" not in str(raised.value)


def test_missing_explicit_config_does_not_fall_back(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        resolve_execution_config(str(tmp_path / "missing.yml"), repo_root=tmp_path)


def test_typescript_config_is_not_executed(tmp_path):
    path = write_config(tmp_path, "playwright.config.ts", "throw new Error('private-value');")
    with pytest.raises(ConfigError, match="YAML"):
        resolve_execution_config(str(path), repo_root=tmp_path)


def test_facade_and_wrapper_accept_the_same_selector(tmp_path):
    from fab_test.scripts.fab_test_parser import build_parser
    from fab_test.scripts.invoke_playwright import parse_args

    path = str(tmp_path / "azure.yml")
    args = build_parser().parse_args(["playwright", "--playwright-config", path, "--workers", "8"])
    wrapper = parse_args(["--playwright-config", path, "--workers", "8"])
    assert args.playwright_config == wrapper.playwright_config == path
    assert args.workers == wrapper.workers == 8


def test_command_builder_forwards_config(tmp_path):
    from fab_test.scripts.fab_test_parser import build_parser
    from fab_test.scripts.fab_test_registry import build_playwright_command

    path = str(tmp_path / "azure.yml")
    args = build_parser().parse_args(["playwright", "--playwright-config", path])
    command = build_playwright_command(tmp_path / "Sales.Report", args, tmp_path / "results")
    assert command[command.index("--playwright-config") + 1] == path


def test_global_config_resolves_execution_path_relative_to_itself(tmp_path):
    from fab_test.scripts._config import merged_file_config, validate_config

    owner = tmp_path / "settings"
    owner.mkdir()
    path = write_config(owner, "fab-test.yml", "playwright_config: azure.yml\n")
    merged, _ = merged_file_config(tmp_path, tmp_path / "pyproject.toml", str(path))
    validate_config(merged)
    assert merged["playwright_config"] == str(owner / "azure.yml")


def test_invalid_config_is_refused_before_target_resolution(tmp_path, monkeypatch, capsys):
    from fab_test.scripts import fab_test

    path = write_config(tmp_path, "invalid.yml", "backend: node\n")
    monkeypatch.setattr(fab_test, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["fab-test", "playwright", "--playwright-config", str(path)])
    assert fab_test.main() == 2
    assert "backend must be local or azure" in capsys.readouterr().err


def test_config_show_reports_selection_origin(tmp_path, monkeypatch, capsys):
    import json

    from fab_test.scripts import fab_test

    path = write_config(tmp_path, "azure.yml", "backend: azure\n")
    monkeypatch.setenv("PLAYWRIGHT_CONFIG_PATH", str(path))
    monkeypatch.setattr(fab_test, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["fab-test", "config", "--show", "--format", "json"])
    assert fab_test.main() == 0
    data = json.loads(capsys.readouterr().out)
    rows = data["settings"] if isinstance(data, dict) else data
    selected = next(row for row in rows if row["key"] == "playwright_config")
    assert selected["value"] == str(path)
    assert "PLAYWRIGHT_CONFIG_PATH" in selected["origin"]
