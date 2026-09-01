"""Playwright's case-count-scaled outer subprocess timeout (Playwright Case
Scaling epic).

Scope
-----
`_playwright_timeout_scaling.py`'s pure logic (`scaled_playwright_timeout`,
`read_playwright_case_count`) plus `run_playwright_with_scaled_timeout`'s
real-subprocess behavior: a run that writes its cases file and then
legitimately needs longer than the flat default must not be killed early,
one that never generates cases (or hangs before writing them) still gets
the same flat-default protection today's behavior already had, and an
explicit --timeout/ANALYZER_TIMEOUT bypasses scaling entirely (tested via
`fab_test_execution._run_artifact_process`'s dispatch condition).

    pytest -m fab_test tests/test_playwright_timeout_scaling.py
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts import (
    _playwright_timeout_scaling as scaling,
)
from fab_test.scripts import fab_test_execution


@pytest.mark.fab_test
class TestScaledTimeoutFormula:
    def test_never_falls_below_the_flat_default(self, monkeypatch):
        """A report generating only one or two cases must not regress today's behavior."""
        monkeypatch.setattr(scaling, "PLAYWRIGHT_FIXED_OVERHEAD_SECONDS", 0)
        monkeypatch.delenv("PLAYWRIGHT_TIMEOUT_SECONDS", raising=False)

        assert scaling.scaled_playwright_timeout(1) == scaling._DEFAULT_SUBPROCESS_TIMEOUT
        assert scaling.scaled_playwright_timeout(0) == scaling._DEFAULT_SUBPROCESS_TIMEOUT

    def test_scales_with_case_count(self, monkeypatch):
        monkeypatch.setattr(scaling, "PLAYWRIGHT_FIXED_OVERHEAD_SECONDS", 60)
        monkeypatch.setenv("PLAYWRIGHT_TIMEOUT_SECONDS", "180")

        assert scaling.scaled_playwright_timeout(10) == 60 + 180 * 10

    def test_reads_per_case_seconds_at_call_time_not_import_time(self, monkeypatch):
        """A module-level constant frozen at import couldn't be monkeypatched
        by a test at all -- this is why it's a function, not a constant."""
        monkeypatch.setenv("PLAYWRIGHT_TIMEOUT_SECONDS", "5")
        assert scaling.playwright_per_case_seconds() == 5

    def test_malformed_env_value_falls_back_to_180(self, monkeypatch):
        monkeypatch.setenv("PLAYWRIGHT_TIMEOUT_SECONDS", "not-a-number")
        assert scaling.playwright_per_case_seconds() == 180


@pytest.mark.fab_test
class TestReadPlaywrightCaseCount:
    def test_missing_file_returns_none(self, tmp_path: Path):
        assert scaling.read_playwright_case_count(tmp_path / "missing.json") is None

    def test_counts_a_json_array(self, tmp_path: Path):
        path = tmp_path / "test-cases.json"
        path.write_text(json.dumps([{"a": 1}, {"a": 2}, {"a": 3}]), encoding="utf-8")
        assert scaling.read_playwright_case_count(path) == 3

    def test_partial_write_returns_none_rather_than_raising(self, tmp_path: Path):
        """A file mid-write (truncated JSON) is treated as not-ready-yet,
        not a crash -- the poll loop just tries again next tick."""
        path = tmp_path / "test-cases.json"
        path.write_text('[{"a": 1}, {"a"', encoding="utf-8")
        assert scaling.read_playwright_case_count(path) is None

    def test_non_list_json_returns_none(self, tmp_path: Path):
        path = tmp_path / "test-cases.json"
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        assert scaling.read_playwright_case_count(path) is None


def _fake_case_writer_script(cases_path: str, case_count: int, sleep_seconds: float, exit_code: int = 0) -> str:
    """A Python one-liner standing in for invoke_playwright.py: writes its
    generated-cases file immediately (like _run_single_report does, well
    before pytest starts), then simulates a run that takes `sleep_seconds`."""
    return (
        "import json, pathlib, time, sys; "
        f"p = pathlib.Path(r'{cases_path}'); "
        "p.parent.mkdir(parents=True, exist_ok=True); "
        f"p.write_text(json.dumps([{{'case': i}} for i in range({case_count})])); "
        f"time.sleep({sleep_seconds}); "
        f"sys.exit({exit_code})"
    )


def _make_ctx(timeout: int, timeout_is_default: bool) -> fab_test_execution._RunContext:
    return fab_test_execution._RunContext(
        in_ci=False,
        sub_env={},
        timeout=timeout,
        timeout_is_default=timeout_is_default,
        manifest=None,
        telemetry=None,
    )


