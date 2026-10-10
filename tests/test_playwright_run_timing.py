"""Where a playwright report's time went (Run Timing epic, task 2).

The timing plugin records each case's setup and render time beside its
result.json; the wrapper reads them into `test_results` and times its own
phases (discovery, embed tokens, render) into the envelope's `timings`.

Always passes on any machine: no browser or Power BI service is invoked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fab_test.scripts.invoke_playwright import _run_pytest, main
from fab_test.scripts.playwright_validation import timing_plugin
from fab_test.scripts.playwright_validation.phase_timing import TIMING_FILENAME, TIMING_PLUGIN
from tests.test_playwright_test_results import _config, _write_case_result

pytestmark = pytest.mark.playwright

_CASES = ("SalesReport_page1_no-bookmark", "SalesReport_page2_no-bookmark")


def _run(tmp_path: Path, session_timing: dict[str, dict[str, int]]) -> dict:
    """Run the wrapper with a fake pytest session that writes ``session_timing`` per case."""
    from fab_test.scripts.playwright_validation.power_bi_api import EmbedContext

    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    for case_id in _CASES:
        _write_case_result(test_cases_dir, case_id, "pass")

    def _session(*_args, **_kwargs):
        for case_id, timing in session_timing.items():
            (test_cases_dir / case_id / TIMING_FILENAME).write_text(json.dumps(timing), encoding="utf-8")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    embed = EmbedContext(
        embed_url="https://app.powerbi.com/embed", embed_token="t", report_id="rpt-1", dataset_id="ds-1"
    )
    with (
        patch("fab_test.scripts.invoke_playwright.load_config", return_value=_config()),
        patch("fab_test.scripts.playwright_validation.discovery.get_embed_context", return_value=embed),
        patch("fab_test.scripts.invoke_playwright._run_pytest", side_effect=_session),
        patch("fab_test.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        main(["--env-file", ".env", "--output-path", str(output_path), "--test-cases-dir", str(test_cases_dir)])
    return json.loads(output_path.read_text(encoding="utf-8"))


def test_each_case_carries_its_render_and_setup_time(tmp_path: Path):
    data = _run(tmp_path, {
        _CASES[0]: {"setup_ms": 4200, "duration_ms": 9100},
        _CASES[1]: {"setup_ms": 300, "duration_ms": 12500},
    })

    by_case = {row["test_name"]: row for row in data["test_results"]}
    assert (by_case[_CASES[0]]["duration_ms"], by_case[_CASES[0]]["setup_ms"]) == (9100, 4200)
    assert by_case[_CASES[1]]["duration_ms"] == 12500


def test_the_envelope_records_each_phase_and_the_settings_behind_them(tmp_path: Path):
    data = _run(tmp_path, {_CASES[0]: {"setup_ms": 4200, "duration_ms": 9100}})

    timings = data["timings"]
    assert {"discovery_ms", "token_ms", "render_ms", "total_ms"} <= set(timings)
    assert timings["browser_setup_ms"] == 4200
    assert timings["total_ms"] >= timings["render_ms"]
    assert (timings["backend"], timings["workers"]) == ("local", 2)
    assert data["started_at"].endswith("+00:00")


def test_a_case_that_did_not_run_this_time_reports_no_duration(tmp_path: Path):
    """An earlier run's timing.json must not be read as this run's."""
    stale = tmp_path / "test-cases" / _CASES[0]
    stale.mkdir(parents=True)
    (stale / TIMING_FILENAME).write_text(json.dumps({"duration_ms": 1}), encoding="utf-8")

    data = _run(tmp_path, {})

    assert all("duration_ms" not in row for row in data["test_results"])
    assert "browser_setup_ms" not in data["timings"]


def test_the_timing_plugin_is_loaded_on_every_run(monkeypatch):
    captured: list[list[str]] = []
    monkeypatch.setattr(
        "fab_test.scripts.invoke_playwright._stream_subprocess",
        lambda command, **_k: captured.append(command) or subprocess.CompletedProcess(command, 0, "", ""),
    )

    _run_pytest({}, verbosity=0, case_count=1)

    assert captured[0][captured[0].index("-p") + 1] == TIMING_PLUGIN


def test_the_plugin_writes_setup_and_render_time_beside_the_cases_result(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    item = SimpleNamespace(callspec=SimpleNamespace(params={"case": {"test_case": "Sales_p1"}}))

    for when, seconds in (("setup", 1.25), ("call", 8.5), ("teardown", 0.1)):
        hook = timing_plugin.pytest_runtest_makereport(item, SimpleNamespace(when=when, duration=seconds))
        next(hook)
        with pytest.raises(StopIteration):
            hook.send(None)

    assert json.loads((tmp_path / "Sales_p1" / TIMING_FILENAME).read_text(encoding="utf-8")) == {
        "setup_ms": 1250,
        "duration_ms": 8500,
    }
