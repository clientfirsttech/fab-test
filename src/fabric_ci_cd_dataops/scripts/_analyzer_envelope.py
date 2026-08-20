"""Shared analyzer result envelope schema (vision §2.8 R2).

Every wrapper writes two output files per artifact:
  - ``native.<ext>``  — the analyzer tool's own raw output, preserved as-is.
  - ``envelope.json`` — the standardized envelope consumed by reporters and gates.

Import helpers::

    from _analyzer_envelope import (
        build_envelope,
        write_envelope,
        ENVELOPE_SCHEMA_VERSION,
    )

The envelope shape is versioned so downstream tooling (Eventhouse, dashboards,
promotion gates) can assert the schema they expect via ``ENVELOPE_SCHEMA_VERSION``.
"""

import json
import time
from pathlib import Path
from typing import Any

ENVELOPE_SCHEMA_VERSION = "1.0"

ENVELOPE_REQUIRED_KEYS: frozenset = frozenset(
    {
        "schema_version",
        "status",
        "message",
        "analyzer",
        "artifact_path",
        "findings",
        "native_output_path",
        "duration_ms",
    }
)

# Keys an analyzer may add but none is obliged to. Optional means *absent*
# rather than null: a consumer tests presence, so a key is never a promise
# pointing nowhere.
#
# native_html_output_path is a human-readable report for this artifact --
# an upstream one where the tool produces it (PBIR Inspector's TestRun.html)
# or a generated one otherwise. `fab-test all` surfaces it in the Report
# column, which is why it needs to be part of the contract rather than a
# field one wrapper happened to set.
ENVELOPE_OPTIONAL_KEYS: frozenset = frozenset(
    {
        "native_html_output_path",
    }
)

# Output layout: analyzer-results/<analyzer>/<artifact-stem>/
_RESULTS_ROOT = "analyzer-results"


def _severity_rank(severity: Any) -> int:
    """Return a numeric severity rank for sorting (higher = more severe).

    Supports numeric values (int/float/strings like "3") and common text
    labels such as Error, Warning, and Information.
    """
    if severity is None:
        return 0
    if isinstance(severity, bool):
        return 0
    if isinstance(severity, (int, float)):
        return int(severity)
    text = str(severity).strip().lower()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        pass
    if text in {"error", "errors", "critical", "fatal", "failure", "failed"}:
        return 3
    if text in {"warning", "warnings", "warn"}:
        return 2
    if text in {"information", "info", "notice", "note"}:
        return 1
    return 0


def _is_error_severity(severity: Any) -> bool:
    """Return True if the severity should be treated as an error.

    Severity >= 3 and unknown/missing values are treated as errors so the
    build gate remains conservative.
    """
    rank = _severity_rank(severity)
    if rank == 0 and severity is not None:
        # Non-empty but unrankable severity still treated as error.
        raw = str(severity).strip()
        if raw:
            return True
    return rank >= 3


def _is_warning_severity(severity: Any) -> bool:
    """Return True if the severity is a known warning (rank 1 or 2)."""
    rank = _severity_rank(severity)
    return 0 < rank < 3


def _severity_counts(findings: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (error_count, warning_count) for a list of findings.

    Unknown severities count as errors.
    """
    errors = 0
    warnings = 0
    for f in findings:
        sev = f.get("severity") or f.get("Severity")
        if _is_error_severity(sev):
            errors += 1
        elif _is_warning_severity(sev):
            warnings += 1
        else:
            # Treat missing/empty severity as error to stay conservative.
            errors += 1
    return errors, warnings


def results_dir(analyzer: str, artifact_stem: str) -> Path:
    """Return the standard output directory for an analyzer run."""
    return Path(_RESULTS_ROOT) / analyzer / artifact_stem


def native_output_path(analyzer: str, artifact_stem: str, extension: str) -> Path:
    """Return the canonical path for the native output file."""
    return results_dir(analyzer, artifact_stem) / f"native.{extension.lstrip('.')}"


def envelope_path(analyzer: str, artifact_stem: str) -> Path:
    """Return the canonical path for the envelope JSON file."""
    return results_dir(analyzer, artifact_stem) / "envelope.json"


def build_envelope(
    *,
    analyzer: str,
    artifact_path: str,
    status: str,
    message: str = "",
    findings: list[dict[str, Any]] | None = None,
    native_output_path_str: str = "",
    native_html_output_path_str: str = "",
    duration_ms: int = 0,
) -> dict[str, Any]:
    """Build a standards-compliant result envelope dictionary.

    ``native_html_output_path_str`` is optional and omitted entirely when
    empty, rather than written as an empty string -- see
    ``ENVELOPE_OPTIONAL_KEYS`` for why absence is the signal.
    """
    envelope = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "status": status,
        "message": message,
        "analyzer": analyzer,
        "artifact_path": artifact_path,
        "findings": findings if findings is not None else [],
        "native_output_path": native_output_path_str,
        "duration_ms": duration_ms,
    }
    if native_html_output_path_str:
        envelope["native_html_output_path"] = native_html_output_path_str
    return envelope


def write_envelope(path: Path, envelope: dict[str, Any]) -> None:
    """Write an envelope dict to disk, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, indent=2)


class Timer:
    """Simple context-manager timer that records elapsed milliseconds."""

    def __init__(self) -> None:
        self._start: float = 0.0
        self.elapsed_ms: int = 0

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = int((time.monotonic() - self._start) * 1000)
