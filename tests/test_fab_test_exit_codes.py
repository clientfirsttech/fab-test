"""Exit codes: error/warning threshold, platform preflight, input validation.

Scope
-----
_artifact_exit_code's error-vs-warning distinction, preflight_error's
platform-mismatch (126) and missing-tool (127) codes, _run_analyzer's
fail-fast on an unsupported platform, and CLI input validation (workspace
GUID, --artifact-dir, --format) that exits 2 before any analyzer runs.

    pytest -m fab_test
"""
import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import UnsupportedPlatformError
from fabric_ci_cd_dataops.scripts.fab_test import _artifact_exit_code, _run_analyzer
from fabric_ci_cd_dataops.scripts.fab_test_registry import preflight_error
from tests.conftest import _RunAnalyzerArgs

# --------------------------------------------------------------------------- #
# Error vs warning threshold
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_artifact_exit_code_warnings_only_returns_zero():
    """A run that produces only warnings must exit 0 even if the tool exited 1."""
    envelope = {
        "status": "failed",
        "findings": [{"rule": "R1", "severity": "Warning"}],
    }
    assert _artifact_exit_code(1, envelope) == 0


@pytest.mark.fab_test
def test_artifact_exit_code_errors_returns_one():
    """A run that produces any errors must exit 1."""
    envelope = {
        "status": "failed",
        "findings": [{"rule": "R1", "severity": "Error"}],
    }
    assert _artifact_exit_code(0, envelope) == 1


@pytest.mark.fab_test
def test_artifact_exit_code_crash_with_no_findings_returns_one():
    """A tool crash with no findings must exit 1."""
    assert _artifact_exit_code(1, None) == 1


@pytest.mark.fab_test
def test_artifact_exit_code_clean_run_returns_zero():
    """A clean run with no findings must exit 0."""
    assert _artifact_exit_code(0, {"findings": []}) == 0


