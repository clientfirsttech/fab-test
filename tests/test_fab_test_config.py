"""Config file support, clean-tools cache management, and shell completions.

Scope
-----
[tool.fab-test] pyproject config feeding CLI defaults (CLI flag > env var >
config file), the clean-tools subcommand's cache removal, and the
--print-completion bash/zsh scripts.

    pytest -m fab_test
"""
import argparse
import subprocess
import sys

import pytest

from fab_test.scripts.fab_test import (
    _apply_environment_default,
    _clean_tools,
    _resolve_timeout,
)
from tests.conftest import _TimeoutArgs

# --------------------------------------------------------------------------- #
# Configuration file support (pyproject.toml [tool.fab-test])
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_output_dir_packaged_default_is_fab_test_results(monkeypatch):
    """With no config override, --output-dir defaults to fab-test-results.

    Renamed from analyzer-results before the first release (no installed
    base depended on the old name); nothing previously pinned this value,
    which is how the rename went unverified by the suite.
    """
    from fab_test.scripts import fab_test as fab_test_module
    from fab_test.scripts import fab_test_parser

    monkeypatch.setattr(fab_test_parser, "_PYPROJECT_CONFIG", {})
    parser = fab_test_module.build_parser()
    ns = parser.parse_args(["bpa", "--dry-run"])
    assert ns.output_dir == str(fab_test_module.RESULTS_ROOT)
    assert ns.output_dir.endswith("fab-test-results")


@pytest.mark.fab_test
def test_common_flags_use_pyproject_config_as_default(monkeypatch):
    """--jobs/--format/--artifact-dir/--output-dir default from [tool.fab-test]."""
    from fab_test.scripts import fab_test as fab_test_module
    from fab_test.scripts import fab_test_parser

    # build_parser (and _add_common_flags) live in fab_test_parser since the
    # Fab-Test Module Split epic; that module's own binding of
    # _PYPROJECT_CONFIG is what the parser defaults actually close over.
    monkeypatch.setattr(
        fab_test_parser,
        "_PYPROJECT_CONFIG",
        {
            "jobs": 4,
            "format": "json",
            "artifact_dir": "/configured/artifacts",
            "output_dir": "/configured/results",
        },
    )
    parser = fab_test_module.build_parser()
    ns = parser.parse_args(["bpa", "--dry-run"])
    assert ns.jobs == 4
    assert ns.output_format == "json"
    assert ns.artifact_dir == "/configured/artifacts"
    assert ns.output_dir == "/configured/results"


@pytest.mark.fab_test
def test_common_flags_cli_overrides_pyproject_config(monkeypatch):
    """An explicit CLI flag still wins over the config file default."""
    from fab_test.scripts import fab_test as fab_test_module
    from fab_test.scripts import fab_test_parser

    monkeypatch.setattr(fab_test_parser, "_PYPROJECT_CONFIG", {"jobs": 4})
    parser = fab_test_module.build_parser()
    ns = parser.parse_args(["bpa", "--dry-run", "--jobs", "8"])
    assert ns.jobs == 8


@pytest.mark.fab_test
def test_backward_compat_real_command_with_only_pyproject_config(tmp_path):
    """A repository with only [tool.fab-test] and no fab-test.yml: a real
    fab-test invocation resolves --artifact-dir from pyproject.toml exactly
    as it did before this epic, with no fab-test.yml involved at all.
    """
    artifact_dir = tmp_path / "configured-artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[tool.fab-test]\nartifact_dir = "{artifact_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    assert not (tmp_path / "fab-test.yml").exists()

    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "SampleModel" in result.stdout


@pytest.mark.fab_test
def test_resolve_timeout_uses_config_when_no_cli_or_env(monkeypatch):
    """A config-file timeout is used when neither --timeout nor the env is set."""
    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)
    value, is_default = _resolve_timeout(_TimeoutArgs(timeout=None), config={"timeout": 300})
    assert value == 300
    assert is_default is False


