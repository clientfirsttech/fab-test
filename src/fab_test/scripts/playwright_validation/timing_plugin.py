"""Per-case timing for the packaged render spec (Run Timing epic, task 2).

Loaded on every render run, unlike ``execution_plugin``, which loads only for
an execution YAML or ``--headed``/``--slow-mo``. Writes ``timing.json`` beside
each case's ``result.json``:

- ``setup_ms`` -- fixture setup before the case: the browser launch or Azure
  connection (once per worker, so on that worker's first case), the context,
  and the page. Kept apart so a slow service connection is never read as
  slow Power BI rendering.
- ``duration_ms`` -- the case itself: embedding the report and waiting for
  ``rendered`` or an error.

Each case runs on exactly one xdist worker, so nothing else writes its file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .render_helpers import _case_result_dir

TIMING_FILENAME = "timing.json"  # keep in step with phase_timing.TIMING_FILENAME
_PHASE_KEYS = {"setup": "setup_ms", "call": "duration_ms"}


def _record(result_dir: Path, key: str, milliseconds: int) -> None:
    path = result_dir / TIMING_FILENAME
    try:
        timing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        timing = {}
    timing[key] = milliseconds
    try:
        result_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(timing), encoding="utf-8")
    except OSError:
        pass  # timing is diagnostic; it must never fail a render case


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Any, call: Any):
    yield
    key = _PHASE_KEYS.get(call.when)
    case = getattr(getattr(item, "callspec", None), "params", {}).get("case")
    if key and case:
        _record(_case_result_dir(case), key, int(call.duration * 1000))