@pytest.mark.fab_test
def test_cli_help_lists_exit_codes():
    """--help epilog documents every exit code and its meaning, for CI branching."""
    result = subprocess.run(
        ["fab-test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Exit codes:" in result.stdout
    for code in ("0", "1", "2", "126", "127"):
        assert code in result.stdout, f"exit code {code} missing from --help epilog"


@pytest.mark.fab_test
def test_cli_invalid_argument_exits_with_code_2():
    """An unrecognized flag must exit 2 before any analyzer runs."""
    result = subprocess.run(
        ["fab-test", "bpa", "--not-a-real-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stderr


@pytest.mark.fab_test
def test_preflight_error_platform_mismatch_returns_exit_code_126(monkeypatch):
    """A platform-only analyzer on an unsupported OS reports exit code 126."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    def _raise_unsupported(*_args, **_kwargs):
        raise UnsupportedPlatformError(
            "Analyzer 'bpa' is not supported on linux. Supported platform: win32."
        )

    monkeypatch.setattr(registry, "resolve_tool", _raise_unsupported)
    message, code = preflight_error("bpa", argparse.Namespace())
    assert code == 126
    assert "not supported on linux" in message


@pytest.mark.fab_test
def test_preflight_error_other_runtime_error_returns_exit_code_127(monkeypatch):
    """A non-platform tool-resolution failure exits 127 (tool not found)."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    def _raise_generic(*_args, **_kwargs):
        raise RuntimeError("could not download TabularEditor.exe")

    monkeypatch.setattr(registry, "resolve_tool", _raise_generic)
    message, code = preflight_error("bpa", argparse.Namespace())
    assert code == 127
    assert "could not download" in message


@pytest.mark.fab_test
def test_preflight_error_names_cli_flag_env_var_and_config_key(monkeypatch):
    """The missing-tool message names the CLI flag alongside env var/config key."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    def _raise_generic(*_args, **_kwargs):
        raise RuntimeError(
            "Could not resolve executable for analyzer 'tabular_editor_bpa'.\n"
            "  Set TABULAR_EDITOR_PATH=<path>\n"
            "  Or set tool_install.install_url in analyzers.json to a zip URL."
        )

    monkeypatch.setattr(registry, "resolve_tool", _raise_generic)
    message, code = preflight_error("bpa", argparse.Namespace())
    assert code == 127
    assert "--tabular-editor-path" in message
    assert "TABULAR_EDITOR_PATH" in message
    assert "tool_install.install_url" in message


@pytest.mark.fab_test
def test_preflight_error_pbir_names_inspector_path_flag(monkeypatch):
    """The pbir missing-tool message names --inspector-path."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    def _raise_generic(*_args, **_kwargs):
        raise RuntimeError("Could not resolve executable for analyzer 'pbir_inspector'.")

    monkeypatch.setattr(registry, "resolve_tool", _raise_generic)
    message, code = preflight_error("pbir", argparse.Namespace())
    assert code == 127
    assert "--inspector-path" in message


@pytest.mark.fab_test
def test_preflight_error_none_when_tool_resolves(monkeypatch):
    """No preflight error is returned when the tool resolves successfully."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    monkeypatch.setattr(registry, "resolve_tool", lambda *a, **k: Path("/tmp/te.exe"))
    assert preflight_error("bpa", argparse.Namespace()) is None


# --------------------------------------------------------------------------- #
# Fail fast on unsupported platforms
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_run_analyzer_bpa_on_unsupported_platform_fails_fast(tmp_path, monkeypatch):
    """`fab-test bpa` on Linux/macOS exits 126 before invoking any subprocess.

    Tabular Editor is Windows-only (requires_platform: win32 in analyzers.json).
    """
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    calls = []
    monkeypatch.setattr(
        fab_test_execution.subprocess, "run", lambda *a, **k: calls.append(a) or None
    )
    monkeypatch.setattr(sys, "platform", "linux")

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("bpa", args, output_dir)

    assert code == 126
    assert calls == [], "no subprocess should run once the platform check fails"


@pytest.mark.fab_test
def test_run_analyzer_bpa_unsupported_platform_points_to_env_var(
    tmp_path, monkeypatch, capsys
):
    """The fail-fast message tells the user how to override with an env var.

    Uses the default --format json, so per the CLI Agent Ergonomics contract
    the preflight message is narrated to stderr, leaving stdout clean.
    """
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(sys, "platform", "linux")

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("bpa", args, output_dir)
    captured = capsys.readouterr()

    assert code == 126
    assert "TABULAR_EDITOR_PATH" in captured.err
    assert captured.out == ""


# --------------------------------------------------------------------------- #
# Validate CLI inputs up front
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_workspace_id_rejects_non_guid():
    """--workspace-id abc is rejected before any analyzer runs."""
    result = subprocess.run(
        ["fab-test", "pql_test", "--workspace-id", "abc", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout
    assert "GUID" in result.stderr


@pytest.mark.fab_test
def test_workspace_id_accepts_valid_guid():
    """A well-formed GUID is accepted."""
    result = subprocess.run(
        [
            "fab-test", "pql_test",
            "--workspace-id", "123e4567-e89b-12d3-a456-426614174000",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_workspace_id_default_empty_is_accepted():
    """Omitting --workspace-id (empty default) does not trigger GUID validation."""
    result = subprocess.run(
        ["fab-test", "pql_test", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_artifact_dir_missing_path_exits_early(tmp_path):
    """A nonexistent --artifact-dir exits before any analyzer runs."""
    missing = tmp_path / "does-not-exist"
    result = subprocess.run(
        ["fab-test", "bpa", "--artifact-dir", str(missing)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout
    assert "does not exist" in result.stdout
    assert str(missing) in result.stdout


@pytest.mark.fab_test
def test_artifact_dir_existing_empty_dir_still_exits_zero(tmp_path):
    """An existing-but-empty --artifact-dir is a distinct, non-fatal case."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run", "--artifact-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_format_invalid_choice_lists_allowed_formats():
    """--format yaml is rejected with the allowed format list."""
    result = subprocess.run(
        ["fab-test", "bpa", "--format", "yaml", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout
    assert "text" in result.stderr
    assert "json" in result.stderr


