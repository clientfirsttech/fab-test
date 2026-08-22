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
def test_the_summary_table_carries_no_path_columns(tmp_path):
    """Paths live below the table, not in it.

    A full envelope path is ~60 characters and identically shaped on every
    row; two such columns pushed the table past 200 characters, which
    wrapped three times in an 80-column terminal.
    """
    (tmp_path / "Sales.SemanticModel").mkdir()

    result = _run_cli("all", "--artifact-dir", str(tmp_path), "--dry-run")

    assert result.returncode == 0, result.stderr
    header = next(
        (line for line in result.stdout.splitlines() if "Analyzer" in line and "Status" in line),
        None,
    )
    assert header is not None, f"no summary table header in:\n{result.stdout}"
    assert "Output" not in header, header
    assert "Report" not in header, header


@pytest.mark.fab_test
def test_the_summary_table_fits_a_standard_terminal(tmp_path):
    """The whole point of moving paths out: no row may wrap at 80 columns."""
    (tmp_path / "Sales.SemanticModel").mkdir()
    (tmp_path / "Sales.Report").mkdir()

    result = _run_cli("all", "--artifact-dir", str(tmp_path), "--dry-run")

    assert result.returncode == 0, result.stderr
    table_lines = [ln for ln in result.stdout.splitlines() if "│" in ln or "╭" in ln]
    assert table_lines, "no table rendered"
    widest = max(len(ln) for ln in table_lines)
    assert widest <= 80, f"table is {widest} chars wide:\n" + "\n".join(table_lines)


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
def test_the_report_path_is_listed_below_the_table(tmp_path, capsys):
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
    assert "pbir/Sales" in out, "the listing should name the analyzer and artifact"
    assert "TestRun.html" in out
    # Whole, not truncated -- that is what keeps it clickable.
    assert "..." not in out


@pytest.mark.fab_test
def test_an_artifact_without_a_report_falls_back_to_its_envelope(tmp_path, capsys):
    """Every artifact gets one clickable line: the report, or the envelope."""
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

    lines = capsys.readouterr().out.splitlines()
    bpa_index = next(i for i, ln in enumerate(lines) if ln.strip() == "bpa/Sales")
    pbir_index = next(i for i, ln in enumerate(lines) if ln.strip() == "pbir/Sales")

    # pbir has an upstream report; bpa has none, so it lists its envelope.
    assert "TestRun.html" in lines[pbir_index + 1]
    assert lines[bpa_index + 1].strip().endswith("envelope.json")


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


# --------------------------------------------------------------------------- #
# A single-analyzer run must surface its report too
#
# Regression: `fab-test pql-test <target> --report` wrote report.html and
# never mentioned it. `fab-test all` lists paths under its table; one
# analyzer listed nothing, so the flag was indistinguishable from a no-op.
# --------------------------------------------------------------------------- #


def _envelope_on_disk(output_dir, analyzer, stem, **extra):
    from fabric_ci_cd_dataops.scripts._analyzer_envelope import build_envelope

    path = output_dir / analyzer / stem
    path.mkdir(parents=True, exist_ok=True)
    (path / "envelope.json").write_text(
        json.dumps(
            build_envelope(analyzer=analyzer, artifact_path=stem, status="passed", **extra)
        ),
        encoding="utf-8",
    )


@pytest.mark.fab_test
def test_single_analyzer_run_names_its_report(tmp_path, capsys):
    """The flag has to be visibly doing something, or it reads as broken."""
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_summary

    report = tmp_path / "pql_test" / "Sales" / "report.html"
    _envelope_on_disk(
        tmp_path, "pql_test", "Sales", native_html_output_path_str=str(report)
    )

    _print_summary("pql_test", [("Sales", 0)], output_dir=tmp_path, output_format="text")

    assert "report.html" in capsys.readouterr().out


@pytest.mark.fab_test
def test_single_analyzer_run_without_a_report_invents_nothing(tmp_path, capsys):
    """No --report means no report; the summary must not imply one exists."""
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_summary

    _envelope_on_disk(tmp_path, "bpa", "Sales")

    _print_summary("bpa", [("Sales", 0)], output_dir=tmp_path, output_format="text")

    assert "report.html" not in capsys.readouterr().out


