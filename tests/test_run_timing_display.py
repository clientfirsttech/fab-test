"""Run timing where people look (Run Timing epic, task 3).

Runs are compared by hand: each keeps its own --output-dir, and the reader
opens both pages. So the terminal summary, index.html, report.html, and the
--format json document each carry the timing, built from the run manifest
(task 1) and the playwright envelope's `timings` (task 2).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts._report_html import render_index, render_report
from fab_test.scripts._run_manifest import RunManifest
from fab_test.scripts._run_timing import add_durations, format_duration, print_timing_line, timing_line

pytestmark = pytest.mark.fab_test


@pytest.mark.parametrize(("milliseconds", "expected"), [
    (41_049, "41.0s"),
    (252_000, "4m12s"),
    (3_780_000, "1h03m"),
    (None, ""),
])
def test_durations_read_at_a_glance(milliseconds, expected):
    assert format_duration(milliseconds) == expected


def _args(*durations: int | None, execution: dict | None = None, wall_ms: int = 4000, **flags) -> argparse.Namespace:
    manifest = RunManifest("1.0.0", ["fab-test", "playwright"])
    manifest.elapsed_ms = lambda: wall_ms  # a fixed clock
    manifest.execution = execution
    for index, duration in enumerate(durations):
        manifest.record_artifact("playwright", f"R{index}", "passed", None, 0, 0, duration_ms=duration)
    return argparse.Namespace(run_manifest=manifest, output_format="text", quiet=False, **flags)


def test_the_run_line_names_wall_clock_artifact_time_ratio_and_settings():
    args = _args(6000, 8000, execution={"backend": "azure", "jobs": 4, "workers": 8})

    assert timing_line(args) == "Wall 4.0s · artifact time 14.0s · 3.5x parallel · azure, jobs 4, workers 8"


def test_an_artifact_that_never_ran_adds_no_time():
    assert timing_line(_args(6000, None)) == "Wall 4.0s · artifact time 6.0s · 1.5x parallel"


def test_a_multi_artifact_text_run_ends_with_the_run_line(capsys):
    print_timing_line(_args(1000, 2000))

    assert capsys.readouterr().out.strip().startswith("⏱ Wall 4.0s")


@pytest.mark.parametrize("flags", [{"quiet": True}, {"output_format": "json"}])
def test_quiet_and_json_keep_their_own_formats(flags, capsys):
    args = _args(1000, 2000)
    vars(args).update(flags)

    print_timing_line(args)

    assert capsys.readouterr().out == ""


def test_a_single_artifact_run_prints_no_run_line(capsys):
    print_timing_line(_args(1000))

    assert capsys.readouterr().out == ""


def test_the_index_shows_each_artifacts_duration_and_the_run_line(tmp_path: Path):
    rows = [{"analyzer": "playwright", "artifact": "R0", "status": "passed", "errors": 0, "warnings": 0}]
    add_durations(rows, _args(61_000))

    page = render_index(rows, tmp_path, run_summary="Wall 4.0s · artifact time 1m01s · 15.3x parallel")

    assert "<th>Duration</th>" in page
    assert '<td class="num">1m01s</td>' in page
    assert "⏱ Wall 4.0s · artifact time 1m01s" in page


def test_an_index_without_timing_renders_as_before(tmp_path: Path):
    rows = [{"analyzer": "bpa", "artifact": "M", "status": "passed", "errors": 0, "warnings": 0}]

    page = render_index(rows, tmp_path)

    assert "Duration" not in page
    assert "run-timing" not in page


def _playwright_envelope() -> dict:
    case = {"suite_name": "Sales", "expected": "rendered", "actual": "rendered", "status": "pass"}
    return {
        "analyzer": "playwright",
        "artifact_path": "Sales",
        "status": "passed",
        "test_results": [
            {**case, "test_name": "fast", "duration_ms": 2_000},
            {**case, "test_name": "slow", "duration_ms": 75_500},
            {**case, "test_name": "unknown"},
        ],
        "timings": {
            "discovery_ms": 4100, "token_ms": 1200, "render_ms": 35100, "total_ms": 41000,
            "browser_setup_ms": 6000, "backend": "azure", "workers": 8,
        },
    }


def test_the_report_shows_where_the_time_went_and_the_slowest_cases_first():
    page = render_report(_playwright_envelope())

    assert "⏱ Discovery 4.1s · Embed tokens 1.2s · Render 35.1s · Total 41.0s" in page
    assert "browser setup 6.0s (summed across cases) · azure, workers 8" in page
    assert page.index("<code>slow</code> 1m16s") < page.index("<code>fast</code> 2.0s")


def test_the_report_gives_each_case_a_sortable_duration():
    page = render_report(_playwright_envelope())

    assert "<th>Duration</th>" in page
    assert "<td>75.5s</td>" in page  # seconds, never 1m16s, so the column sorts numerically


def test_a_report_without_timings_renders_as_before():
    envelope = _playwright_envelope()
    del envelope["timings"]
    for row in envelope["test_results"]:
        row.pop("duration_ms", None)

    page = render_report(envelope)

    assert "run-timing" not in page
    assert "Duration" not in page


def test_format_json_carries_each_artifacts_duration_and_the_run_timing(tmp_path: Path, monkeypatch, capsys):
    from fab_test.scripts import fab_test as fab_test_module
    from fab_test.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    for stem in ("A", "B"):
        (artifact_dir / f"{stem}.Report").mkdir(parents=True)
    output_dir = tmp_path / "results"

    def _run(cmd, **_kwargs):
        stem = "A" if "A.Report" in " ".join(map(str, cmd)) else "B"
        envelope = output_dir / "pbir" / stem / "envelope.json"
        envelope.parent.mkdir(parents=True, exist_ok=True)
        envelope.write_text(json.dumps({"status": "passed", "findings": []}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _run)
    monkeypatch.setattr(fab_test_execution, "_preflight_error", lambda *a, **k: None)
    monkeypatch.setattr(
        sys, "argv",
        ["fab-test", "pbir", "--artifact-dir", str(artifact_dir), "--output-dir", str(output_dir), "--format", "json"],
    )

    fab_test_module.main()

    document = json.loads(capsys.readouterr().out)
    assert all(isinstance(row["duration_ms"], int) for row in document["artifacts"])
    assert {"wall_ms", "artifact_ms", "parallel"} <= set(document["timing"])
