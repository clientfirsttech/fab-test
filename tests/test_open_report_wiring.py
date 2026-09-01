"""Contract tests for wiring the resolved report path into each run shape
(Open Report Flag epic, Task 3).

Scope
-----
`_print_all_summary` (the `fab-test all` index) and `_print_summary` (a
single-analyzer command) each decide, from the same `args` object Task 1
resolves, whether to hand a path to `open_report_in_browser` -- stubbed
here so no browser is ever launched. Always passes on any machine.
"""

import json
from pathlib import Path

import pytest

from fab_test.scripts import fab_test_summary
from fab_test.scripts.fab_test_summary import _print_all_summary, _print_summary


class _FakeArgs:
    """Minimal argparse.Namespace stand-in, mirroring test_fab_test_summary.py's."""

    def __init__(
        self,
        artifact_dir: Path,
        *,
        artifact: str | None = None,
        dry_run: bool = False,
        report: bool | None = None,
        open_report: bool | None = None,
    ):
        self.artifact_dir = str(artifact_dir)
        self.artifact = artifact
        self.dry_run = dry_run
        self.report = report
        self.open_report = open_report
        self.file_config: dict = {}
        self.output_format = "text"


def _write_envelope(output_dir: Path, analyzer: str, stem: str, *, report_path: str | None = None):
    envelope = output_dir / analyzer / stem / "envelope.json"
    envelope.parent.mkdir(parents=True)
    payload = {"status": "passed", "findings": []}
    if report_path is not None:
        payload["native_html_output_path"] = report_path
    envelope.write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------- #
# `fab-test all` (>1 analyzer): opens the index once
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_all_opens_the_index_once_when_open_report_is_on(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "fab-test-results"
    _write_envelope(output_dir, "bpa", "SampleModel")
    _write_envelope(output_dir, "pbir", "SampleModel")
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    (artifact_dir / "SampleModel.Report").mkdir(parents=True)

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )
    args = _FakeArgs(artifact_dir, report=None, open_report=True)

    _print_all_summary(output_dir=output_dir, analyzers=("bpa", "pbir"), codes=[0, 0], args=args)

    assert len(calls) == 1
    assert str(calls[0]).endswith("index.html")
    assert "Index:" in capsys.readouterr().out


@pytest.mark.fab_test
def test_all_does_not_open_when_open_report_is_off(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "fab-test-results"
    _write_envelope(output_dir, "bpa", "SampleModel")
    _write_envelope(output_dir, "pbir", "SampleModel")
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    (artifact_dir / "SampleModel.Report").mkdir(parents=True)

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )
    args = _FakeArgs(artifact_dir, report=True, open_report=None)

    _print_all_summary(output_dir=output_dir, analyzers=("bpa", "pbir"), codes=[0, 0], args=args)

    assert calls == []
    assert "Index:" in capsys.readouterr().out


@pytest.mark.fab_test
def test_all_guard_warns_instead_of_opening_when_report_somehow_resolves_off(
    tmp_path, monkeypatch, capsys
):
    """Should not happen post Task 1's auto-enable -- covered anyway."""
    output_dir = tmp_path / "fab-test-results"
    _write_envelope(output_dir, "bpa", "SampleModel")
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )
    monkeypatch.setattr(fab_test_summary, "resolve_report", lambda args: False)
    monkeypatch.setattr(fab_test_summary, "resolve_open_report", lambda args: True)
    args = _FakeArgs(artifact_dir)

    _print_all_summary(output_dir=output_dir, analyzers=("bpa", "pbir"), codes=[0, 0], args=args)

    assert calls == []
    assert "skipping" in capsys.readouterr().out.lower()


# --------------------------------------------------------------------------- #
# A single-analyzer command with exactly one artifact: opens that report
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_single_artifact_opens_its_own_report(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "fab-test-results"
    report_path = str(tmp_path / "report.html")
    _write_envelope(output_dir, "bpa", "SampleModel", report_path=report_path)
    artifact_dir = tmp_path / "artifacts"

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )
    args = _FakeArgs(artifact_dir, open_report=True)

    _print_summary("bpa", [("SampleModel", 0)], output_dir=output_dir, args=args)

    assert calls == [report_path]


@pytest.mark.fab_test
def test_single_artifact_does_not_open_when_open_report_is_off(tmp_path, monkeypatch):
    output_dir = tmp_path / "fab-test-results"
    report_path = str(tmp_path / "report.html")
    _write_envelope(output_dir, "bpa", "SampleModel", report_path=report_path)
    artifact_dir = tmp_path / "artifacts"

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )
    args = _FakeArgs(artifact_dir, report=True, open_report=None)

    _print_summary("bpa", [("SampleModel", 0)], output_dir=output_dir, args=args)

    assert calls == []


@pytest.mark.fab_test
def test_no_args_means_no_opening_at_all(tmp_path, monkeypatch):
    """Backward compatibility: existing callers that never pass `args`."""
    output_dir = tmp_path / "fab-test-results"
    _write_envelope(output_dir, "bpa", "SampleModel", report_path=str(tmp_path / "report.html"))

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )

    _print_summary("bpa", [("SampleModel", 0)], output_dir=output_dir)

    assert calls == []


# --------------------------------------------------------------------------- #
# A single-analyzer command with more than one artifact: note, no opening
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_multiple_artifacts_prints_a_note_and_opens_nothing(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "fab-test-results"
    _write_envelope(output_dir, "bpa", "First", report_path=str(tmp_path / "first.html"))
    _write_envelope(output_dir, "bpa", "Second", report_path=str(tmp_path / "second.html"))
    artifact_dir = tmp_path / "artifacts"

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )
    args = _FakeArgs(artifact_dir, open_report=True)

    _print_summary(
        "bpa", [("First", 0), ("Second", 0)], output_dir=output_dir, args=args
    )

    assert calls == []
    out = capsys.readouterr().out
    assert "first.html" in out
    assert "second.html" in out
    assert "multiple reports" in out.lower()


# --------------------------------------------------------------------------- #
# The guard: --open-report resolves true, resolve_report somehow doesn't
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_single_analyzer_guard_warns_instead_of_opening(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "fab-test-results"
    _write_envelope(output_dir, "bpa", "SampleModel", report_path=str(tmp_path / "report.html"))
    artifact_dir = tmp_path / "artifacts"

    calls = []
    monkeypatch.setattr(
        fab_test_summary, "open_report_in_browser", lambda path: calls.append(path) or True
    )
    monkeypatch.setattr(fab_test_summary, "resolve_report", lambda args: False)
    monkeypatch.setattr(fab_test_summary, "resolve_open_report", lambda args: True)
    args = _FakeArgs(artifact_dir)

    _print_summary("bpa", [("SampleModel", 0)], output_dir=output_dir, args=args)

    assert calls == []
    assert "skipping" in capsys.readouterr().out.lower()