@pytest.mark.fab_test
class TestRunPlaywrightWithScaledTimeout:
    def test_a_run_that_needs_more_than_the_flat_default_is_not_killed(self, tmp_path, monkeypatch):
        """The real defect this epic exists to fix: a report whose matrix
        takes longer than the flat default must survive once its real case
        count is known -- proven with a real subprocess, not a mock.
        """
        monkeypatch.setattr(scaling, "_DEFAULT_SUBPROCESS_TIMEOUT", 2)
        monkeypatch.setattr(scaling, "PLAYWRIGHT_FIXED_OVERHEAD_SECONDS", 0)
        monkeypatch.setattr(scaling, "PLAYWRIGHT_POLL_INTERVAL_SECONDS", 0.05)
        monkeypatch.setenv("PLAYWRIGHT_TIMEOUT_SECONDS", "2")

        cases_path = tmp_path / "test-cases.json"
        # 3 cases * 2s/case = 6s scaled budget; sleeps 3s -- well past the
        # flat 2s default, comfortably inside the scaled one.
        script = _fake_case_writer_script(str(cases_path), case_count=3, sleep_seconds=3)
        cmd = [sys.executable, "-c", script]
        ctx = _make_ctx(timeout=2, timeout_is_default=True)

        result = scaling.run_playwright_with_scaled_timeout(
            cmd, ctx, capture_stdout=False, output_format="text",
            name="playwright", display_name="Sales", test_cases_path=cases_path,
            narration=scaling.Narration(reemit_lines=lambda *a, **k: None, narrate=lambda *a, **k: None),
        )

        assert isinstance(result, subprocess.CompletedProcess), result
        assert result.returncode == 0

    def test_a_run_that_never_writes_cases_still_respects_the_flat_default(self, tmp_path, monkeypatch):
        """No cases file ever appears (e.g. discovery hangs) -- falls back to
        exactly today's behavior: killed at the flat default, not left to
        run forever."""
        monkeypatch.setattr(scaling, "_DEFAULT_SUBPROCESS_TIMEOUT", 1)
        monkeypatch.setattr(scaling, "PLAYWRIGHT_POLL_INTERVAL_SECONDS", 0.05)

        cases_path = tmp_path / "test-cases.json"  # never written
        cmd = [sys.executable, "-c", "import time; time.sleep(5)"]
        ctx = _make_ctx(timeout=1, timeout_is_default=True)

        result = scaling.run_playwright_with_scaled_timeout(
            cmd, ctx, capture_stdout=False, output_format="text",
            name="playwright", display_name="Sales", test_cases_path=cases_path,
            narration=scaling.Narration(reemit_lines=lambda *a, **k: None, narrate=lambda *a, **k: None),
        )

        assert result == ("Sales", 1)

    def test_a_scaled_run_that_still_exceeds_its_new_deadline_is_killed(self, tmp_path, monkeypatch):
        """Scaling raises the ceiling; it does not remove one."""
        monkeypatch.setattr(scaling, "_DEFAULT_SUBPROCESS_TIMEOUT", 1)
        monkeypatch.setattr(scaling, "PLAYWRIGHT_FIXED_OVERHEAD_SECONDS", 0)
        monkeypatch.setattr(scaling, "PLAYWRIGHT_POLL_INTERVAL_SECONDS", 0.05)
        monkeypatch.setenv("PLAYWRIGHT_TIMEOUT_SECONDS", "1")

        cases_path = tmp_path / "test-cases.json"
        # 1 case * 1s/case = 1s scaled budget; sleeps far longer than that.
        script = _fake_case_writer_script(str(cases_path), case_count=1, sleep_seconds=5)
        cmd = [sys.executable, "-c", script]
        ctx = _make_ctx(timeout=1, timeout_is_default=True)

        result = scaling.run_playwright_with_scaled_timeout(
            cmd, ctx, capture_stdout=False, output_format="text",
            name="playwright", display_name="Sales", test_cases_path=cases_path,
            narration=scaling.Narration(reemit_lines=lambda *a, **k: None, narrate=lambda *a, **k: None),
        )

        assert result == ("Sales", 1)


@pytest.mark.fab_test
class TestRunArtifactProcessDispatch:
    def test_playwright_with_default_timeout_uses_the_scaled_path(self, tmp_path, monkeypatch):
        """The dispatch condition itself: default timeout + a real
        (non-impact-manifest) playwright run takes the new code path."""
        called = {}

        def _fake_scaled(*args, **kwargs):
            called["used"] = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(fab_test_execution, "run_playwright_with_scaled_timeout", _fake_scaled)
        ctx = _make_ctx(timeout=200, timeout_is_default=True)

        fab_test_execution._run_artifact_process(
            [sys.executable, "--version"], ctx, False, "text", "playwright", "Sales",
            test_cases_path=tmp_path / "test-cases.json",
        )

        assert called.get("used") is True

    def test_explicit_timeout_bypasses_scaling_entirely(self, monkeypatch):
        """An explicit --timeout/ANALYZER_TIMEOUT/config value is honored as
        an override -- the caller's own choice is never silently replaced."""
        called = {}

        def _fake_scaled(*args, **kwargs):
            called["used"] = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(fab_test_execution, "run_playwright_with_scaled_timeout", _fake_scaled)
        ctx = _make_ctx(timeout=5, timeout_is_default=False)

        result = fab_test_execution._run_artifact_process(
            [sys.executable, "--version"], ctx, False, "text", "playwright", "Sales",
        )

        assert "used" not in called
        assert isinstance(result, subprocess.CompletedProcess)

    def test_non_playwright_analyzers_are_completely_unaffected(self, monkeypatch):
        """bpa/pbir/etc. never take the new code path, default timeout or not."""
        called = {}

        def _fake_scaled(*args, **kwargs):
            called["used"] = True
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(fab_test_execution, "run_playwright_with_scaled_timeout", _fake_scaled)
        ctx = _make_ctx(timeout=200, timeout_is_default=True)

        result = fab_test_execution._run_artifact_process(
            [sys.executable, "--version"], ctx, False, "text", "bpa", "Sales",
        )

        assert "used" not in called
        assert isinstance(result, subprocess.CompletedProcess)