@pytest.mark.fab_test
def test_resolve_timeout_env_overrides_config(monkeypatch):
    """ANALYZER_TIMEOUT still overrides a config-file timeout."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    value, is_default = _resolve_timeout(_TimeoutArgs(timeout=None), config={"timeout": 300})
    assert value == 60
    assert is_default is False


@pytest.mark.fab_test
def test_resolve_timeout_cli_overrides_config_and_env(monkeypatch):
    """An explicit --timeout wins over both env var and config file."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    value, is_default = _resolve_timeout(_TimeoutArgs(timeout=999), config={"timeout": 300})
    assert value == 999
    assert is_default is False


@pytest.mark.fab_test
def test_apply_environment_default_uses_config_when_no_cli_or_env(monkeypatch):
    """--env falls back to [tool.fab-test].environment when unset."""
    monkeypatch.delenv("FABRIC_ENVIRONMENT", raising=False)
    ns = argparse.Namespace(environment="")
    _apply_environment_default(ns, {"environment": "DEV"})
    assert ns.environment == "DEV"


@pytest.mark.fab_test
def test_apply_environment_default_env_overrides_config(monkeypatch):
    """FABRIC_ENVIRONMENT still overrides a config-file environment default."""
    monkeypatch.setenv("FABRIC_ENVIRONMENT", "PROD")
    ns = argparse.Namespace(environment="")
    _apply_environment_default(ns, {"environment": "DEV"})
    assert ns.environment == "PROD"


@pytest.mark.fab_test
def test_apply_environment_default_cli_value_not_overwritten(monkeypatch):
    """An explicit --env value is never replaced by env var or config."""
    monkeypatch.setenv("FABRIC_ENVIRONMENT", "PROD")
    ns = argparse.Namespace(environment="STAGE")
    _apply_environment_default(ns, {"environment": "DEV"})
    assert ns.environment == "STAGE"


@pytest.mark.fab_test
def test_apply_environment_default_noop_when_no_environment_attr():
    """Subcommands without an --env flag are left untouched."""
    ns = argparse.Namespace()
    _apply_environment_default(ns, {"environment": "DEV"})
    assert not hasattr(ns, "environment")


@pytest.mark.fab_test
def test_main_applies_environment_default_before_dispatch(monkeypatch):
    """main() merges the config/env default for --env before running analyzers."""
    from fab_test.scripts import fab_test as fab_test_module

    calls = []
    monkeypatch.setattr(
        fab_test_module,
        "_apply_environment_default",
        lambda args, config: calls.append((args.analyzer, config)),
    )
    monkeypatch.setattr(sys, "argv", ["fab-test", "pql_test", "--dry-run"])
    fab_test_module.main()
    assert calls and calls[0][0] == "pql_test"


