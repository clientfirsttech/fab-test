"""Where one report's playwright run spent its time (Run Timing epic, task 2).

The wrapper side of per-case timing: ``timing_plugin`` writes each case's
``timing.json`` inside the pytest session; this module reads it back and
times the wrapper's own phases (discovery, embed tokens, render) for the
envelope's ``timings``. Kept apart from ``invoke_playwright`` so the
wrapper's module budget pays one import, not the helpers.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .execution_config import ExecutionConfig
from .execution_runtime import _resolve_max_workers, _resolve_xdist_workers

# Loaded with `-p` by module path rather than imported, so the wrapper never
# imports pytest or the render helpers the plugin depends on.
TIMING_PLUGIN = "fab_test.scripts.playwright_validation.timing_plugin"
TIMING_FILENAME = "timing.json"


class PhaseClock:
    """Wall-clock phases of one report's run, for its envelope's ``timings``.

    ``duration_ms`` keeps meaning the render phase alone, so readers of it are
    unaffected; ``timings`` says where the rest of the report's time went.
    """

    def __init__(self) -> None:
        self.started_at = datetime.now(UTC).isoformat(timespec="seconds")
        self._start = self._mark = time.monotonic()
        self.phases: dict[str, int] = {}
        self.render_duration_ms = 0  # pytest alone: the envelope's `duration_ms`

    def lap(self, phase: str) -> None:
        now = time.monotonic()
        self.phases[phase] = int((now - self._mark) * 1000)
        self._mark = now

    def timings(self, test_results: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
        setups = [row["setup_ms"] for row in test_results if "setup_ms" in row]
        # The xdist workers this report actually used: capped by its case count, 1 when serial.
        workers = _resolve_xdist_workers(len(test_results), _resolve_max_workers(getattr(args, "workers", None)))
        return {
            **self.phases,
            # Summed across cases: browser launch or Azure connection lands on
            # each worker's first case, context and page creation on every case.
            **({"browser_setup_ms": sum(setups)} if setups else {}),
            "total_ms": int((time.monotonic() - self._start) * 1000),
            "backend": (getattr(args, "execution_config", None) or ExecutionConfig()).backend,
            "workers": workers or 1,
        }


def case_timing(result_dir: Path) -> dict[str, int]:
    """Return the case's ``duration_ms``/``setup_ms`` the timing plugin recorded; empty when it never ran."""
    try:
        timing = json.loads((result_dir / TIMING_FILENAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {key: timing[key] for key in ("duration_ms", "setup_ms") if isinstance(timing.get(key), int)}


def clear_case_timing(result_dirs: Iterable[Path]) -> None:
    """Drop an earlier run's timing.json, so a case that never runs this time reports no duration."""
    for result_dir in result_dirs:
        (result_dir / TIMING_FILENAME).unlink(missing_ok=True)
