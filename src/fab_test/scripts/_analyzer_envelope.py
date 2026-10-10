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
from dataclasses import dataclass
from datetime import UTC, datetime
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
        # UTC ISO-8601 wall-clock time the analyzer run started, from
        # Timer. duration_ms says how long; this says when.
        "started_at",
        # Service Targeting: which mode the run tested (local|service)
        # and which input decided it. Stamped by fab-test, not the wrapper.
        "mode",
        "source",
    }
)

# Output layout: fab-test-results/<analyzer>/<artifact-stem>/
_RESULTS_ROOT = "fab-test-results"


def is_test_finding(finding: dict) -> bool:
    """Return True when a finding uses the pql-test suite/test/expected shape."""
    return (
        "test_name" in finding
        or "suite_name" in finding
        or ("passed" in finding and ("expected" in finding or "actual" in finding))
    )


def finding_status(finding: dict) -> str:
    """Map a pql-test result dict to a status label."""
    if finding.get("error"):
        return "ERROR"
    if finding.get("skipped"):
        return "SKIPPED"
    if finding.get("passed"):
        return "PASS"
    return "FAIL"


def normalize_findings(findings: list[dict]) -> tuple[str, list[tuple]]:
    """Return ``(kind, sorted rows)`` for a list of findings.

    ``kind`` is ``"rules"`` — (rule, severity, object, message) — or
    ``"tests"`` — (suite, test, expected, actual, status). Collapsing
    BPA's PascalCase keys and PBIR's lowercase keys here is what stops one
    analyzer's findings rendering differently from another's.

    Shared by the terminal summary and the HTML report so the two can
    never disagree about what a finding says or which order findings come
    in. Rendering-free by design: no widths, no escaping, no markup.
    """
    if findings and is_test_finding(findings[0]):
        rows = [
            (
                f.get("suite_name") or "?",
                f.get("test_name") or "?",
                f.get("expected") or "",
                f.get("actual") or "",
                finding_status(f),
            )
            for f in findings
        ]
        status_rank = {"ERROR": 0, "FAIL": 1, "SKIPPED": 2, "PASS": 3}
        rows.sort(key=lambda r: (status_rank.get(r[4], 1), str(r[0]).lower(), str(r[1]).lower()))
        return "tests", rows

    rows = [
        (
            f.get("rule") or f.get("RuleName") or "?",
            f.get("severity") or f.get("Severity") or "",
            f.get("object") or f.get("ObjectName") or "",
            f.get("message") or f.get("Message") or f.get("description") or "",
        )
        for f in findings
    ]
    # Most severe first, then stable by rule and object.
    rows.sort(key=lambda r: (-severity_rank(r[1]), str(r[0]).lower(), str(r[2]).lower()))
    return "rules", rows


def _test_result_status(entry: dict) -> str:
    """Return a canonical PASS/FAIL/WARNING/ERROR/SKIPPED label for one full-list row.

    A BPA-shaped row already carries a computed ``status`` (pass/error/
    warning/skip -- see ``invoke_tabular_editor_bpa._bpa_result_status``);
    this just upper-cases it into the same vocabulary ``finding_status``
    already uses for pql-test-shaped rows, so the renderer needs one
    filter mapping for either shape.
    """
    if "status" in entry:
        return str(entry["status"]).upper()
    return finding_status(entry)


def normalize_test_results(test_results: list[dict]) -> tuple[str, list[tuple]]:
    """Return ``(kind, sorted rows)`` for the FULL result list -- passes included.

    Mirrors ``normalize_findings``'s two shapes (rules vs. tests), but
    keeps every row rather than only violations, and every row ends with
    a status column so the report can filter by it. Shares the same shape
    detection (``is_test_finding``) so a row is never classified
    differently here than it would be as a finding.
    """
    if not test_results:
        return "rules", []

    status_rank = {
        "ERROR": 0, "FAIL": 0, "WARNING": 1, "SKIPPED": 2, "SKIP": 2, "PASS": 3,
    }

    if is_test_finding(test_results[0]):
        # `evidence` and `report_link` are both additive: only Playwright's
        # rows carry them (screenshot/console/network paths, and a deep
        # link to the report page/bookmark that case validated), so every
        # other analyzer's rows just end up with `{}` here -- falsy, so
        # `_report_html` renders them exactly as it did before either
        # column existed.
        rows = [
            (
                f.get("suite_name") or "?",
                f.get("test_name") or "?",
                f.get("expected") or "",
                f.get("actual") or "",
                _test_result_status(f),
                f.get("evidence") or {},
                f.get("report_link") or {},
                f.get("duration_ms"),  # Playwright's per-case render time; None elsewhere
            )
            for f in test_results
        ]
        rows.sort(key=lambda r: (status_rank.get(r[4], 1), str(r[0]).lower(), str(r[1]).lower()))
        return "tests", rows

    rows = [
        (
            f.get("rule") or f.get("RuleName") or "?",
            f.get("severity") or f.get("Severity") or "",
            f.get("object") or f.get("ObjectName") or "",
            f.get("message") or f.get("Message") or f.get("description") or "",
            _test_result_status(f),
        )
        for f in test_results
    ]
    rows.sort(key=lambda r: (status_rank.get(r[4], 1), str(r[0]).lower(), str(r[2]).lower()))
    return "rules", rows