# --------------------------------------------------------------------------- #
# Tool-cache management command (clean-tools)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_clean_tools_help_exits_zero():
    """fab-test clean-tools --help exits 0."""
    result = subprocess.run(
        ["fab-test", "clean-tools", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_clean_tools_removes_existing_cache_dir(tmp_path, capsys):
    """clean-tools deletes .fab-test-tools and prints a confirmation."""
    cache_dir = tmp_path / ".fab-test-tools"
    (cache_dir / "pbir_inspector").mkdir(parents=True)
    (cache_dir / "pbir_inspector" / "tool.exe").write_text("x", encoding="utf-8")

    code = _clean_tools(tmp_path, dry_run=False)
    captured = capsys.readouterr()

    assert code == 0
    assert not cache_dir.exists()
    assert "removed" in captured.out
    assert str(cache_dir) in captured.out


@pytest.mark.fab_test
def test_clean_tools_dry_run_lists_without_deleting(tmp_path, capsys):
    """--dry-run lists what would be removed without deleting anything."""
    cache_dir = tmp_path / ".fab-test-tools"
    (cache_dir / "pbir_inspector").mkdir(parents=True)
    (cache_dir / "pbir_inspector" / "tool.exe").write_text("x", encoding="utf-8")

    code = _clean_tools(tmp_path, dry_run=True)
    captured = capsys.readouterr()

    assert code == 0
    assert cache_dir.exists()
    assert (cache_dir / "pbir_inspector" / "tool.exe").exists()
    assert "tool.exe" in captured.out


@pytest.mark.fab_test
def test_clean_tools_nothing_to_clean_when_missing(tmp_path):
    """A missing .fab-test-tools cache exits cleanly with a clear message."""
    code = _clean_tools(tmp_path, dry_run=False)

    assert code == 0


@pytest.mark.fab_test
def test_clean_tools_names_each_cached_analyzer_platform_version(tmp_path, capsys):
    """A real (version-keyed) cache layout is reported by analyzer/platform/version,
    not just as one generic ".fab-test-tools removed" line.
    """
    cache_dir = tmp_path / ".fab-test-tools"
    extracted = cache_dir / "pbir_inspector" / "win32" / "3.4.0" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "fab-inspector.exe").write_text("x", encoding="utf-8")

    code = _clean_tools(tmp_path, dry_run=False)
    captured = capsys.readouterr()

    assert code == 0
    assert not cache_dir.exists()
    assert "pbir_inspector/win32/3.4.0" in captured.out


@pytest.mark.fab_test
def test_clean_tools_dry_run_names_each_cached_version_without_deleting(tmp_path, capsys):
    """--dry-run against a real cache layout lists each version, deletes nothing."""
    cache_dir = tmp_path / ".fab-test-tools"
    extracted = cache_dir / "tabular_editor_bpa" / "win32" / "2.28.0" / "extracted"
    extracted.mkdir(parents=True)
    (extracted / "TabularEditor.exe").write_text("x", encoding="utf-8")

    code = _clean_tools(tmp_path, dry_run=True)
    captured = capsys.readouterr()

    assert code == 0
    assert cache_dir.exists()
    assert "tabular_editor_bpa/win32/2.28.0" in captured.out


@pytest.mark.fab_test
def test_main_clean_tools_dispatches_correctly(tmp_path, monkeypatch, capsys):
    """main() routes the clean-tools subcommand to _clean_tools."""
    from fab_test.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["fab-test", "clean-tools"])

    code = fab_test_module.main()
    captured = capsys.readouterr()

    assert code == 0
    assert "nothing to clean" in captured.out


# --------------------------------------------------------------------------- #
# Shell completions
# --------------------------------------------------------------------------- #

_SUBCOMMAND_NAMES = (
    "bpa",
    "pbir",
    "pql-test",
    "pql-lint",
    "playwright",
    "playwright-impact",
    "dependencies",
    "all",
    "clean-tools",
)


@pytest.mark.fab_test
def test_print_completion_bash_exits_zero_and_writes_to_stdout():
    """--print-completion bash writes a bash completion script to stdout."""
    result = subprocess.run(
        ["fab-test", "--print-completion", "bash"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "complete -F" in result.stdout
    assert "fab-test" in result.stdout


@pytest.mark.fab_test
def test_print_completion_zsh_exits_zero_and_writes_to_stdout():
    """--print-completion zsh writes a zsh completion script to stdout."""
    result = subprocess.run(
        ["fab-test", "--print-completion", "zsh"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "#compdef" in result.stdout


@pytest.mark.fab_test
def test_print_completion_invalid_shell_exits_2():
    """--print-completion only accepts bash or zsh."""
    result = subprocess.run(
        ["fab-test", "--print-completion", "fish"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout


@pytest.mark.fab_test
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_print_completion_lists_all_subcommands(shell):
    """Both completion scripts enumerate every fab-test subcommand."""
    result = subprocess.run(
        ["fab-test", "--print-completion", shell],
        capture_output=True,
        text=True,
        check=False,
    )
    for name in _SUBCOMMAND_NAMES:
        assert name in result.stdout, f"{name} missing from {shell} completion script"


@pytest.mark.fab_test
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_print_completion_completes_common_flags(shell):
    """Both completion scripts offer common flags like --artifact-dir."""
    result = subprocess.run(
        ["fab-test", "--print-completion", shell],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "--artifact-dir" in result.stdout
    assert "--dry-run" in result.stdout


@pytest.mark.fab_test
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_print_completion_completes_artifact_stems_dynamically(shell):
    """Both scripts look up artifact stems from fabric-artifacts at completion time."""
    result = subprocess.run(
        ["fab-test", "--print-completion", shell],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "fabric-artifacts" in result.stdout


