"""Run manifest: one file per fab-test invocation (CLI Agent Ergonomics §11-12).

Callers (humans, pipelines, and agents alike) read ``analyzer-results/run.json``
instead of globbing result directories to learn what happened in the most
recent invocation: the command that ran, every artifact's status and envelope
path, totals, and the final exit code.
"""

from __future__ import annotations

import json
import re
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


class RunManifest:
    """Accumulates per-artifact results across one fab-test invocation."""

    def __init__(self, fab_test_version: str, invoked_command: list[str]):
        self.fab_test_version = fab_test_version
        self.invoked_command = _sanitize_command(invoked_command)
        self.artifacts: list[dict[str, Any]] = []

    def record_artifact(
        self,
        analyzer: str,
        artifact: str,
        status: str,
        envelope_path: str | None,
        errors: int,
        warnings: int,
        detail: str | None = None,
    ) -> None:
        """Record one artifact's outcome for the manifest.

        ``detail`` carries the human-readable failure reason for abort
        statuses (``preflight_failed``, ``timeout``); it is ``None`` when
        the artifact completed normally.
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
            }
        )

    def to_dict(self, exit_code: int) -> dict[str, Any]:
        """Return the manifest as a plain dict, without writing it."""
        total_errors = sum(a["errors"] for a in self.artifacts)
        total_warnings = sum(a["warnings"] for a in self.artifacts)
        return {
            "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
            "fab_test_version": self.fab_test_version,
            "command": self.invoked_command,
            "artifacts": self.artifacts,
            "totals": {"errors": total_errors, "warnings": total_warnings},
            "exit_code": exit_code,
        }

    def write(self, output_dir: Path, exit_code: int) -> Path:
        """Write run.json under ``output_dir`` and return its path."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "run.json"
        path.write_text(
            json.dumps(self.to_dict(exit_code), indent=2), encoding="utf-8"
        )
        return path