_SEVERITY_TEXT_RANK: dict[str, int] = {
    **dict.fromkeys(("error", "errors", "critical", "fatal", "failure", "failed"), 3),
    **dict.fromkeys(("warning", "warnings", "warn"), 2),
    **dict.fromkeys(("information", "info", "notice", "note"), 1),
}


def severity_rank(severity: Any) -> int:
    """Return a numeric severity rank for sorting (higher = more severe).

    Supports numeric values (int/float/strings like "3") and common text
    labels such as Error, Warning, and Information.
    """
    if severity is None or isinstance(severity, bool):
        return 0
    if isinstance(severity, (int, float)):
        return int(severity)
    text = str(severity).strip().lower()
    if text.lstrip("-").isdigit():
        return int(text)
    return _SEVERITY_TEXT_RANK.get(text, 0)


def _is_error_severity(severity: Any) -> bool:
    """Return True if the severity should be treated as an error.

    Severity >= 3 and unknown/missing values are treated as errors so the
    build gate remains conservative.
    """
    rank = severity_rank(severity)
    if rank == 0 and severity is not None:
        # Non-empty but unrankable severity still treated as error.
        raw = str(severity).strip()
        if raw:
            return True
    return rank >= 3


def _is_warning_severity(severity: Any) -> bool:
    """Return True if the severity is a known warning (rank 1 or 2)."""
    rank = severity_rank(severity)
    return 0 < rank < 3


def severity_counts(findings: list[dict[str, Any]]) -> tuple[int, int]:
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


def native_output_path(analyzer: str, artifact_stem: str, extension: str, *, beside: Path | None = None) -> Path:
    """Return the path for the native output file: beside the envelope, else the default root.

    The parent passes the envelope's path (``--output-path``), already under
    ``--output-dir``; building native output from the default root instead
    split one artifact's results across two directories.
    """
    folder = beside.parent if beside is not None else results_dir(analyzer, artifact_stem)
    return folder / f"native.{extension.lstrip('.')}"


def envelope_path(analyzer: str, artifact_stem: str) -> Path:
    """Return the canonical path for the envelope JSON file."""
    return results_dir(analyzer, artifact_stem) / "envelope.json"


@dataclass(frozen=True)
class EnvelopeIdentity:
    """Which analyzer produced an envelope, and for which artifact.

    Every ``build_envelope`` call passes these two together; grouping them
    is what kept the function under the argument budget.
    """

    analyzer: str
    artifact_path: str


def build_envelope(
    identity: EnvelopeIdentity,
    *,
    status: str,
    message: str = "",
    findings: list[dict[str, Any]] | None = None,
    native_output_path_str: str = "",
    native_html_output_path_str: str = "",
    started_at: str = "",
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
        "analyzer": identity.analyzer,
        "artifact_path": identity.artifact_path,
        "findings": findings if findings is not None else [],
        "native_output_path": native_output_path_str,
        "duration_ms": duration_ms,
    }
    if native_html_output_path_str:
        envelope["native_html_output_path"] = native_html_output_path_str
    if started_at:
        envelope["started_at"] = started_at
    return envelope


@dataclass(frozen=True)
class WrapperResult:
    """Fields ``write_results`` needs from every analyzer wrapper.

    Each of the three wrappers grew its own ``write_results`` past the
    argument budget one flag at a time; this is the part they shared.
    An analyzer-specific extra (``rules_path``, desktop identity) stays a
    parameter of that wrapper's own ``write_results`` rather than living
    here.
    """

    output_path: Path
    status: str
    findings: list[dict[str, Any]]
    artifact_path: Path
    message: str = ""
    native_out: "Path | None" = None
    duration_ms: int = 0
    started_at: str = ""
    test_summary: "dict[str, int] | None" = None
    test_results: "list[dict[str, Any]] | None" = None


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
        # Wall-clock UTC, recorded alongside the monotonic clock: elapsed_ms
        # answers "how long" but has no epoch, so it cannot answer "when".
        # Reports need the latter, and it belongs in the envelope so the
        # renderer displays a recorded fact rather than the time it happened
        # to run.
        self.started_at: str = ""

    def __enter__(self) -> "Timer":
        self._start = time.monotonic()
        self.started_at = datetime.now(UTC).isoformat(timespec="seconds")
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = int((time.monotonic() - self._start) * 1000)
