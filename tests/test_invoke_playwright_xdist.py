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

from fab_test.scripts.invoke_playwright import (
    _XDIST_MAX_WORKERS,
    _resolve_max_workers,
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


class TestResolveMaxWorkers:
    """--workers > PLAYWRIGHT_XDIST_WORKERS > packaged default (4) -- the
    same precedence shape every other fab-test setting uses."""

    def test_defaults_to_the_packaged_constant(self, monkeypatch) -> None:
        monkeypatch.delenv("PLAYWRIGHT_XDIST_WORKERS", raising=False)
        assert _resolve_max_workers(None) == _XDIST_MAX_WORKERS

    def test_env_var_overrides_the_default(self, monkeypatch) -> None:
        """A beefier VM can raise the cap without a CLI flag on every invocation."""
        monkeypatch.setenv("PLAYWRIGHT_XDIST_WORKERS", "12")
        assert _resolve_max_workers(None) == 12

    def test_explicit_value_overrides_the_env_var(self, monkeypatch) -> None:
        monkeypatch.setenv("PLAYWRIGHT_XDIST_WORKERS", "12")
        assert _resolve_max_workers(6) == 6

    def test_malformed_env_value_falls_back_to_the_default(self, monkeypatch) -> None:
        monkeypatch.setenv("PLAYWRIGHT_XDIST_WORKERS", "not-a-number")
        assert _resolve_max_workers(None) == _XDIST_MAX_WORKERS


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

    def test_a_raised_cap_is_honored(self) -> None:
        """The whole point of making this configurable: a machine that can
        safely run more concurrent browser instances gets to use them."""
        assert _resolve_xdist_workers(100, max_workers=16) == 16


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
            "fab_test.scripts.invoke_playwright._stream_subprocess",
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

    def test_explicit_max_workers_is_honored_over_the_default(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.delenv("PLAYWRIGHT_XDIST_WORKERS", raising=False)
        captured = self._fake_pytest_argv_capture(monkeypatch, tmp_path)

        _run_pytest({}, verbosity=0, case_count=100, max_workers=16)

        command = captured[0]
        assert command[command.index("-n") + 1] == "16"

    def test_env_var_is_honored_when_no_explicit_max_workers(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setenv("PLAYWRIGHT_XDIST_WORKERS", "7")
        captured = self._fake_pytest_argv_capture(monkeypatch, tmp_path)

        _run_pytest({}, verbosity=0, case_count=100)

        command = captured[0]
        assert command[command.index("-n") + 1] == "7"


class TestBuildPlaywrightCommandForwardsWorkers:
    """`fab-test playwright --workers N` has to actually reach the
    invoke_playwright.py subprocess as `--workers N`, not just parse on the
    outer CLI and go nowhere."""

    def test_explicit_workers_is_forwarded(self, tmp_path: Path) -> None:
        import argparse

        from fab_test.scripts.fab_test_registry import build_playwright_command

        artifact = tmp_path / "Sales.Report"
        artifact.mkdir()
        args = argparse.Namespace(
            playwright_env_file=None, environment="", workspace_id="", impact_manifest=None,
            dataset_id="", pages="auto", roles="auto", workers=12,
        )

        cmd = build_playwright_command(artifact, args, tmp_path / "results")

        idx = cmd.index("--workers")
        assert cmd[idx + 1] == "12"

    def test_unset_workers_omits_the_flag(self, tmp_path: Path) -> None:
        """No --workers on the outer CLI: the child falls back to
        PLAYWRIGHT_XDIST_WORKERS/the packaged default on its own."""
        import argparse

        from fab_test.scripts.fab_test_registry import build_playwright_command

        artifact = tmp_path / "Sales.Report"
        artifact.mkdir()
        args = argparse.Namespace(
            playwright_env_file=None, environment="", workspace_id="", impact_manifest=None,
            dataset_id="", pages="auto", roles="auto", workers=None,
        )

        cmd = build_playwright_command(artifact, args, tmp_path / "results")

        assert "--workers" not in cmd