@pytest.mark.fab_test
def test_single_analyzer_json_carries_report_path_like_all_does(tmp_path, capsys):
    """One analyzer and `all` must not disagree about the row shape."""
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_summary

    report = tmp_path / "pql_test" / "Sales" / "report.html"
    _envelope_on_disk(
        tmp_path, "pql_test", "Sales", native_html_output_path_str=str(report)
    )

    _print_summary("pql_test", [("Sales", 0)], output_dir=tmp_path, output_format="json")

    row = json.loads(capsys.readouterr().out)["artifacts"][0]
    assert "report_path" in row, "report_path must be present, as it is under `all`"
    assert row["report_path"] == str(report)


@pytest.mark.fab_test
def test_all_suppresses_the_per_analyzer_report_line(tmp_path, monkeypatch):
    """Regression: `all` named every report twice.

    `_print_summary` runs once per analyzer inside `all`, so surfacing the
    report there duplicated the aggregate listing that already existed.
    Asserts the wiring rather than the rendered output, because `all`
    really runs the analyzers and would overwrite any fixture envelope.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    seen: dict[str, bool] = {}

    def _spy(name, results, **kwargs):
        seen[name] = kwargs.get("show_reports", True)
        return 0

    monkeypatch.setattr(fab_test_module, "_print_summary", _spy)
    monkeypatch.setattr(fab_test_module, "_preflight", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module, "_run_one_artifact", lambda *a, **k: ("Sales", 0))
    (tmp_path / "Sales.SemanticModel").mkdir()

    import argparse

    args = argparse.Namespace(
        analyzer="all", artifact_dir=str(tmp_path), output_format="text",
        dry_run=False, artifact=None, target=None, resolved_target=None,
        jobs=1, timeout=None, file_config={}, report=True, telemetry=False,
    )
    fab_test_module._run_analyzer("bpa", args, tmp_path / "results")

    assert seen == {"bpa": False}, "under `all`, the per-analyzer Report line must be off"


@pytest.mark.fab_test
def test_a_standalone_run_keeps_the_per_analyzer_report_line(tmp_path, monkeypatch):
    """One analyzer has no aggregate listing, so the line is the only mention."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    seen: dict[str, bool] = {}
    monkeypatch.setattr(
        fab_test_module, "_print_summary",
        lambda name, results, **kw: (seen.setdefault(name, kw.get("show_reports", True)) and 0) or 0,
    )
    monkeypatch.setattr(fab_test_module, "_preflight", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module, "_run_one_artifact", lambda *a, **k: ("Sales", 0))
    (tmp_path / "Sales.SemanticModel").mkdir()

    import argparse

    args = argparse.Namespace(
        analyzer="bpa", artifact_dir=str(tmp_path), output_format="text",
        dry_run=False, artifact=None, target=None, resolved_target=None,
        jobs=1, timeout=None, file_config={}, report=True, telemetry=False,
    )
    fab_test_module._run_analyzer("bpa", args, tmp_path / "results")

    assert seen == {"bpa": True}


@pytest.mark.fab_test
def test_local_still_names_its_reports(tmp_path):
    """`local` has no aggregate listing, so its per-analyzer lines must stay.

    Suppressing the Report line for every bundle would have removed the
    information from `local` entirely rather than de-duplicating it.
    """
    from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_summary

    path = tmp_path / "pql_lint" / "Sales"
    path.mkdir(parents=True)
    (path / "envelope.json").write_text(
        json.dumps(
            build_envelope(
                analyzer="pql_lint",
                artifact_path="Sales",
                status="passed",
                native_html_output_path_str=str(path / "report.html"),
            )
        ),
        encoding="utf-8",
    )
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_summary("pql_lint", [("Sales", 0)], output_dir=tmp_path, show_reports=True)

    assert "report.html" in buffer.getvalue()
