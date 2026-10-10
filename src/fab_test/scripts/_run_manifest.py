"""Run manifest: one file per fab-test invocation (CLI Agent Ergonomics §11-12).

Callers (humans, pipelines, and agents alike) read ``fab-test-results/run.json``
instead of globbing result directories to learn what happened in the most
recent invocation: the command that ran, every artifact's status and envelope
path, totals, and the final exit code.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_MANIFEST_SCHEMA_VERSION = 1

# Flags whose value is a credential and must never be written verbatim.
_SENSITIVE_FLAG_NAMES = {
    "--client-secret",
    "--password",
    "--token",
    "--secret",
    "--api-key",
}

# Catches an embedded credential in a single "key=value"-shaped token, in
# case one is ever passed that way instead of as two separate argv tokens.
_SENSITIVE_KV_PATTERN = re.compile(r"(?i)^(.*?\b(?:token|secret|password|key)\s*=\s*).+$")


def _sanitize_command(command: list[str]) -> list[str]:
    """Return ``command`` with any credential-shaped value redacted."""
    sanitized = list(command)
    for i, part in enumerate(sanitized):
        if part.lower() in _SENSITIVE_FLAG_NAMES and i + 1 < len(sanitized):
            sanitized[i + 1] = "<redacted>"
    for i, part in enumerate(sanitized):
        match = _SENSITIVE_KV_PATTERN.match(part)
        if match:
            sanitized[i] = f"{match.group(1)}<redacted>"
    return sanitized


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RunManifest:
    """Accumulates per-artifact results across one fab-test invocation."""

    def __init__(
        self,
        fab_test_version: str,
        invoked_command: list[str],
        origin: str = "unknown",
        target: dict[str, Any] | None = None,
    ):
        self.fab_test_version = fab_test_version
        self.invoked_command = _sanitize_command(invoked_command)
        self.origin = origin
        # The resolved target, or None when the run discovered artifacts
        # rather than being pointed at one. Recorded so a finished run says
        # whether it read files, a Desktop instance, or a workspace --
        # which `origin` alone (local vs CI) does not answer.
        self.target = target
        # Why this run's telemetry was not delivered, or None when it was
        # (or when none was asked for). A pipeline reading only the manifest
        # can otherwise not tell a run whose telemetry landed from one whose
        # records were dropped.
        self.telemetry_error: str | None = None
        self.artifacts: list[dict[str, Any]] = []
        # Wall clock for the whole invocation: the sum of artifact durations
        # against it is what shows how much --jobs / Azure-hosted browsers saved.
        self.started_at = _utc_now()
        self._started = time.monotonic()
        # Playwright's resolved backend/workers/jobs and where each came from,
        # or None when the run did not include playwright. Never credentials.
        self.execution: dict[str, Any] | None = None

    def record_artifact(
        self,
        analyzer: str,
        artifact: str,
        status: str,
        envelope_path: str | None,
        errors: int,
        warnings: int,
        detail: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Record one artifact's outcome for the manifest.

        ``detail`` carries the human-readable failure reason for abort
        statuses (``preflight_failed``, ``timeout``); it is ``None`` when
        the artifact completed normally. ``duration_ms`` is the parent's
        wall time for the analyzer subprocess; ``None`` when it never ran.
        """
        self.artifacts.append(
            {
                "analyzer": analyzer,
                "artifact": artifact,
                "status": status,
                "envelope_path": envelope_path,
                "errors": errors,
                "warnings": warnings,
                "detail": detail,
                "duration_ms": duration_ms,
            }
        )

    def to_dict(self, exit_code: int) -> dict[str, Any]:
        """Return the manifest as a plain dict, without writing it."""
        total_errors = sum(a["errors"] for a in self.artifacts)
        total_warnings = sum(a["warnings"] for a in self.artifacts)
        return {
            "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
            "fab_test_version": self.fab_test_version,
            "origin": self.origin,
            "target": self.target,
            "command": self.invoked_command,
            "artifacts": self.artifacts,
            "totals": {"errors": total_errors, "warnings": total_warnings},
            # Null when telemetry landed or none was requested. Additive and
            # optional: a reader that does not know the key is unaffected.
            "telemetry_error": self.telemetry_error,
            "exit_code": exit_code,
            # Additive timing (Run Timing epic, task 1).
            "started_at": self.started_at,
            "finished_at": _utc_now(),
            "wall_ms": int((time.monotonic() - self._started) * 1000),
            "execution": self.execution,
        }

    def write(self, output_dir: Path, exit_code: int) -> Path:
        """Write run.json under ``output_dir`` and return its path."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "run.json"
        path.write_text(
            json.dumps(self.to_dict(exit_code), indent=2), encoding="utf-8"
        )
        return path
