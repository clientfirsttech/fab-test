"""Playwright's case-count-scaled outer subprocess timeout.

Split out of `fab_test_execution.py` (Playwright Case Scaling epic) once
this pushed that file over its hard line budget -- a cohesive, playwright-
specific unit of its own, not something every other analyzer's execution
path needs to carry.

The flat outer timeout (``_DEFAULT_SUBPROCESS_TIMEOUT``, in
``_fab_test_context.py``) is sized for roughly one case, but a report's
page/bookmark/role matrix can generate many, run sequentially inside one
pytest invocation. The real case count is only known *inside* that
subprocess, after discovery -- a live Fabric REST call, not something worth
redoing out here just to size a timeout. Rather than double that network
cost with a separate pre-flight run, ``run_playwright_with_scaled_timeout``
polls for the same test-cases file ``invoke_playwright.py`` already writes
mid-run and extends the deadline once, from inside the one subprocess this
analyzer already spawns.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._fab_test_context import _DEFAULT_SUBPROCESS_TIMEOUT

PLAYWRIGHT_FIXED_OVERHEAD_SECONDS = 60
PLAYWRIGHT_POLL_INTERVAL_SECONDS = 0.25


def playwright_per_case_seconds() -> int:
    """Per-case render-wait budget, read at call time (not import time) so
    a test can monkeypatch PLAYWRIGHT_TIMEOUT_SECONDS reliably -- matches
    the same env var invoke_playwright.py's own config loader reads."""
    try:
        return int(os.environ.get("PLAYWRIGHT_TIMEOUT_SECONDS", "180"))
    except ValueError:
        return 180


def scaled_playwright_timeout(case_count: int) -> int:
    """Per-run timeout floor for a playwright run generating ``case_count`` cases.

    Never below ``_DEFAULT_SUBPROCESS_TIMEOUT`` -- a report generating only
    one or two cases must not regress today's behavior.
    """
    scaled = PLAYWRIGHT_FIXED_OVERHEAD_SECONDS + playwright_per_case_seconds() * case_count
    return max(_DEFAULT_SUBPROCESS_TIMEOUT, scaled)


def read_playwright_case_count(test_cases_path: Path) -> int | None:
    """Return the case count once invoke_playwright.py has written its
    test-cases JSON, or None while it doesn't exist yet / is mid-write."""
    try:
        data = json.loads(test_cases_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return len(data) if isinstance(data, list) else None


def _drain_pipe(pipe: Any, chunks: list[str]) -> None:
    """Continuously read lines from ``pipe`` into ``chunks`` until it closes.

    Runs in a background thread for the subprocess's whole lifetime so a
    long, verbose pytest run can never fill the OS pipe buffer and
    deadlock while the main thread is busy polling for the case-count file
    instead of calling ``communicate()`` immediately, the way
    ``subprocess.run`` does internally.
    """
    if pipe is None:
        return
    try:
        chunks.extend(iter(pipe.readline, ""))
    finally:
        pipe.close()


@dataclass(frozen=True)
class Narration:
    """The caller's own narration helpers, bundled into one parameter rather
    than two positional callables -- keeps `run_playwright_with_scaled_timeout`
    under the complexity ratchet's argument-count ceiling."""

    reemit_lines: Callable[[str | None, str], None]
    narrate: Callable[..., None]


def run_playwright_with_scaled_timeout(
    cmd: list[str],
    ctx: Any,
    capture_stdout: bool,
    output_format: str,
    name: str,
    display_name: str,
    test_cases_path: Path,
    narration: Narration,
) -> subprocess.CompletedProcess | tuple[str, int]:
    """Run the playwright subprocess with a timeout that extends once the
    real generated case count is known, instead of one flat number sized
    for a single case.

    ``ctx`` is fab_test_execution.py's ``_RunContext`` (duck-typed here,
    not imported, to avoid a circular import back into the module that
    calls this one); ``narration`` bundles that module's own narration
    helpers, injected rather than duplicated.
    """
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE if capture_stdout else None,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ctx.sub_env,
    )
    stdout_thread = None
    if capture_stdout and proc.stdout is not None:
        stdout_thread = threading.Thread(
            target=_drain_pipe, args=(proc.stdout, stdout_chunks), daemon=True
        )
        stdout_thread.start()
    stderr_thread = threading.Thread(
        target=_drain_pipe, args=(proc.stderr, stderr_chunks), daemon=True
    )
    stderr_thread.start()

    start = time.monotonic()
    # Bounded by the flat default until cases are known -- generous for
    # discovery (a handful of REST calls), never enough for a full run.
    deadline = start + ctx.timeout
    cases_known = False
    while proc.poll() is None:
        if not cases_known:
            count = read_playwright_case_count(test_cases_path)
            if count is not None:
                cases_known = True
                deadline = start + scaled_playwright_timeout(count)
        if time.monotonic() >= deadline:
            break
        time.sleep(PLAYWRIGHT_POLL_INTERVAL_SECONDS)

    timed_out = proc.poll() is None
    if timed_out:
        proc.kill()
    proc.wait()
    if stdout_thread is not None:
        stdout_thread.join()
    stderr_thread.join()
    stdout_text = "".join(stdout_chunks) if capture_stdout else None
    stderr_text = "".join(stderr_chunks)

    if timed_out:
        effective_timeout = round(deadline - start)
        narration.narrate(
            f"  ⏰ fab-test {name}: timed out after {effective_timeout}s for {display_name}",
            output_format=output_format,
        )
        if capture_stdout:
            narration.reemit_lines(stdout_text, output_format)
        if ctx.manifest is not None:
            ctx.manifest.record_artifact(
                name, display_name, "timeout", None, 0, 0,
                detail=f"exceeded {effective_timeout}s timeout",
                duration_ms=effective_timeout * 1000,
            )
        return (display_name, 1)

    return subprocess.CompletedProcess(cmd, proc.returncode, stdout_text, stderr_text)
