"""Top-level help, the `help` subcommand, unknown analyzers, and --version.

Scope
-----
--help / -V output, the `help` subcommand (topic lookup and unknown-topic
errors), unknown-analyzer suggestions, and the per-analyzer --help text --
the surface a caller reads before running anything.

    pytest -m fab_test
"""
import argparse
import subprocess
from pathlib import Path

import pytest

from fabric_ci_cd_dataops import __version__ as fab_test_version
from fabric_ci_cd_dataops.scripts.fab_test_registry import build_pql_test_command

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / ".fabric" / "artifacts"

# pql_lint is deliberately absent: it is hidden from the advertised surface
# (see HIDDEN_ANALYZERS and tests/test_hidden_analyzers.py) while remaining
# fully invocable.
_ALL_SUBCOMMANDS = ("bpa", "pbir", "pql_test", "all")


# --------------------------------------------------------------------------- #
# Top-level help
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_cli_help_exits_zero():
    """fab-test --help exits 0."""
    result = subprocess.run(
        ["fab-test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_cli_help_lists_all_subcommands():
    """--help must mention every subcommand so users can discover them."""
    result = subprocess.run(
        ["fab-test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    for name in _ALL_SUBCOMMANDS:
        assert name in result.stdout, f"subcommand '{name}' missing from --help"


@pytest.mark.fab_test
def test_cli_help_distinguishes_from_pytest():
    """--help output must state that fab-test is not pytest."""
    result = subprocess.run(
        ["fab-test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "pytest" in result.stdout.lower(), (
        "fab-test --help should mention pytest to clarify the separation"
    )


@pytest.mark.fab_test
def test_cli_help_shows_version_and_docs():
    """--help output should include the current version and documentation link."""
    result = subprocess.run(
        ["fab-test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fab_test_version in result.stdout, "--help should show the package version"
    assert "github.com/kerski/fab-test" in result.stdout, (
        "--help should link to project documentation"
    )


# --------------------------------------------------------------------------- #
# `fab-test help` — the git spelling, for anyone who reaches for it first
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_help_subcommand_prints_the_same_text_as_the_flag():
    bare = subprocess.run(
        ["fab-test", "help"], capture_output=True, text=True, check=False
    )
    flag = subprocess.run(
        ["fab-test", "--help"], capture_output=True, text=True, check=False
    )

    assert bare.returncode == 0, bare.stderr
    assert bare.stdout == flag.stdout


@pytest.mark.fab_test
def test_help_subcommand_takes_a_topic():
    """`fab-test help bpa` is `fab-test bpa --help`."""
    result = subprocess.run(
        ["fab-test", "help", "bpa"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "--bpa-rules-path" in result.stdout


@pytest.mark.fab_test
def test_help_subcommand_rejects_an_unknown_topic():
    result = subprocess.run(
        ["fab-test", "help", "nonsense"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 2
    assert "unknown analyzer 'nonsense'" in result.stderr


@pytest.mark.fab_test
def test_help_is_listed_as_a_subcommand():
    """It only helps the caller who does not know about --help if it is visible."""
    result = subprocess.run(
        ["fab-test", "--help"], capture_output=True, text=True, check=False
    )

    assert "\n    help " in result.stdout, result.stdout


@pytest.mark.fab_test
def test_help_works_even_when_the_config_file_is_broken(tmp_path):
    """Help is what you reach for when something is already wrong."""
    broken = tmp_path / "fab-test.yml"
    broken.write_text("timeout: not-a-number\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "--config", str(broken), "help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout


# --------------------------------------------------------------------------- #
# Unknown analyzer
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_unknown_analyzer_suggests_the_closest_command():
    result = subprocess.run(
        ["fab-test", "doctr"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 2
    assert "did you mean 'fab-test doctor'?" in result.stderr


@pytest.mark.fab_test
def test_unknown_analyzer_without_a_near_miss_just_lists_the_commands():
    result = subprocess.run(
        ["fab-test", "zzzzzzzz"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 2
    assert "did you mean" not in result.stderr
    assert "choose from bpa, pbir" in result.stderr


# --------------------------------------------------------------------------- #
# Version
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_cli_version_exits_zero():
    """fab-test --version exits 0 and prints the package version."""
    result = subprocess.run(
        ["fab-test", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert fab_test_version in result.stdout
    assert "fab-test" in result.stdout.lower()


@pytest.mark.fab_test
def test_cli_version_short_flag():
    """fab-test -V behaves the same as --version."""
    result = subprocess.run(
        ["fab-test", "-V"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert fab_test_version in result.stdout


# --------------------------------------------------------------------------- #
# Subcommand help — one per analyzer
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_bpa_help_exits_zero():
    """fab-test bpa --help exits 0."""
    result = subprocess.run(
        ["fab-test", "bpa", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_bpa_help_shows_required_flags():
    """bpa help must document all BPA-specific flags."""
    result = subprocess.run(
        ["fab-test", "bpa", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    flags = (
        "--tabular-editor-path",
        "--bpa-rules-path",
        "--dry-run",
        "--artifact",
    )
    for flag in flags:
        assert flag in result.stdout, f"{flag} missing from 'bpa --help'"


@pytest.mark.fab_test
def test_pbir_help_shows_inspector_path():
    """pbir help must document --inspector-path."""
    result = subprocess.run(
        ["fab-test", "pbir", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--inspector-path" in result.stdout
    assert "--rules-path" in result.stdout


@pytest.mark.fab_test
def test_pql_test_help_exits_zero():
    """fab-test pql_test --help exits 0."""
    result = subprocess.run(
        ["fab-test", "pql_test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout


@pytest.mark.fab_test
def test_bpa_verbose_flag_accepted():
    """fab-test bpa -v is accepted without error."""
    result = subprocess.run(
        ["fab-test", "bpa", "-v", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_bpa_verbose_long_flag_accepted():
    """fab-test bpa --verbose is accepted without error."""
    result = subprocess.run(
        ["fab-test", "bpa", "--verbose", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_pql_lint_help_exits_zero():
    """fab-test pql_lint --help exits 0."""
    result = subprocess.run(
        ["fab-test", "pql_lint", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout


@pytest.mark.fab_test
def test_pql_test_help_lists_workspace_id_flag():
    """pql_test help must document the --workspace-id flag."""
    result = subprocess.run(
        ["fab-test", "pql_test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--workspace-id" in result.stdout


@pytest.mark.fab_test
def test_build_pql_test_command_forwards_workspace_id():
    """pql_test --workspace-id X forwards --workspace-id X to invoke_pql_test.py."""
    artifact = ARTIFACT_ROOT / "SampleModel-PQLAssert.SemanticModel"
    if not artifact.exists():
        pytest.skip("SampleModel-PQLAssert.SemanticModel not present")

    args = argparse.Namespace(
        workspace_id="workspace-123",
        environment="DEV",
    )
    cmd = build_pql_test_command(artifact, args, REPO_ROOT / "fab-test-results")
    assert "--workspace-id" in cmd
    idx = cmd.index("--workspace-id")
    assert cmd[idx + 1] == "workspace-123"
    assert "--env" in cmd
    env_idx = cmd.index("--env")
    assert cmd[env_idx + 1] == "DEV"


@pytest.mark.fab_test
def test_build_pql_test_command_uses_fabric_workspace_id_env(monkeypatch):
    """build_pql_test_command falls back to FABRIC_WORKSPACE_ID env var."""
    artifact = ARTIFACT_ROOT / "SampleModel-PQLAssert.SemanticModel"
    if not artifact.exists():
        pytest.skip("SampleModel-PQLAssert.SemanticModel not present")

    args = argparse.Namespace(
        workspace_id="",
        environment="",
    )
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "env-workspace-456")
    monkeypatch.setenv("FABRIC_ENVIRONMENT", "TEST")
    cmd = build_pql_test_command(artifact, args, REPO_ROOT / "fab-test-results")
    assert "--workspace-id" in cmd
    idx = cmd.index("--workspace-id")
    assert cmd[idx + 1] == "env-workspace-456"
    assert "--env" in cmd
    env_idx = cmd.index("--env")
    assert cmd[env_idx + 1] == "TEST"


