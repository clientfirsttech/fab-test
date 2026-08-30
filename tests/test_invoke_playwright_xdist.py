"""pytest-xdist concurrency for generated Playwright cases (Playwright Case
Scaling epic).

Scope
-----
Split out of test_invoke_playwright.py once this section pushed that file
over its hard line budget. `_resolve_xdist_workers`'s bounded-worker-count
formula and `_run_pytest`'s actual `-n` command-line construction --
`_run_pytest` is otherwise always mocked wholesale in test_invoke_playwright.py,
never argv-tested, so these use a stubbed `_stream_subprocess` to capture
the real constructed command.

    pytest -m playwright tests/test_invoke_playwright_xdist.py
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from fabric_ci_cd_dataops.scripts.invoke_playwright import (
    _XDIST_MAX_WORKERS,
    _resolve_xdist_workers,
    _run_pytest,
)

_ROOT = Path(__file__).resolve().parent.parent


def test_pytest_xdist_is_a_dev_dependency() -> None:
    """`_run_pytest` passes `-n <workers>` once there is more than one case;
    pytest rejects `-n` as unrecognized without `pytest-xdist` installed."""
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(d.startswith("pytest-xdist") for d in dev), dev


class TestResolveXdistWorkers:
    def test_a_single_case_needs_no_parallelism(self) -> None:
        assert _resolve_xdist_workers(1) is None
        assert _resolve_xdist_workers(0) is None

    def test_worker_count_matches_case_count_under_the_cap(self) -> None:
        assert _resolve_xdist_workers(2) == 2
        assert _resolve_xdist_workers(3) == 3

    def test_worker_count_is_capped_for_a_large_matrix(self) -> None:
        """Unconditionally maximal parallelism (e.g. `-n auto`) risks
        exhausting local memory/CPU -- each worker opens its own browser."""
        assert _resolve_xdist_workers(100) == _XDIST_MAX_WORKERS


class TestRunPytestXdistArgs:
    """`_run_pytest` is otherwise always mocked wholesale elsewhere; these
    exercise its actual command-line construction via a stubbed
    `_stream_subprocess`, so no real pytest subprocess is spawned."""

    def _fake_pytest_argv_capture(self, monkeypatch, tmp_path: Path) -> list[str]:
        captured: list[list[str]] = []

        def _fake_stream_subprocess(command, **_kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(
            "fabric_ci_cd_dataops.scripts.invoke_playwright._stream_subprocess",
            _fake_stream_subprocess,
        )
        return captured

    def test_a_single_case_omits_dash_n(self, monkeypatch, tmp_path: Path) -> None:
        captured = self._fake_pytest_argv_capture(monkeypatch, tmp_path)

        _run_pytest({}, verbosity=0, case_count=1)

        assert "-n" not in captured[0]

    def test_more_than_one_case_passes_dash_n(self, monkeypatch, tmp_path: Path) -> None:
        captured = self._fake_pytest_argv_capture(monkeypatch, tmp_path)

        _run_pytest({}, verbosity=0, case_count=3)

        command = captured[0]
        assert "-n" in command
        assert command[command.index("-n") + 1] == "3"

    def test_default_case_count_omits_dash_n(self, monkeypatch, tmp_path: Path) -> None:
        """The default (case_count=1) matches every existing mocked caller
        of _run_pytest elsewhere in test_invoke_playwright.py, none of which
        pass it."""
        captured = self._fake_pytest_argv_capture(monkeypatch, tmp_path)

        _run_pytest({}, verbosity=0)

        assert "-n" not in captured[0]
