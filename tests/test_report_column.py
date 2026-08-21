"""Contract tests for the report path (Human-Readable Reports §1-2).

Scope
-----
§2 promotes `native_html_output_path` from a field set only inside
`invoke_pbir_inspector.py` to a documented *optional* envelope key. §1
surfaces it: the `all` summary gains a Report column pointing at the
readable artifact, so the one HTML report in the tree stops being
invisible.

Optional means absent, not null: an analyzer with no report omits the key
entirely, and every existing envelope stays valid without it. Always
passes on any machine — no analyzer is invoked.
"""

import json
import os
import subprocess
import sys

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_envelope import (
    ENVELOPE_OPTIONAL_KEYS,
    ENVELOPE_REQUIRED_KEYS,
    build_envelope,
)
from fabric_ci_cd_dataops.scripts.fab_test_summary import _report_path_for


def _envelope(**overrides):
    base = {
        "analyzer": "pbir",
        "artifact_path": "Sales.Report",
        "status": "passed",
    }
    base.update(overrides)
    return build_envelope(**base)


def _run_cli(*argv):
    return subprocess.run(
        [sys.executable, "-m", "fabric_ci_cd_dataops.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
        check=False,
    )


# --------------------------------------------------------------------------- #
# §2 — the envelope key
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_html_path_is_a_documented_optional_key():
    """It is part of the contract now, not a PBIR implementation detail."""
    assert "native_html_output_path" in ENVELOPE_OPTIONAL_KEYS


@pytest.mark.fab_test
def test_optional_keys_do_not_overlap_required_ones():
    """A key is required or optional, never both -- consumers branch on that."""
    assert not (ENVELOPE_OPTIONAL_KEYS & ENVELOPE_REQUIRED_KEYS)


@pytest.mark.fab_test
def test_an_envelope_without_a_report_omits_the_key_entirely():
    """Absent, not null: a consumer tests presence rather than truthiness."""
    envelope = _envelope()

    assert "native_html_output_path" not in envelope


@pytest.mark.fab_test
def test_an_envelope_with_a_report_carries_the_key():
    envelope = _envelope(native_html_output_path_str="results/pbir/Sales/TestRun.html")

    assert envelope["native_html_output_path"] == "results/pbir/Sales/TestRun.html"


@pytest.mark.fab_test
def test_an_empty_html_path_is_treated_as_no_report():
    """An empty string must not produce a key pointing nowhere."""
    assert "native_html_output_path" not in _envelope(native_html_output_path_str="")


@pytest.mark.fab_test
def test_every_envelope_still_has_all_required_keys():
    """The new key is additive: nothing about the required set changes."""
    assert set(_envelope()) >= ENVELOPE_REQUIRED_KEYS


# --------------------------------------------------------------------------- #
# §1 — reading it back
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_report_path_is_none_when_the_envelope_has_no_report():
    assert _report_path_for(_envelope()) is None


@pytest.mark.fab_test
def test_report_path_is_none_for_a_missing_envelope():
    """A dry run reads no envelope; that must not raise."""
    assert _report_path_for(None) is None


@pytest.mark.fab_test
def test_report_path_is_returned_when_present():
    envelope = _envelope(native_html_output_path_str="results/pbir/Sales/TestRun.html")

    assert _report_path_for(envelope) == "results/pbir/Sales/TestRun.html"


# --------------------------------------------------------------------------- #
# §1 — the Report column
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_summary_omits_the_column_when_no_run_produced_a_report(tmp_path):
    """An always-empty column is noise; drop it rather than print blanks.

    Checks the table header specifically. A bare substring search over
    stdout would match the ``*.Report`` glob in the discovery narration
    and pass whether or not the column was actually dropped.
    """
    (tmp_path / "Sales.SemanticModel").mkdir()

    result = _run_cli(
        "all", "--artifact-dir", str(tmp_path), "--dry-run"
    )

    assert result.returncode == 0, result.stderr
    header = next(
        (line for line in result.stdout.splitlines() if "Analyzer" in line and "Output" in line),
        None,
    )
    assert header is not None, f"no summary table header in:\n{result.stdout}"
    assert "Report" not in header, f"Report column present with no reports: {header}"


def _summary_args(artifact_dir, output_dir, output_format="text"):
    import argparse

    return argparse.Namespace(
        artifact_dir=str(artifact_dir),
        output_dir=str(output_dir),
        dry_run=False,
        output_format=output_format,
        artifact=None,
        target=None,
        resolved_target=None,
    )


def _write_envelope(output_dir, analyzer, stem, **extra):
    path = output_dir / analyzer / stem
    path.mkdir(parents=True, exist_ok=True)
    (path / "envelope.json").write_text(
        json.dumps(_envelope(analyzer=analyzer, **extra)), encoding="utf-8"
    )


@pytest.mark.fab_test
def test_summary_shows_the_column_when_a_report_exists(tmp_path, capsys):
    """The point of the feature: a readable artifact stops being invisible."""
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_all_summary

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.Report").mkdir(parents=True)
    output_dir = tmp_path / "results"
    report = output_dir / "pbir" / "Sales" / "TestRun.html"
    _write_envelope(
        output_dir, "pbir", "Sales", native_html_output_path_str=str(report)
    )

    _print_all_summary(
        output_dir, ("pbir",), [0], _summary_args(artifact_dir, output_dir)
    )

    out = capsys.readouterr().out
    header = next(line for line in out.splitlines() if "Analyzer" in line)
    assert "Report" in header
    assert "TestRun.html" in out


@pytest.mark.fab_test
def test_a_row_without_a_report_is_blank_not_the_envelope_path(tmp_path, capsys):
    """An analyzer with no report must not have envelope.json repeated into it."""
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_all_summary

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.Report").mkdir(parents=True)
    (artifact_dir / "Sales.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "results"
    _write_envelope(
        output_dir,
        "pbir",
        "Sales",
        native_html_output_path_str=str(output_dir / "pbir" / "Sales" / "TestRun.html"),
    )
    _write_envelope(output_dir, "bpa", "Sales")

    _print_all_summary(
        output_dir, ("pbir", "bpa"), [0, 0], _summary_args(artifact_dir, output_dir)
    )

    out = capsys.readouterr().out
    # Rows are boxed, so strip the border characters before reading a cell.
    bpa_line = next(
        line for line in out.splitlines() if line.strip().lstrip("│ ").startswith("bpa")
    )
    assert "TestRun.html" not in bpa_line
    report_cell = bpa_line.strip().strip("│").rsplit("│", 1)[-1]
    assert not report_cell.strip(), (
        f"bpa's Report cell should be empty, got: {report_cell!r}"
    )


@pytest.mark.fab_test
def test_summary_json_exposes_the_report_path_separately(tmp_path):
    """output_path keeps its meaning; the report is its own field."""
    (tmp_path / "Sales.SemanticModel").mkdir()

    result = _run_cli(
        "all", "--artifact-dir", str(tmp_path), "--dry-run", "--format", "json"
    )

    assert result.returncode == 0, result.stderr
    for row in json.loads(result.stdout)["artifacts"]:
        assert "report_path" in row, "report_path must always be present, even as null"
        assert "output_path" in row
