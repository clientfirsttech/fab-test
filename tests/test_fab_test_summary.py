"""Summary formatting: findings tables, per-artifact and aggregate summaries.

Scope
-----
_format_findings' generic and pql-test table rendering, _print_summary's
severity breakdown and JSON output, and _print_all_summary's aggregate
error/warning totals across analyzers.

    pytest -m fab_test
"""
import json
import subprocess
from pathlib import Path

import pytest

from fab_test.scripts._analyzer_envelope import finding_status
from fab_test.scripts.fab_test import _print_all_summary, _print_summary
from fab_test.scripts.fab_test_summary import (
    _artifact_status,
    _artifact_summary_prefix,
    _format_findings,
    _is_pql_test_finding,
)

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
    """finding_status maps result fields to PASS/FAIL/SKIPPED/ERROR."""
    assert finding_status({"passed": True}) == "PASS"
    assert finding_status({"passed": False}) == "FAIL"
    assert finding_status({"passed": False, "skipped": True}) == "SKIPPED"
    assert finding_status({"passed": False, "error": "x"}) == "ERROR"


@pytest.mark.fab_test
def test_artifact_status_reports_a_warning_envelope_as_a_warning():
    """A warning envelope that exited 0 is a warning, not a pass.

    pql-test writes this when nothing could execute. Falling through to
    "passed" would show a green check over a run in which no test ran.
    """
    assert _artifact_status({"status": "warning"}, code=0, errors=0, warnings=0) == (
        "warning"
    )


@pytest.mark.fab_test
def test_artifact_summary_prefix_marks_a_warning_run():
    """A warning run gets its own icon rather than the green check."""
    assert _artifact_summary_prefix(0, "warning") == "⚠️"
    assert _artifact_summary_prefix(0, "passed") == "✅"
    assert _artifact_summary_prefix(1, "failed") == "❌"


@pytest.mark.fab_test
def test_print_summary_shows_test_summary_and_severity_breakdown(tmp_path, capsys):
    """Summary line includes test counters and error/warning breakdown."""
    output_dir = tmp_path / "fab-test-results"
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
    output_dir = tmp_path / "fab-test-results"
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
    output_dir = tmp_path / "fab-test-results"
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
    output_dir = tmp_path / "fab-test-results"
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
    output_dir = tmp_path / "fab-test-results"
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
    output_dir = tmp_path / "fab-test-results"
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
    output_dir = tmp_path / "fab-test-results"
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
    output_dir = tmp_path / "fab-test-results"
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


