"""Contract tests for the fab-test CLI (vision §2.7).

Scope
-----
These tests validate the *fab-test command surface*:
subcommand structure, help output, and dry-run artifact discovery.
No external tools (Tabular Editor, PBIR Inspector, etc.) required.
Always passes on any machine.

    pytest -m fab_test       # all fab-test CLI contract tests

Real artifact execution is done via fab-test directly:
    python scripts/fab_test.py bpa
"""

import argparse
import hashlib
import json
import subprocess
import sys
import unittest.mock
from pathlib import Path

import pytest

from fabric_ci_cd_dataops import __version__ as fab_test_version
from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import (
    UnsupportedPlatformError,
    _verify_checksum,
    resolve_executable,
)
from fabric_ci_cd_dataops.scripts.fab_test import (
    _SUBCOMMAND_ALIASES,
    _apply_environment_default,
    _artifact_exit_code,
    _build_telemetry_payload,
    _clean_tools,
    _detect_origin,
    _git_context,
    _load_fab_test_all_analyzers,
    _load_pyproject_config,
    _machine_context,
    _print_all_summary,
    _print_summary,
    _redact_pii,
    _resolve_timeout,
    _run_analyzer,
    _send_telemetry,
    _telemetry_enabled,
    _validate_telemetry_payload,
    build_parser,
)
from fabric_ci_cd_dataops.scripts.fab_test_registry import (
    build_pql_test_command,
    preflight_error,
)
from fabric_ci_cd_dataops.scripts.fab_test_summary import (
    _format_findings,
    _is_pql_test_finding,
    _pql_test_status,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FAB_TEST = "fab-test"
ARTIFACT_ROOT = REPO_ROOT / ".fabric" / "artifacts"

_ALL_SUBCOMMANDS = ("bpa", "pbir", "pql_test", "pql_lint", "all")


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
    assert "github.com/kerski/fabric-ci-cd-dataops" in result.stdout, (
        "--help should link to project documentation"
    )


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
    cmd = build_pql_test_command(artifact, args, REPO_ROOT / "analyzer-results")
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
    cmd = build_pql_test_command(artifact, args, REPO_ROOT / "analyzer-results")
    assert "--workspace-id" in cmd
    idx = cmd.index("--workspace-id")
    assert cmd[idx + 1] == "env-workspace-456"
    assert "--env" in cmd
    env_idx = cmd.index("--env")
    assert cmd[env_idx + 1] == "TEST"


@pytest.mark.fab_test
def test_all_help_exits_zero():
    """fab-test all --help exits 0."""
    result = subprocess.run(
        ["fab-test", "all", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Dry-run artifact discovery — no external tools needed
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_bpa_dry_run_exits_zero():
    """fab-test bpa --dry-run exits 0 (no Tabular Editor needed)."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_bpa_dry_run_discovers_sample_model():
    """fab-test bpa --dry-run finds the sample SemanticModel."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "SampleModel-PQLAssert" in result.stdout, (
        f"Expected SampleModel-PQLAssert in dry-run output.\nGot: {result.stdout}"
    )


@pytest.mark.fab_test
def test_bpa_dry_run_with_artifact_filter():
    """--artifact STEM filters the discovered artifact list."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run",
         "--artifact", "SampleModel-PQLAssert"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "SampleModel-PQLAssert" in result.stdout


@pytest.mark.fab_test
def test_bpa_dry_run_empty_artifact_dir(tmp_path: Path):
    """--artifact-dir with no matching artifacts exits 0 with a warning."""
    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run",
         "--artifact-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_pbir_dry_run_exits_zero():
    """fab-test pbir --dry-run exits 0 regardless of Report artifact count."""
    result = subprocess.run(
        ["fab-test", "pbir", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_pql_lint_dry_run_exits_zero():
    """fab-test pql_lint --dry-run exits 0."""
    result = subprocess.run(
        ["fab-test", "pql_lint", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Formatter helpers — tabulate-based verbose output
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_format_findings_empty_returns_empty_string():
    """No findings should produce no table output."""
    assert _format_findings([]) == ""


@pytest.mark.fab_test
def test_format_findings_shows_rule_severity_object_message():
    """A single finding is rendered with the four key columns."""
    table = _format_findings(
        [
            {
                "rule": "AvoidCalcColumns",
                "severity": "Error",
                "object": "Sales[Amount]",
                "message": "Calculated columns are not allowed in this model.",
            }
        ]
    )
    assert "AvoidCalcColumns" in table
    assert "Error" in table
    assert "Sales[Amount]" in table
    assert "Calculated columns" in table


@pytest.mark.fab_test
def test_format_findings_truncates_long_message():
    """Long messages are truncated with an ellipsis to keep output scannable."""
    long_message = "A" * 200
    table = _format_findings(
        [{"rule": "R1", "severity": "Warning", "object": "T", "message": long_message}],
        max_width=60,
    )
    assert "..." in table
    assert len(table.splitlines()[0]) <= 70  # header row bounded by terminal budget


@pytest.mark.fab_test
def test_format_findings_truncates_long_rule():
    """Long rule names are also truncated so the table stays within bounds."""
    long_rule = "VeryLongRuleNameThatWouldOverflow" * 5
    table = _format_findings(
        [{"rule": long_rule, "severity": "Warning", "object": "T", "message": "m"}],
        max_width=60,
    )
    assert "..." in table


@pytest.mark.fab_test
def test_format_findings_sorts_by_severity_descending():
    """Findings are sorted so the highest severity appears first."""
    table = _format_findings(
        [
            {"rule": "Low", "severity": "1", "object": "T", "message": "info"},
            {"rule": "High", "severity": "Error", "object": "T", "message": "bad"},
            {"rule": "Med", "severity": "2", "object": "T", "message": "warn"},
        ],
        max_width=120,
    )
    high_pos = table.find("High")
    med_pos = table.find("Med")
    low_pos = table.find("Low")
    assert high_pos < med_pos < low_pos


@pytest.mark.fab_test
def test_format_findings_pql_test_columns():
    """pql-test findings render Test Suite, Test, Expected, Actual, Passed columns."""
    table = _format_findings(
        [
            {
                "suite_name": "DataQuality.ANY.Tests",
                "test_name": "DateDim Date should be unique",
                "expected": "All values distinct",
                "actual": "DUPLICATES FOUND",
                "passed": False,
                "skipped": False,
                "error": None,
            }
        ],
        max_width=160,
    )
    assert "Test Suite" in table
    assert "Test" in table
    assert "Expected" in table
    assert "Actual" in table
    assert "Passed" in table
    assert "DataQuality.ANY.Tests" in table
    assert "DateDim Date should be unique" in table
    assert "All values distinct" in table
    assert "DUPLICATES FOUND" in table
    assert "FAIL" in table


@pytest.mark.fab_test
def test_format_findings_pql_test_status_skipped():
    """pql-test finding with skipped=True renders SKIPPED in Passed column."""
    table = _format_findings(
        [
            {
                "suite_name": "S",
                "test_name": "T",
                "expected": "e",
                "actual": "a",
                "passed": False,
                "skipped": True,
                "error": None,
            }
        ],
        max_width=120,
    )
    assert "SKIPPED" in table


@pytest.mark.fab_test
def test_format_findings_pql_test_status_error():
    """pql-test finding with an error renders ERROR in Passed column."""
    table = _format_findings(
        [
            {
                "suite_name": "S",
                "test_name": "T",
                "expected": "e",
                "actual": "a",
                "passed": False,
                "skipped": False,
                "error": "connection refused",
            }
        ],
        max_width=120,
    )
    assert "ERROR" in table


@pytest.mark.fab_test
def test_format_findings_bpa_unchanged():
    """BPA/PBIR-style findings still use the generic four-column table."""
    table = _format_findings(
        [
            {
                "rule": "NoCalcColumns",
                "severity": "Error",
                "object": "Sales[Amount]",
                "message": "Calculated columns are not allowed.",
            }
        ],
        max_width=120,
    )
    assert "Rule" in table
    assert "Severity" in table
    assert "Object" in table
    assert "Message" in table
    assert "Test Suite" not in table


@pytest.mark.fab_test
def test_is_pql_test_finding_detects_result_shape():
    """pql-test result dicts are detected by test_name/expected/actual fields."""
    assert _is_pql_test_finding({"test_name": "T", "passed": True})
    assert _is_pql_test_finding({"suite_name": "S", "passed": False})
    assert not _is_pql_test_finding({"rule": "R", "severity": "Error"})


@pytest.mark.fab_test
def test_pql_test_status_labels():
    """_pql_test_status maps result fields to PASS/FAIL/SKIPPED/ERROR."""
    assert _pql_test_status({"passed": True}) == "PASS"
    assert _pql_test_status({"passed": False}) == "FAIL"
    assert _pql_test_status({"passed": False, "skipped": True}) == "SKIPPED"
    assert _pql_test_status({"passed": False, "error": "x"}) == "ERROR"


@pytest.mark.fab_test
def test_print_summary_shows_test_summary_and_severity_breakdown(tmp_path, capsys):
    """Summary line includes test counters and error/warning breakdown."""
    output_dir = tmp_path / "analyzer-results"
    envelope = output_dir / "bpa" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps(
            {
                "status": "failed",
                "test_summary": {
                    "total": 72,
                    "executed": 72,
                    "passed": 56,
                    "failed": 16,
                },
                "findings": [
                    {
                        "rule": "NoHiddenObjects",
                        "severity": "Error",
                        "object": "Sales",
                        "message": "Hidden objects detected.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code = _print_summary(
        "bpa",
        [("SampleModel", 1)],
        output_dir=output_dir,
        verbosity="verbose",
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "72 tests" in captured.out
    assert "16 failed" in captured.out
    assert "1 error" in captured.out


@pytest.mark.fab_test
def test_print_summary_default_does_not_show_findings(capsys):
    """Default verbosity keeps the summary concise (no per-finding table)."""
    code = _print_summary("bpa", [("SampleModel", 1)])
    captured = capsys.readouterr()
    assert code == 1
    assert "SampleModel" in captured.out
    assert "Rule" not in captured.out  # findings table header not printed


@pytest.mark.fab_test
def test_print_summary_verbose_shows_findings_for_failed_artifact(tmp_path, capsys):
    """Verbose mode surfaces the failed artifact's findings from its envelope."""
    output_dir = tmp_path / "analyzer-results"
    envelope = output_dir / "bpa" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps(
            {
                "status": "failed",
                "findings": [
                    {
                        "rule": "NoHiddenObjects",
                        "severity": "Error",
                        "object": "Sales",
                        "message": "Hidden objects detected.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code = _print_summary(
        "bpa",
        [("SampleModel", 1)],
        output_dir=output_dir,
        verbosity="verbose",
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "NoHiddenObjects" in captured.out
    assert "Hidden objects detected" in captured.out


@pytest.mark.fab_test
def test_print_summary_pql_test_counters(tmp_path, capsys):
    """pql-test summary line shows total/passed/failed/skipped counters."""
    output_dir = tmp_path / "analyzer-results"
    envelope = output_dir / "pql_test" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps(
            {
                "analyzer": "pql_test",
                "status": "failed",
                "test_summary": {
                    "total": 86,
                    "passed": 76,
                    "failed": 10,
                    "skipped": 0,
                },
                "findings": [],
            }
        ),
        encoding="utf-8",
    )

    code = _print_summary(
        "pql_test",
        [("SampleModel", 1)],
        output_dir=output_dir,
        verbosity="verbose",
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "86 tests" in captured.out
    assert "76 passed" in captured.out
    assert "10 failed" in captured.out
    assert "0 skipped" in captured.out


@pytest.mark.fab_test
def test_print_summary_pql_test_verbose_table(tmp_path, capsys):
    """pql-test verbose output shows the test-results table."""
    output_dir = tmp_path / "analyzer-results"
    envelope = output_dir / "pql_test" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps(
            {
                "analyzer": "pql_test",
                "status": "failed",
                "test_summary": {
                    "total": 2,
                    "passed": 1,
                    "failed": 1,
                    "skipped": 0,
                },
                "findings": [
                    {
                        "suite_name": "DQ",
                        "test_name": "Uniqueness",
                        "expected": "distinct",
                        "actual": "duplicates",
                        "passed": False,
                        "skipped": False,
                        "error": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    code = _print_summary(
        "pql_test",
        [("SampleModel", 1)],
        output_dir=output_dir,
        verbosity="verbose",
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "Test Suite" in captured.out
    assert "Uniqueness" in captured.out
    assert "FAIL" in captured.out


# --------------------------------------------------------------------------- #
# Metadata-driven analyzer list for `fab-test all`
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_reads_metadata(tmp_path):
    """The analyzer list for `all` is read from analyzers.json."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text(
        json.dumps({"fab_test_all": ["bpa", "pbir"]}),
        encoding="utf-8",
    )
    assert _load_fab_test_all_analyzers(metadata) == ("bpa", "pbir")


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_ignores_non_string_items(tmp_path):
    """Only string items in the list are returned."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text(
        json.dumps({"fab_test_all": ["bpa", 123, None, "pbir"]}),
        encoding="utf-8",
    )
    assert _load_fab_test_all_analyzers(metadata) == ("bpa", "pbir")


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_falls_back_on_missing_file(tmp_path):
    """A missing or unreadable file falls back to the historical default."""
    missing = tmp_path / "analyzers.json"
    assert _load_fab_test_all_analyzers(missing) == (
        "bpa",
        "pbir",
        "pql_test",
        "pql_lint",
    )


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_falls_back_on_bad_json(tmp_path):
    """Malformed JSON falls back to the historical default."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text("not json", encoding="utf-8")
    assert _load_fab_test_all_analyzers(metadata) == (
        "bpa",
        "pbir",
        "pql_test",
        "pql_lint",
    )


@pytest.mark.fab_test
def test_load_fab_test_all_analyzers_falls_back_when_key_missing(tmp_path):
    """A valid JSON file without fab_test_all falls back to the default."""
    metadata = tmp_path / "analyzers.json"
    metadata.write_text(json.dumps({"analyzer_registry": {}}), encoding="utf-8")
    assert _load_fab_test_all_analyzers(metadata) == (
        "bpa",
        "pbir",
        "pql_test",
        "pql_lint",
    )


@pytest.mark.fab_test
def test_all_dry_run_uses_metadata_list_not_pql_lint():
    """`fab-test all --dry-run` skips analyzers excluded from metadata."""
    result = subprocess.run(
        ["fab-test", "all", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # pql_lint is excluded from fab_test_all in the committed metadata.
    assert "fab-test pql_lint" not in result.stdout
    assert "fab-test bpa" in result.stdout
    assert "fab-test pbir" in result.stdout
    assert "fab-test pql_test" in result.stdout


@pytest.mark.fab_test
def test_pql_lint_direct_subcommand_still_works_dry_run():
    """`fab-test pql_lint` can still be invoked directly even when excluded from `all`."""
    result = subprocess.run(
        ["fab-test", "pql_lint", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fab-test pql_lint" in result.stdout


# --------------------------------------------------------------------------- #
# Aggregate `fab-test all` summary
# --------------------------------------------------------------------------- #


class _FakeArgs:
    """Minimal argparse.Namespace stand-in for summary tests."""

    def __init__(self, artifact_dir: Path, artifact: str | None = None, dry_run: bool = False):
        self.artifact_dir = str(artifact_dir)
        self.artifact = artifact
        self.dry_run = dry_run


@pytest.mark.fab_test
def test_print_all_summary_shows_aggregate_errors_and_warnings(tmp_path, capsys):
    """Aggregate summary totals errors and warnings across analyzers."""
    output_dir = tmp_path / "analyzer-results"
    for analyzer, stem, findings in [
        ("bpa", "SampleModel", [{"rule": "R1", "severity": "Error"}] * 2),
        ("pbir", "SampleModel", [{"rule": "R2", "severity": "Warning"}] * 3),
    ]:
        envelope = output_dir / analyzer / stem / "envelope.json"
        envelope.parent.mkdir(parents=True)
        envelope.write_text(
            json.dumps(
                {
                    "status": "failed" if findings else "passed",
                    "findings": findings,
                }
            ),
            encoding="utf-8",
        )

    artifact_dir = tmp_path / "artifacts"
    for stem, glob_name in [("SampleModel", "*.SemanticModel")]:
        (artifact_dir / f"{stem}.SemanticModel").mkdir(parents=True)
        (artifact_dir / f"{stem}.Report").mkdir(parents=True)

    args = _FakeArgs(artifact_dir=artifact_dir)
    code = _print_all_summary(
        output_dir=output_dir,
        analyzers=("bpa", "pbir"),
        codes=[1, 0],
        args=args,
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "2 error(s), 3 warning(s)" in captured.out
    assert "Totals:" in captured.out


@pytest.mark.fab_test
def test_print_all_summary_no_artifacts_analyzed(tmp_path, capsys):
    """When no artifacts match, the aggregate summary reports that clearly."""
    output_dir = tmp_path / "analyzer-results"
    artifact_dir = tmp_path / "artifacts"
    args = _FakeArgs(artifact_dir=artifact_dir)
    code = _print_all_summary(
        output_dir=output_dir,
        analyzers=("bpa",),
        codes=[0],
        args=args,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "No artifacts were analyzed" in captured.out


# --------------------------------------------------------------------------- #
# New CI-focused CLI flags
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_bpa_help_shows_telemetry_and_format_flags():
    """--telemetry, --no-telemetry, and --format must appear on subcommand help."""
    result = subprocess.run(
        ["fab-test", "bpa", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--telemetry" in result.stdout
    assert "--no-telemetry" in result.stdout
    assert "--format" in result.stdout


@pytest.mark.fab_test
def test_all_format_json_dry_run_is_valid_json():
    """`fab-test all --format json --dry-run` prints ONLY the JSON summary on
    stdout — the per-analyzer dry-run banners/listings are narrated to stderr
    instead (CLI Agent Ergonomics: stdout stays a single parseable document).
    """
    result = subprocess.run(
        ["fab-test", "all", "--format", "json", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert "artifacts" in summary
    assert "totals" in summary
    assert summary["dry_run"] is True
    assert "dry run" in result.stderr


@pytest.mark.fab_test
def test_print_summary_json_format(tmp_path, capsys):
    """_print_summary with output_format='json' emits JSON."""
    output_dir = tmp_path / "analyzer-results"
    envelope = output_dir / "bpa" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps({"status": "passed", "findings": []}),
        encoding="utf-8",
    )
    code = _print_summary(
        "bpa",
        [("SampleModel", 0)],
        output_dir=output_dir,
        output_format="json",
    )
    captured = capsys.readouterr()
    assert code == 0
    summary = json.loads(captured.out)
    assert summary["analyzer"] == "bpa"
    assert summary["artifacts"][0]["status"] == "passed"


@pytest.mark.fab_test
def test_print_all_summary_json_format(tmp_path, capsys):
    """_print_all_summary with output_format='json' emits JSON."""
    output_dir = tmp_path / "analyzer-results"
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    envelope = output_dir / "bpa" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps({"status": "passed", "findings": []}),
        encoding="utf-8",
    )
    args = _FakeArgs(artifact_dir=artifact_dir)
    args.output_format = "json"
    code = _print_all_summary(
        output_dir=output_dir,
        analyzers=("bpa",),
        codes=[0],
        args=args,
    )
    captured = capsys.readouterr()
    assert code == 0
    summary = json.loads(captured.out)
    assert summary["artifacts"][0]["analyzer"] == "bpa"
    assert summary["totals"] == {"errors": 0, "warnings": 0}


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
    for code in ("0", "1", "2", "126"):
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
def test_preflight_error_other_runtime_error_returns_exit_code_1(monkeypatch):
    """A non-platform tool-resolution failure keeps the existing exit code 1."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    def _raise_generic(*_args, **_kwargs):
        raise RuntimeError("could not download TabularEditor.exe")

    monkeypatch.setattr(registry, "resolve_tool", _raise_generic)
    message, code = preflight_error("bpa", argparse.Namespace())
    assert code == 1
    assert "could not download" in message


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
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    calls = []
    monkeypatch.setattr(
        fab_test_module.subprocess, "run", lambda *a, **k: calls.append(a) or None
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
    output_dir = tmp_path / "analyzer-results"

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


# --------------------------------------------------------------------------- #
# Telemetry gating
# --------------------------------------------------------------------------- #


class _TelemetryArgs:
    def __init__(self, telemetry=None):
        self.telemetry = telemetry


@pytest.mark.fab_test
def test_telemetry_enabled_false_arg_overrides_env(monkeypatch):
    """--no-telemetry suppresses telemetry even when env var is true."""
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    args = _TelemetryArgs(telemetry=False)
    assert _telemetry_enabled(args) is False


@pytest.mark.fab_test
def test_telemetry_enabled_true_arg_overrides_env(monkeypatch):
    """--telemetry forces telemetry even when env var is false."""
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "false")
    args = _TelemetryArgs(telemetry=True)
    assert _telemetry_enabled(args) is True


@pytest.mark.fab_test
def test_telemetry_enabled_defaults_to_env(monkeypatch):
    """When no arg is provided, telemetry follows ENABLE_EVENTHOUSE_LOGGING."""
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    args = _TelemetryArgs(telemetry=None)
    assert _telemetry_enabled(args) is True

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "false")
    assert _telemetry_enabled(args) is False


# --------------------------------------------------------------------------- #
# Git context (telemetry): branch, commit, actor
# --------------------------------------------------------------------------- #


def _clear_github_env(monkeypatch):
    for name in (
        "GITHUB_REPOSITORY",
        "GITHUB_REF_NAME",
        "GITHUB_SHA",
        "GITHUB_ACTOR",
        "GITHUB_RUN_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def _fake_git_run(responses: dict[str, str]):
    """Build a subprocess.run stand-in keyed by the git subcommand args."""

    def _run(cmd, **_kwargs):
        key = " ".join(cmd[1:])  # drop the leading "git"
        if key in responses:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=responses[key], stderr=""
            )
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")

    return _run


@pytest.mark.fab_test
def test_git_context_prefers_github_env_vars(monkeypatch):
    """GitHub Actions env vars are used as-is when present."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setenv("GITHUB_REPOSITORY", "kerski/fab-test")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_ACTOR", "ci-bot")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("git should not run")),
    )

    ctx = _git_context()
    assert ctx == {
        "repository": "kerski/fab-test",
        "branch": "main",
        "commit": "abc123",
        "actor": "ci-bot",
        "workflow_run_id": "42",
    }


@pytest.mark.fab_test
def test_git_context_falls_back_to_local_git_branch_and_commit(monkeypatch):
    """Outside GitHub Actions, branch and commit come from local git."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse HEAD": "deadbeef\n",
                "rev-parse --abbrev-ref HEAD": "feature/x\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )

    ctx = _git_context()
    assert ctx["commit"] == "deadbeef"
    assert ctx["branch"] == "feature/x"


@pytest.mark.fab_test
def test_git_context_falls_back_to_local_git_user_email_for_actor(monkeypatch):
    """When GITHUB_ACTOR is unset, the actor falls back to git config user.email."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse HEAD": "deadbeef\n",
                "rev-parse --abbrev-ref HEAD": "main\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )

    ctx = _git_context()
    assert ctx["actor"] == "dev@example.com"


@pytest.mark.fab_test
def test_git_context_actor_empty_when_git_config_has_no_email(monkeypatch):
    """A git config with no user.email set leaves actor empty, not crashing."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess, "run", _fake_git_run({})  # every command "fails"
    )

    ctx = _git_context()
    assert ctx["actor"] == ""
    assert ctx["branch"] == ""
    assert ctx["commit"] == ""


@pytest.mark.fab_test
def test_git_context_returns_empty_strings_when_git_is_unavailable(monkeypatch):
    """If git itself is missing, _git_context degrades to empty fields, no crash."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git not found")),
    )

    ctx = _git_context()
    assert ctx == {
        "repository": "",
        "branch": "",
        "commit": "",
        "actor": "",
        "workflow_run_id": "",
    }


@pytest.mark.fab_test
def test_git_context_actor_not_overridden_by_git_when_github_actor_set(monkeypatch):
    """GITHUB_ACTOR wins over the local git user.email even if both are set."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTOR", "ci-bot")
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run({"config user.email": "dev@example.com\n"}),
    )

    ctx = _git_context()
    assert ctx["actor"] == "ci-bot"


# --------------------------------------------------------------------------- #
# Distinguish local vs pipeline origin
# --------------------------------------------------------------------------- #


def _clear_ci_env(monkeypatch):
    for name in ("GITHUB_ACTIONS", "CI", "GITLAB_CI", "CIRCLECI", "AZURE_DEVOPS"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.fab_test
def test_detect_origin_github_actions(monkeypatch):
    """GITHUB_ACTIONS maps origin to 'github-actions'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert _detect_origin() == "github-actions"


@pytest.mark.fab_test
def test_detect_origin_gitlab_ci(monkeypatch):
    """GITLAB_CI maps origin to 'gitlab-ci'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("GITLAB_CI", "true")
    assert _detect_origin() == "gitlab-ci"


@pytest.mark.fab_test
def test_detect_origin_circleci(monkeypatch):
    """CIRCLECI maps origin to 'circleci'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("CIRCLECI", "true")
    assert _detect_origin() == "circleci"


@pytest.mark.fab_test
def test_detect_origin_azure_devops(monkeypatch):
    """AZURE_DEVOPS maps origin to 'azure-devops'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("AZURE_DEVOPS", "true")
    assert _detect_origin() == "azure-devops"


@pytest.mark.fab_test
def test_detect_origin_local_when_no_ci_env_present(monkeypatch):
    """With no known CI env vars, origin is 'local'."""
    _clear_ci_env(monkeypatch)
    assert _detect_origin() == "local"


@pytest.mark.fab_test
def test_detect_origin_github_actions_takes_precedence(monkeypatch):
    """If multiple CI env vars are somehow set, GITHUB_ACTIONS wins."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITLAB_CI", "true")
    assert _detect_origin() == "github-actions"


@pytest.mark.fab_test
def test_build_telemetry_payload_includes_origin(monkeypatch):
    """The telemetry payload carries the detected origin field."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("CIRCLECI", "true")

    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert payload["origin"] == "circleci"


# --------------------------------------------------------------------------- #
# Capture machine context
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_machine_context_includes_platform_python_and_fab_test_version():
    """Machine context carries platform, python_version, and fab_test_version."""
    context = _machine_context()
    assert context["platform"] == sys.platform
    assert context["python_version"]
    assert context["fab_test_version"] == fab_test_version


@pytest.mark.fab_test
def test_machine_context_omits_platform_when_undetectable(monkeypatch):
    """If the OS platform can't be read, the field is omitted, not a crash."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_current_os_platform",
        lambda: (_ for _ in ()).throw(RuntimeError("no platform")),
    )

    context = _machine_context()
    assert "platform" not in context
    assert context["python_version"]
    assert context["fab_test_version"] == fab_test_version


@pytest.mark.fab_test
def test_redact_pii_hashes_email_like_values():
    """An email-shaped value is redacted to a stable, non-reversible hash."""
    redacted = _redact_pii("dev@example.com")
    assert "@" not in redacted
    assert redacted.startswith("sha256:")
    assert redacted == _redact_pii("dev@example.com")  # stable/deterministic


@pytest.mark.fab_test
def test_redact_pii_leaves_non_email_values_unchanged():
    """A non-email value (e.g. a CI bot username) passes through unchanged."""
    assert _redact_pii("ci-bot") == "ci-bot"
    assert _redact_pii("") == ""


@pytest.mark.fab_test
def test_build_telemetry_payload_includes_machine_context():
    """The telemetry payload carries platform/python_version/fab_test_version."""
    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert payload["platform"] == sys.platform
    assert payload["fab_test_version"] == fab_test_version


@pytest.mark.fab_test
def test_build_telemetry_payload_redacts_email_actor(monkeypatch):
    """An actor that looks like an email address is redacted in the payload."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module, "_git_context", lambda: {"actor": "dev@example.com"}
    )
    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert "@" not in payload["actor"]
    assert payload["actor"].startswith("sha256:")


@pytest.mark.fab_test
def test_build_telemetry_payload_actor_unchanged_when_not_email(monkeypatch):
    """A non-email actor (e.g. GITHUB_ACTOR) passes through unredacted."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "_git_context", lambda: {"actor": "ci-bot"})
    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert payload["actor"] == "ci-bot"


# --------------------------------------------------------------------------- #
# Validate telemetry payload schema
# --------------------------------------------------------------------------- #


def _valid_telemetry_payload(**overrides):
    payload = {
        "timestamp": "2026-08-18T12:00:00",
        "artifact_name": "SampleModel",
        "artifact_type": "SemanticModel",
        "analyzer": "bpa",
        "status": "passed",
        "commit_sha": "abc123",
        "workflow_run_id": "",
        "repository": "",
        "actor": "",
        "branch": "",
        "origin": "local",
    }
    payload.update(overrides)
    return payload


@pytest.mark.fab_test
def test_validate_telemetry_payload_passes_through_valid_payload():
    """A fully-formed payload is returned unchanged (aside from key order)."""
    payload = _valid_telemetry_payload()
    assert _validate_telemetry_payload(payload) == payload


@pytest.mark.fab_test
def test_validate_telemetry_payload_returns_none_when_required_field_missing(capsys):
    """A payload missing a required field is skipped, with a warning logged."""
    payload = _valid_telemetry_payload()
    del payload["status"]

    result = _validate_telemetry_payload(payload)
    captured = capsys.readouterr()

    assert result is None
    assert "status" in captured.out


@pytest.mark.fab_test
def test_validate_telemetry_payload_reports_all_missing_required_fields(capsys):
    """The warning lists every missing required field, not just the first."""
    payload = _valid_telemetry_payload()
    del payload["analyzer"]
    del payload["timestamp"]

    result = _validate_telemetry_payload(payload)
    captured = capsys.readouterr()

    assert result is None
    assert "analyzer" in captured.out
    assert "timestamp" in captured.out


@pytest.mark.fab_test
def test_validate_telemetry_payload_drops_malformed_optional_field():
    """A malformed (non-JSON-serializable) optional field is dropped, not fatal."""
    payload = _valid_telemetry_payload(weird_field={1, 2, 3})

    result = _validate_telemetry_payload(payload)

    assert result is not None
    assert "weird_field" not in result
    assert result["status"] == "passed"
    assert result["analyzer"] == "bpa"


@pytest.mark.fab_test
def test_send_telemetry_skips_and_warns_on_invalid_payload(monkeypatch, capsys):
    """_send_telemetry skips sending and warns, without raising, on invalid payload."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "_telemetry_enabled", lambda args: True)
    monkeypatch.setattr(
        fab_test_module,
        "_build_telemetry_payload",
        lambda *a, **k: _valid_telemetry_payload(status=""),  # falsy -> "missing"
    )
    calls = []
    monkeypatch.setattr(
        fab_test_module,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    _send_telemetry("bpa", Path("SampleModel.SemanticModel"), {"findings": []}, _TelemetryArgs())
    captured = capsys.readouterr()

    assert calls == []
    assert "status" in captured.out


@pytest.mark.fab_test
def test_send_telemetry_sends_valid_payload(monkeypatch):
    """A valid payload still reaches publish_analyzer_telemetry as before."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "_telemetry_enabled", lambda args: True)
    monkeypatch.setattr(
        fab_test_module,
        "_build_telemetry_payload",
        lambda *a, **k: _valid_telemetry_payload(),
    )
    calls = []
    monkeypatch.setattr(
        fab_test_module,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    _send_telemetry("bpa", Path("SampleModel.SemanticModel"), {"findings": []}, _TelemetryArgs())

    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Telemetry dry-run inspection
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_dry_run_with_telemetry_prints_payload_preview_not_sent(tmp_path, monkeypatch, capsys):
    """--telemetry --dry-run prints the payload preview instead of sending it.

    Uses the default --format json, so the preview is narrated to stderr,
    leaving stdout clean per the CLI Agent Ergonomics contract.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    calls = []
    monkeypatch.setattr(
        fab_test_module,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=True, dry_run=True)
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert calls == [], "telemetry must never be transmitted during --dry-run"
    assert captured.out == ""
    assert "Telemetry preview" in captured.err
    assert '"analyzer": "pql_lint"' in captured.err
    assert '"artifact_name": "SampleModel"' in captured.err


@pytest.mark.fab_test
def test_dry_run_without_telemetry_flag_shows_no_preview(tmp_path, monkeypatch, capsys):
    """Plain --dry-run (no --telemetry) prints no telemetry preview."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.delenv("ENABLE_EVENTHOUSE_LOGGING", raising=False)
    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=None, dry_run=True)
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "Telemetry preview" not in captured.out
    assert "Telemetry preview" not in captured.err


@pytest.mark.fab_test
def test_dry_run_no_telemetry_flag_suppresses_preview_even_with_env(
    tmp_path, monkeypatch, capsys
):
    """--no-telemetry suppresses the dry-run preview even if the env flag is on."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=False, dry_run=True)
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "Telemetry preview" not in captured.out
    assert "Telemetry preview" not in captured.err


@pytest.mark.fab_test
def test_telemetry_sent_normally_when_not_dry_run(tmp_path, monkeypatch):
    """--telemetry with ENABLE_EVENTHOUSE_LOGGING=true still sends for real runs."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    monkeypatch.setattr(
        fab_test_module.subprocess, "run", _stub_subprocess_run
    )
    calls = []
    monkeypatch.setattr(
        fab_test_module,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=None, dry_run=False)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Regression tests for telemetry context
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_git_context_mocked_local_git_returns_branch_and_actor(monkeypatch):
    """A mocked local git environment yields both branch and actor via git."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse HEAD": "deadbeef\n",
                "rev-parse --abbrev-ref HEAD": "feature/x\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )
    ctx = _git_context()
    assert ctx["branch"] == "feature/x"
    assert ctx["actor"] == "dev@example.com"


@pytest.mark.fab_test
def test_git_context_github_actions_env_preferred_over_local_git(monkeypatch):
    """GitHub Actions env vars win over local git output when both are present."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_ACTOR", "ci-bot")
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse --abbrev-ref HEAD": "local-branch\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )
    ctx = _git_context()
    assert ctx["branch"] == "main"
    assert ctx["actor"] == "ci-bot"


@pytest.mark.fab_test
def test_telemetry_send_network_failure_does_not_affect_analyzer_exit_code(
    tmp_path, monkeypatch, capsys
):
    """A telemetry network failure is swallowed; the analyzer's own exit code stands."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    envelope_dir = output_dir / "pql_lint" / "SampleModel"
    envelope_dir.mkdir(parents=True)
    envelope_dir_json = envelope_dir / "envelope.json"
    envelope_dir_json.write_text(
        json.dumps(
            {
                "status": "failed",
                "findings": [
                    {"rule": "R1", "severity": "Error", "object": "T", "message": "m"}
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)
    monkeypatch.setattr(
        fab_test_module,
        "publish_analyzer_telemetry",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("network unreachable")),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=None, dry_run=False)
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 1  # driven by the Error-severity finding, not the telemetry failure
    assert "Telemetry failed" in captured.err  # default --format json narrates to stderr


# --------------------------------------------------------------------------- #
# Tool bootstrap with zip archives
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_resolve_executable_downloads_and_extracts_zip(tmp_path, monkeypatch):
    """Missing tool is downloaded from install URL and extracted from zip."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # Build a zip containing the expected executable.
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    exe = tool_dir / "PBIRInspectorCLI"
    exe.write_text("#!/bin/sh\necho hi", encoding="utf-8")
    zip_path = tmp_path / "tool.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(exe, arcname="PBIRInspectorCLI")

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI"


@pytest.mark.fab_test
def test_resolve_executable_prefers_existing_path(tmp_path, monkeypatch):
    """If the env-var path exists, resolve_executable uses it without downloading."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"
    existing = repo_root / "PBIRInspectorCLI"
    existing.write_text("existing", encoding="utf-8")
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PBIR_INSPECTOR_PATH", str(existing))
    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", "http://example.com/tool.zip")
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved == existing.resolve()


@pytest.mark.fab_test
def test_resolve_executable_uses_committed_install_url(tmp_path, monkeypatch):
    """If no env var is set, a committed install_url in analyzers.json is used."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    # Build a local zip with the expected executable.
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    exe = tool_dir / "PBIRInspectorCLI"
    exe.write_text("#!/bin/sh\necho hi", encoding="utf-8")
    zip_path = tmp_path / "tool.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(exe, arcname="PBIRInspectorCLI")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_url": zip_path.as_uri(),
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # Ensure no env var overrides are present.
    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI"


@pytest.mark.fab_test
def test_resolve_executable_env_install_url_wins_over_committed(tmp_path, monkeypatch):
    """The env-var install URL takes precedence over the committed install_url."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    # Committed zip contains the wrong executable name.
    committed_dir = tmp_path / "committed"
    committed_dir.mkdir()
    committed_exe = committed_dir / "PBIRInspectorCLI"
    committed_exe.write_text("committed", encoding="utf-8")
    committed_zip = tmp_path / "committed.zip"
    with zipfile.ZipFile(committed_zip, "w") as zf:
        zf.write(committed_exe, arcname="PBIRInspectorCLI")

    # Env-var zip contains a differently named executable.
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    env_exe = env_dir / "PBIRInspectorCLI-Env"
    env_exe.write_text("env", encoding="utf-8")
    env_zip = tmp_path / "env.zip"
    with zipfile.ZipFile(env_zip, "w") as zf:
        zf.write(env_exe, arcname="PBIRInspectorCLI-Env")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_url": committed_zip.as_uri(),
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI-Env",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", env_zip.as_uri())

    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI-Env"


@pytest.mark.fab_test
def test_resolve_executable_selects_platform_specific_url_and_subpath(tmp_path, monkeypatch):
    """Platform-specific install_urls and executable_subpaths are honored."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    # Build a zip for each platform with a differently named executable.
    platform_assets = {}
    for platform in ("linux", "win32", "darwin"):
        asset_dir = tmp_path / platform
        asset_dir.mkdir()
        exe_name = f"fab-inspector-{platform}"
        if platform == "win32":
            exe_name += ".exe"
        exe = asset_dir / exe_name
        exe.write_text(f"#!/bin/sh\necho {platform}", encoding="utf-8")
        zip_path = tmp_path / f"{platform}.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(exe, arcname=exe_name)
        platform_assets[platform] = zip_path.as_uri()

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_urls": platform_assets,
                            "archive_type": "zip",
                            "executable_subpaths": {
                                "linux": "fab-inspector-linux",
                                "win32": "fab-inspector-win32.exe",
                                "darwin": "fab-inspector-darwin",
                            },
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    # Simulate running on Windows.
    with unittest.mock.patch("sys.platform", "win32"):
        resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "fab-inspector-win32.exe"

    # Simulate running on Linux.
    with unittest.mock.patch("sys.platform", "linux"):
        resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "fab-inspector-linux"


@pytest.mark.fab_test
def test_resolve_executable_requires_platform_mismatch_raises(tmp_path, monkeypatch):
    """If requires_platform does not match the current OS, raise RuntimeError."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "requires_platform": "linux",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)

    with (
        unittest.mock.patch("sys.platform", "win32"),
        pytest.raises(UnsupportedPlatformError, match="not supported on win32"),
    ):
        resolve_executable(analyzer_name, metadata, repo_root)


# --------------------------------------------------------------------------- #
# Verify downloaded tool archives (checksum)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_verify_checksum_mismatch_deletes_file_and_raises(tmp_path):
    """A checksum mismatch removes the downloaded file and raises clearly."""
    archive = tmp_path / "tool.zip"
    archive.write_bytes(b"archive-bytes")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _verify_checksum(archive, "0" * 64, "pbir_inspector")

    assert not archive.exists()


@pytest.mark.fab_test
def test_verify_checksum_match_leaves_file_in_place(tmp_path):
    """A matching checksum does not delete the file or raise."""
    archive = tmp_path / "tool.zip"
    archive.write_bytes(b"archive-bytes")
    expected = hashlib.sha256(b"archive-bytes").hexdigest()

    _verify_checksum(archive, expected, "pbir_inspector")

    assert archive.exists()


def _write_zip_with_executable(zip_path: Path, exe_path: Path, arcname: str) -> None:
    import zipfile

    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("#!/bin/sh\necho hi", encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(exe_path, arcname=arcname)


@pytest.mark.fab_test
def test_resolve_executable_verifies_checksum_before_extraction(tmp_path, monkeypatch):
    """A correct install_sha256 verifies and resolution proceeds normally."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    tool_dir = tmp_path / "tool"
    exe = tool_dir / "PBIRInspectorCLI"
    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, exe, "PBIRInspectorCLI")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_sha256": digest,
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI"


@pytest.mark.fab_test
def test_resolve_executable_checksum_mismatch_raises_before_extraction(
    tmp_path, monkeypatch
):
    """A wrong install_sha256 raises and never extracts the archive."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    tool_dir = tmp_path / "tool"
    exe = tool_dir / "PBIRInspectorCLI"
    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, exe, "PBIRInspectorCLI")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_sha256": "0" * 64,
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        resolve_executable(analyzer_name, metadata, repo_root)

    extracted = repo_root / ".fab-test-tools" / analyzer_name / "extracted"
    assert not extracted.exists(), "archive must not be extracted on checksum mismatch"


@pytest.mark.fab_test
def test_resolve_executable_no_install_sha256_skips_verification(tmp_path, monkeypatch):
    """No install_sha256 declared preserves today's download-and-extract behavior."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    tool_dir = tmp_path / "tool"
    exe = tool_dir / "PBIRInspectorCLI"
    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, exe, "PBIRInspectorCLI")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()


# --------------------------------------------------------------------------- #
# Configurable subprocess timeout
# --------------------------------------------------------------------------- #


class _TimeoutArgs:
    def __init__(self, timeout=None):
        self.timeout = timeout


@pytest.mark.fab_test
def test_resolve_timeout_uses_cli_flag_over_env(monkeypatch):
    """--timeout takes precedence over ANALYZER_TIMEOUT."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    assert _resolve_timeout(_TimeoutArgs(timeout=300)) == 300


@pytest.mark.fab_test
def test_resolve_timeout_uses_env_when_no_cli_flag(monkeypatch):
    """ANALYZER_TIMEOUT overrides the default when --timeout is not passed."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "200")
    assert _resolve_timeout(_TimeoutArgs(timeout=None)) == 200


@pytest.mark.fab_test
def test_resolve_timeout_defaults_to_120(monkeypatch):
    """With neither --timeout nor ANALYZER_TIMEOUT set, the default is 120."""
    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)
    assert _resolve_timeout(_TimeoutArgs(timeout=None)) == 120


@pytest.mark.fab_test
def test_bpa_help_shows_timeout_flag():
    """--timeout must be documented on subcommand help."""
    result = subprocess.run(
        ["fab-test", "bpa", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--timeout" in result.stdout


@pytest.mark.fab_test
def test_run_analyzer_passes_resolved_timeout_to_subprocess(tmp_path, monkeypatch):
    """_run_analyzer forwards the resolved timeout to subprocess.run."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    captured_timeouts = []

    def _fake_subprocess(*args, **kwargs):
        captured_timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel", timeout=45)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    assert captured_timeouts == [45]


# --------------------------------------------------------------------------- #
# Parallelize per-artifact runs
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_jobs_flag_default_is_one():
    """--jobs defaults to 1 (sequential) when not passed."""
    parser = build_parser()
    ns = parser.parse_args(["bpa", "--dry-run"])
    assert ns.jobs == 1


@pytest.mark.fab_test
def test_jobs_flag_parses_requested_value():
    """--jobs 4 is parsed as an int."""
    parser = build_parser()
    ns = parser.parse_args(["bpa", "--jobs", "4", "--dry-run"])
    assert ns.jobs == 4


@pytest.mark.fab_test
def test_run_analyzer_default_jobs_runs_artifacts_sequentially(tmp_path, monkeypatch):
    """With --jobs 1 (default), only one artifact's subprocess runs at a time."""
    import threading
    import time

    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    for i in range(3):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    lock = threading.Lock()
    active = 0
    max_active = 0

    def _fake_subprocess(*_args, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, jobs=1)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    assert max_active == 1


@pytest.mark.fab_test
def test_run_analyzer_jobs_n_runs_artifacts_concurrently(tmp_path, monkeypatch):
    """--jobs 3 runs up to 3 artifacts of the same analyzer in parallel."""
    import threading

    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    for i in range(3):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    # A 3-party barrier only completes if all three subprocess calls are
    # in flight at once; sequential execution would deadlock and time out.
    barrier = threading.Barrier(3, timeout=2)

    def _fake_subprocess(*_args, **_kwargs):
        barrier.wait()
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, jobs=3)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0


@pytest.mark.fab_test
def test_run_analyzer_parallel_writes_one_envelope_per_artifact(tmp_path, monkeypatch):
    """Each artifact still writes its own envelope; the summary waits for all."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    stems = [f"Model{i}" for i in range(3)]
    for stem in stems:
        (artifact_dir / f"{stem}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    def _fake_subprocess(cmd, **_kwargs):
        # Locate the artifact stem this invocation targets and write its
        # envelope, mirroring what the real analyzer wrapper would do.
        stem = next(s for s in stems if s in " ".join(cmd))
        envelope_dir = output_dir / "pql_lint" / stem
        envelope_dir.mkdir(parents=True, exist_ok=True)
        (envelope_dir / "envelope.json").write_text(
            json.dumps({"status": "passed", "findings": []}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, jobs=3)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    for stem in stems:
        assert (output_dir / "pql_lint" / stem / "envelope.json").exists()


# --------------------------------------------------------------------------- #
# Configuration file support (pyproject.toml [tool.fab-test])
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_load_pyproject_config_reads_tool_fab_test_section(tmp_path):
    """[tool.fab-test] values are returned as a plain dict."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.fab-test]\njobs = 4\nformat = "json"\n', encoding="utf-8"
    )
    config = _load_pyproject_config(pyproject)
    assert config == {"jobs": 4, "format": "json"}


@pytest.mark.fab_test
def test_load_pyproject_config_missing_file_returns_empty(tmp_path):
    """A missing pyproject.toml yields an empty config, not an error."""
    assert _load_pyproject_config(tmp_path / "does-not-exist.toml") == {}


@pytest.mark.fab_test
def test_load_pyproject_config_missing_section_returns_empty(tmp_path):
    """A pyproject.toml without [tool.fab-test] yields an empty config."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.other]\nx = 1\n', encoding="utf-8")
    assert _load_pyproject_config(pyproject) == {}


@pytest.mark.fab_test
def test_load_pyproject_config_malformed_toml_returns_empty(tmp_path):
    """Malformed TOML yields an empty config rather than crashing."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("not [ valid toml", encoding="utf-8")
    assert _load_pyproject_config(pyproject) == {}


@pytest.mark.fab_test
def test_common_flags_use_pyproject_config_as_default(monkeypatch):
    """--jobs/--format/--artifact-dir/--output-dir default from [tool.fab-test]."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
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
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "_PYPROJECT_CONFIG", {"jobs": 4})
    parser = fab_test_module.build_parser()
    ns = parser.parse_args(["bpa", "--dry-run", "--jobs", "8"])
    assert ns.jobs == 8


@pytest.mark.fab_test
def test_resolve_timeout_uses_config_when_no_cli_or_env(monkeypatch):
    """A config-file timeout is used when neither --timeout nor the env is set."""
    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)
    assert _resolve_timeout(_TimeoutArgs(timeout=None), config={"timeout": 300}) == 300


@pytest.mark.fab_test
def test_resolve_timeout_env_overrides_config(monkeypatch):
    """ANALYZER_TIMEOUT still overrides a config-file timeout."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    assert _resolve_timeout(_TimeoutArgs(timeout=None), config={"timeout": 300}) == 60


@pytest.mark.fab_test
def test_resolve_timeout_cli_overrides_config_and_env(monkeypatch):
    """An explicit --timeout wins over both env var and config file."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    assert _resolve_timeout(_TimeoutArgs(timeout=999), config={"timeout": 300}) == 999


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
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

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
def test_clean_tools_nothing_to_clean_when_missing(tmp_path, capsys):
    """A missing .fab-test-tools cache exits cleanly with a clear message."""
    code = _clean_tools(tmp_path, dry_run=False)
    captured = capsys.readouterr()

    assert code == 0
    assert "nothing to clean" in captured.out


@pytest.mark.fab_test
def test_main_clean_tools_dispatches_correctly(tmp_path, monkeypatch, capsys):
    """main() routes the clean-tools subcommand to _clean_tools."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

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
    "pql_test",
    "pql_lint",
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
    """Both scripts look up artifact stems from .fabric/artifacts at completion time."""
    result = subprocess.run(
        ["fab-test", "--print-completion", shell],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ".fabric/artifacts" in result.stdout


# --------------------------------------------------------------------------- #
# Normalize subcommand aliases
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_subcommand_alias_mapping():
    """Hyphen/underscore aliases resolve to their canonical analyzer name."""
    assert _SUBCOMMAND_ALIASES["pql-test"] == "pql_test"
    assert _SUBCOMMAND_ALIASES["pql-lint"] == "pql_lint"
    assert _SUBCOMMAND_ALIASES["playwright_impact"] == "playwright-impact"


@pytest.mark.fab_test
def test_pql_test_hyphen_alias_behaves_like_underscore():
    """fab-test pql-test behaves identically to fab-test pql_test."""
    canonical = subprocess.run(
        ["fab-test", "pql_test", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "pql-test", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0
    assert canonical.stdout == aliased.stdout


@pytest.mark.fab_test
def test_pql_lint_hyphen_alias_behaves_like_underscore():
    """fab-test pql-lint behaves identically to fab-test pql_lint."""
    canonical = subprocess.run(
        ["fab-test", "pql_lint", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "pql-lint", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0
    assert canonical.stdout == aliased.stdout


@pytest.mark.fab_test
def test_playwright_impact_underscore_alias_accepted():
    """playwright-impact remains canonical; playwright_impact is also accepted."""
    canonical = subprocess.run(
        ["fab-test", "playwright-impact", "--help"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "playwright_impact", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0


@pytest.mark.fab_test
def test_all_dry_run_output_unaffected_by_aliases():
    """`fab-test all` still lists the canonical pql_test name, not an alias."""
    result = subprocess.run(
        ["fab-test", "all", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fab-test pql_test" in result.stdout
    assert "fab-test pql-test" not in result.stdout


# --------------------------------------------------------------------------- #
# Route CLI narration through the helper (CLI Agent Ergonomics §2)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_json_format_real_run_has_no_narration_on_stdout(tmp_path, monkeypatch, capsys):
    """A real (non-dry-run) analyzer run under --format json narrates only to
    stderr; stdout carries just the final JSON summary from _print_summary.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    for i in range(2):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    summary = json.loads(captured.out)
    assert summary["analyzer"] == "pql_lint"
    assert "artifact 1 of 2" in captured.err
    assert "fab-test pql_lint" in captured.err


@pytest.mark.fab_test
def test_text_format_narration_still_on_stdout(tmp_path, monkeypatch, capsys):
    """--format text keeps narration on stdout exactly as before (regression)."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "fab-test pql_lint" in captured.out
    assert captured.err == ""


@pytest.mark.fab_test
def test_missing_artifacts_warning_narrated_by_format(tmp_path, capsys):
    """The 'no artifacts found' warning follows the same json/stderr routing."""
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()
    output_dir = tmp_path / "analyzer-results"

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    code = _run_analyzer("bpa", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert captured.out == ""
    assert "no *.SemanticModel artifacts found" in captured.err


@pytest.mark.fab_test
def test_main_artifact_dir_missing_message_narrated_by_format(tmp_path):
    """main()'s --artifact-dir-missing message follows --format routing too."""
    missing = tmp_path / "does-not-exist"

    result = subprocess.run(
        ["fab-test", "bpa", "--artifact-dir", str(missing), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "does not exist" in result.stderr


# --------------------------------------------------------------------------- #
# Show per-artifact progress
# --------------------------------------------------------------------------- #


def _stub_subprocess_run(*_args, **_kwargs):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


@pytest.mark.fab_test
def test_progress_shown_non_ci_multiple_artifacts(tmp_path, monkeypatch, capsys):
    """A non-CI run with multiple artifacts shows 'artifact N of M'."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    for i in range(3):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "artifact 1 of 3" in captured.out
    assert "artifact 2 of 3" in captured.out
    assert "artifact 3 of 3" in captured.out


@pytest.mark.fab_test
def test_progress_not_shown_for_single_artifact(tmp_path, monkeypatch, capsys):
    """A single-artifact run shows no 'N of 1' progress noise."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "of 1" not in captured.out


@pytest.mark.fab_test
def test_progress_emitted_as_ci_notice(tmp_path, monkeypatch, capsys):
    """In CI (GITHUB_ACTIONS), progress is a ::notice:: annotation, not plain text."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    for i in range(2):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: True)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module, "emit_workflow_annotations", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "::notice::" in captured.out
    assert "artifact 1 of 2" in captured.out
    assert "artifact 2 of 2" in captured.out
    assert "\n  artifact 1 of 2" not in captured.out  # not the plain-text form


@pytest.mark.fab_test
def test_artifact_start_line_still_printed_alongside_progress(tmp_path, monkeypatch, capsys):
    """The per-artifact '▶ fab-test ... → stem' line still prints as artifacts start."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    args.verbose = 1
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "fab-test pql_lint" in captured.out
    assert "SampleModel" in captured.out


# --------------------------------------------------------------------------- #
# Regression: per-artifact warning handling
# --------------------------------------------------------------------------- #


class _RunAnalyzerArgs:
    """Minimal argparse.Namespace stand-in for _run_analyzer tests."""

    def __init__(
        self,
        artifact_dir: Path,
        output_dir: Path,
        artifact: str | None = None,
        telemetry: bool | None = False,
        output_format: str = "json",
        impact_manifest: str | None = None,
        timeout: int | None = None,
        jobs: int = 1,
        dry_run: bool = False,
    ):
        self.artifact_dir = str(artifact_dir)
        self.output_dir = str(output_dir)
        self.artifact = artifact
        self.dry_run = dry_run
        self.verbose = 0
        self.telemetry = telemetry
        self.output_format = output_format
        self.environment = ""
        self.workspace_id = ""
        self.impact_manifest = impact_manifest
        self.timeout = timeout
        self.jobs = jobs


def _make_warning_envelope(output_dir: Path, analyzer: str, stem: str) -> None:
    envelope = output_dir / analyzer / stem / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps(
            {
                "status": "failed",
                "findings": [
                    {"rule": "R1", "severity": "Warning", "object": "T", "message": "m"}
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.fab_test
def test_run_analyzer_warning_no_name_error_outside_ci(tmp_path, monkeypatch):
    """Regression: warning-level findings must not raise NameError outside CI."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    _make_warning_envelope(output_dir, "pql_lint", "SampleModel")

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("pql_lint", args, output_dir)
    assert code == 0


@pytest.mark.fab_test
def test_run_analyzer_warning_emits_pr_review_comment_in_ci(tmp_path, monkeypatch):
    """Warning-level findings trigger PR review comments when running in CI."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    _make_warning_envelope(output_dir, "pql_lint", "SampleModel")

    calls = []
    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: True)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_module,
        "emit_workflow_annotations",
        lambda *a, **k: calls.append("annotation"),
    )
    monkeypatch.setattr(
        fab_test_module,
        "emit_pr_review_comments",
        lambda *a, **k: calls.append("pr_comment"),
    )
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("pql_lint", args, output_dir)
    assert code == 0
    assert "annotation" in calls
    assert "pr_comment" in calls


@pytest.mark.fab_test
def test_run_analyzer_playwright_with_impact_manifest_is_repository_scoped(
    tmp_path, monkeypatch
):
    """Playwright with --impact-manifest runs once, not per local Report artifact."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ReportOne.Report").mkdir(parents=True)
    (artifact_dir / "ReportTwo.Report").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    impact_manifest = tmp_path / "impact-manifest.json"
    impact_manifest.write_text(json.dumps({"reports": []}), encoding="utf-8")

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    commands: list[list[str]] = []

    def _fake_subprocess(*args, **kwargs):
        commands.append(list(args[0]))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(
        artifact_dir,
        output_dir,
        impact_manifest=str(impact_manifest),
    )
    code = _run_analyzer("playwright", args, output_dir)

    assert code == 0
    assert len(commands) == 1
    assert "--impact-manifest" in commands[0]


@pytest.mark.fab_test
def test_run_analyzer_error_does_not_emit_pr_review_comment(tmp_path, monkeypatch):
    """Error-level findings are annotations only; PR comments are reserved for warnings."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    envelope = output_dir / "pql_lint" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps(
            {
                "status": "failed",
                "findings": [
                    {"rule": "R1", "severity": "Error", "object": "T", "message": "m"}
                ],
            }
        ),
        encoding="utf-8",
    )

    calls = []
    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: True)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_module,
        "emit_workflow_annotations",
        lambda *a, **k: calls.append("annotation"),
    )
    monkeypatch.setattr(
        fab_test_module,
        "emit_pr_review_comments",
        lambda *a, **k: calls.append("pr_comment"),
    )
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("pql_lint", args, output_dir)
    assert code == 1
    assert "annotation" in calls
    assert "pr_comment" not in calls
