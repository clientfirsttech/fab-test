"""Live progress for a Data Agent run, so a minute of agent calls never looks hung (follow-up 18).

fab-test pipes the wrapper's stdout and stderr and replays them when it exits, so live lines go
straight to the terminal a person is watching (``CONOUT$`` / ``/dev/tty``). There is none in CI,
under ``-q``, or with no console; then nothing is shown, and stdout stays one JSON document under
``--format json`` either way.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Any, TextIO

POLL_SECONDS = 0.25
SECONDS_PER_QUESTION = 20  # observed against agent-sample-model, 2026-11-21: 18-21 s


def terminal() -> TextIO | None:
    """The terminal a person is watching, or None when nobody is."""
    if os.getenv("ANALYZER_VERBOSITY") == "summary" or os.getenv("CI"):
        return None
    try:
        return open("CONOUT$" if os.name == "nt" else "/dev/tty", "w", encoding="utf-8",
                    errors="replace")
    except OSError:
        return None


def _say(out: TextIO, line: str) -> None:
    with contextlib.suppress(OSError, ValueError):  # a closed or vanished terminal never fails the run
        out.write(line + "\n")
        out.flush()


class Progress:
    """Print each answer as the provider reports it, while promptfoo runs."""

    def __init__(self, out: TextIO | None, path: Path, total: int, item: str) -> None:
        self.out, self.path, self.total, self.item = out, path, total, item
        self.shown = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Progress:
        if self.out is not None:
            plural = "question" if self.total == 1 else "questions"
            _say(self.out, f"  asking {self.total} {plural} of {self.item} "
                           f"(live agent calls, about {SECONDS_PER_QUESTION} s each)")
            self._thread = threading.Thread(target=self._watch, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
            self._drain()

    def _watch(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            self._drain()

    def _drain(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for raw in lines[self.shown:]:
            try:
                entry = json.loads(raw)
            except ValueError:
                return  # a line still being written: read it on the next poll
            self.shown += 1
            verb = "failed after" if entry.get("error") else "answered in"
            _say(self.out, f"  … {self.shown}/{self.total} {verb} {entry.get('seconds', '?')} s: "
                           f"{str(entry.get('query', ''))[:80]}")


def show_verdicts(out: TextIO | None, results: list[dict[str, Any]], findings: list[dict[str, Any]]) -> None:
    """One ✓ or ✗ per test once promptfoo has graded the answers, naming why a test failed."""
    if out is None:
        return
    reasons = {finding["object"]: finding["message"] for finding in findings}
    for result in results:
        name = result["test_name"]
        _say(out, f"  ✓ {name}" if result["passed"] else f"  ✗ {name}: {reasons.get(name, 'failed')}")
