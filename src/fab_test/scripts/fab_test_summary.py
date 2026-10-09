"""Summary formatting and table rendering for ``fab-test``.

This module keeps ``fab_test.py`` focused on orchestration. It reads analyzer
envelopes, renders findings tables, and prints per-analyzer and aggregate
summaries for both text and JSON output formats.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tabulate import tabulate

from ._analyzer_envelope import finding_status, normalize_findings, severity_counts
from ._cli_utils import CHECKOUT_REMEDIATION, skipped_checkout_lines
from ._report_html import (
    open_report_in_browser,
    resolve_open_report,
    resolve_report,
    write_index,
)
from ._service_export import service_row_stems
from ._table_style import TABLE_FORMAT, table_padding
from ._target import target_from_args
from .fab_test_registry import ANALYZER_REGISTRY, discover_artifacts

# Plain ANSI rather than a library: colour here marks three states, which
# is not worth a runtime dependency for presentation alone.
_ANSI = {
    "red": "\033[31m",
    "yellow": "\033[33m",
    "green": "\033[32m",
    "dim": "\033[2m",
}
_RESET = "\033[0m"

_STATUS_COLORS = {
    "FAILED": "red",
    "failed": "red",
    "warning": "yellow",
    "passed": "green",
    "skipped": "dim",
}


def color_enabled(stream: Any = None) -> bool:
    """Whether ANSI colour should be written to ``stream``.

    Off unless the stream is a terminal, so redirected output, piped
    output, and captured CI logs stay plain. ``NO_COLOR`` (any value, per
    no-color.org) always wins; ``FORCE_COLOR`` opts back in for a CI job
    that does render ANSI.

    Callers must still keep colour away from ``--format json``, whose
    stdout is contractually a single JSON document -- this function
    answers "can the terminal show it", not "is it allowed here".
    """
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream if stream is not None else sys.stdout
    return bool(getattr(stream, "isatty", None)) and stream.isatty()


def _paint(text: str, color: str | None, *, enabled: bool) -> str:
    """Wrap ``text`` in an ANSI colour, always resetting afterwards.

    An unreset colour bleeds into everything printed after it, including
    another program's output, so the reset is unconditional.
    """
    if not enabled or not color or color not in _ANSI:
        return text
    return f"{_ANSI[color]}{text}{_RESET}"


def _status_label(status: str) -> str:
    """Return the status text for a summary table cell.

    Plain text, deliberately. The emoji these replaced carry a variation
    selector: `tabulate` measures them as one column while most terminals
    draw them as two, so every row with a status pushed the columns after
    it out of alignment by a character.
    """
    return {
        "passed": "passed",
        "warning": "warning",
        "failed": "FAILED",
        "dry-run": "dry-run",
        "skipped": "skipped",
    }.get(status, status)


def _print_list(
    rows: list[dict[str, Any]],
    output_format: str = "text",
    *,
    skipped_checkouts: Sequence[Path] = (),
) -> int:
    """Print the `fab-test list` capability report. Always exits 0.

    ``skipped_checkouts`` is populated only when every discovering
    analyzer matched nothing *and* the scan pruned repositories. A column
    of zeroes otherwise reads as "there is nothing here", which is the
    one thing it does not mean.
    """
    if output_format == "json":
        payload: dict[str, Any] = {
            "analyzers": rows,
            "skipped_checkouts": [str(path) for path in skipped_checkouts],
        }
        if skipped_checkouts:
            payload["remediation"] = CHECKOUT_REMEDIATION
        print(json.dumps(payload, indent=2))
        return 0

    display_rows = [
        (
            r["analyzer"],
            ", ".join(r.get("aliases", ())) or "-",
            r["glob"] or "(repository)",
            str(r["matched_artifacts"]),
            r["required_tool"] or "(none)",
            ", ".join(r.get("scopes", ())) or "-",
        )
        for r in rows
    ]
    table = tabulate(
        display_rows,
        headers=("Analyzer", "Aliases", "Glob", "Matched", "Required Tool", "Scopes"),
        tablefmt=TABLE_FORMAT,
        stralign="left",
    )
    print(table)
    for line in skipped_checkout_lines(skipped_checkouts):
        print(line)
    return 0


def _print_auth_status(
    payload: dict[str, Any], output_format: str = "text", *, exit_code: int = 0
) -> int:
    """Print the `fab-test auth status` report and return ``exit_code``.

    Never prints a secret: the payload carries a source name, a tenant,
    and a workspace ID, none of which grant access to anything.
    """
    from ._credentials import redact_secrets

    # Defense in depth: the probe is tested never to put a secret in these
    # fields, but this output is the one place a live credential value
    # could reach a terminal or a CI log, so scrub it on the way out.
    for key in ("detail", "remediation"):
        if payload.get(key):
            payload[key] = redact_secrets(payload[key])

    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return exit_code

    identity = payload["identity"]
    rows = [
        ("identity", identity["source"] or "(none resolved)"),
        ("tenant", identity["tenant_id"] or "-"),
        ("verified", "yes" if identity["verified"] else "no"),
    ]
    workspace = payload.get("workspace")
    if workspace:
        rows.append(("workspace", workspace["id"]))
        rows.append(("reachable", "yes" if workspace["reachable"] else "no"))
    print(tabulate(rows, headers=("Check", "Value"), tablefmt=TABLE_FORMAT, stralign="left"))
    if payload.get("detail"):
        print(f"\n  {payload['detail']}")
    if payload.get("remediation"):
        print(f"  → {payload['remediation']}")
    return exit_code


def _print_doctor(rows: list[dict[str, Any]], output_format: str = "text") -> int:
    """Print the `fab-test doctor` readiness report.

    Returns 0 if at least one analyzer is ready, else 1.

    ``ready`` is tri-state. None means "not applicable, or not verifiable
    from here" and is neither a pass nor a failure: it neither satisfies the
    at-least-one-ready condition nor prevents it. Telemetry uses it, because
    an optional feature nobody configured must not report a broken install,
    and a credential that resolves is not proof it may ingest.
    """
    any_ready = any(r["ready"] is True for r in rows)
    blocking = [r for r in rows if r["ready"] is False]

    if output_format == "json":
        print(json.dumps({"analyzers": rows}, indent=2))
        return 0 if any_ready or not blocking else 1

    paint = color_enabled()
    for r in rows:
        icon = {True: "✅", False: "❌", None: "ℹ"}[r["ready"]]
        location = f" — {r['resolved_path']}" if r["resolved_path"] else ""
        colour = {True: "green", False: "red", None: "yellow"}[r["ready"]]
        reason = _paint(r["reason"], colour, enabled=paint)
        print(f"{icon} {r['analyzer']}: {reason}{location}")
        if r.get("service"):
            print(f"   {r['service']}")
        if r["ready"] is not True and r["remediation"]:
            # Yellow, not red: this is the actionable half, and colouring it
            # the same as the failure would flatten the distinction.
            print(_paint(f"   → {r['remediation']}", "yellow", enabled=paint))
    return 0 if any_ready or not blocking else 1


def _print_config_show(rows: list[dict[str, Any]], output_format: str = "text") -> int:
    """Print `fab-test config --show`'s effective settings and their origin.

    Always returns 0 -- this is a reporting command, never a failure.
    """
    if output_format == "json":
        print(json.dumps({"settings": rows}, indent=2))
        return 0

    width = max((len(r["key"]) for r in rows), default=0)
    for r in rows:
        print(f"{r['key']:<{width}} = {r['value']!r}  ({r['origin']})")
    return 0


def _print_local_doctor(
    rows: list[dict[str, Any]], would_run: list[str], output_format: str = "text"
) -> int:
    """Print the `fab-test doctor --local` readiness report.

    Returns 0 if at least one local analyzer would run, else 1.
    """
    if output_format == "json":
        print(json.dumps({"checks": rows, "would_run": would_run}, indent=2))
        return 0 if would_run else 1

    for r in rows:
        icon = "✅" if r["ready"] else "❌"
        location = f" — {r['resolved_path']}" if r.get("resolved_path") else ""
        print(f"{icon} {r['check']}: {r['reason']}{location}")
        if not r["ready"] and r.get("remediation"):
            print(f"   → {r['remediation']}")
    if would_run:
        print(f"\nfab-test local would run: {', '.join(would_run)}")
    else:
        print("\nfab-test local: nothing would run -- resolve at least one prerequisite above")
    return 0 if would_run else 1


def _terminal_width() -> int:
    try:
        return max(shutil.get_terminal_size().columns, 80)
    except OSError:
        return 120


def _truncate(text: str, width: int, placeholder: str = "...") -> str:
    """Return ``text`` truncated to ``width`` characters with an ellipsis."""
    text = str(text).replace("\n", " ").replace("\r", "")
    if len(text) <= width:
        return text
    if width <= len(placeholder):
        return placeholder[:width]
    return text[: width - len(placeholder)] + placeholder


def _format_findings(findings: list[dict], max_width: int | None = None) -> str:
    """Render findings as a width-bounded text table (tabulate).

    Long cells are truncated with an ellipsis so verbose output stays scannable.
    Full details remain in the envelope/native files on disk.
    """
    if not findings:
        return ""
    if max_width is None:
        max_width = _terminal_width()

    _rows, table = _build_findings_table(findings, max_width)
    return table


def _is_pql_test_finding(finding: dict) -> bool:
    """Return True if the finding shape matches pql-test results."""
    return (
        "test_name" in finding
        or "suite_name" in finding
        or ("passed" in finding and ("expected" in finding or "actual" in finding))
    )


def _build_findings_table(
    findings: list[dict],
    max_width: int,
) -> tuple[list[tuple], str]:
    """Build sorted findings rows and a tabulate-rendered table."""
    if findings and _is_pql_test_finding(findings[0]):
        return _build_pql_test_table(findings, max_width)

    # Shared with the HTML report so a finding never reads differently, or
    # sorts differently, between the terminal and the report.
    _kind, rows = normalize_findings(findings)

    # Allocate column widths: keep severity compact, cap rule/object widths,
    # and guarantee the message column at least 20 characters.
    padding = table_padding(4)
    sev_w = min(max((len("Severity"), *(len(r[1]) for r in rows))), 10)
    rule_w = min(max((len("Rule"), *(len(r[0]) for r in rows))), 25)
    obj_w = min(max((len("Object"), *(len(r[2]) for r in rows))), 20)

    # Shrink rule/object columns on narrow terminals until the message fits.
    while rule_w > 8 and (rule_w + sev_w + obj_w + padding + 20) > max_width:
        rule_w -= 1
    while obj_w > 6 and (rule_w + sev_w + obj_w + padding + 20) > max_width:
        obj_w -= 1

    msg_w = max(20, max_width - rule_w - sev_w - obj_w - padding)

    truncated = [
        (
            _truncate(rule, rule_w),
            _truncate(sev, sev_w),
            _truncate(obj, obj_w),
            _truncate(msg, msg_w),
        )
        for rule, sev, obj, msg in rows
    ]

    return rows, tabulate(
        truncated,
        headers=("Rule", "Severity", "Object", "Message"),
        tablefmt=TABLE_FORMAT,
        stralign="left",
    )


def _build_pql_test_table(
    findings: list[dict],
    max_width: int,
) -> tuple[list[tuple], str]:
    """Build a tabulate-rendered table for pql-test results.

    Columns: Test Suite, Test, Expected, Actual, Passed.
    """
    rows = []
    for f in findings:
        suite = f.get("suite_name") or "?"
        test = f.get("test_name") or "?"
        expected = f.get("expected") or ""
        actual = f.get("actual") or ""
        status = finding_status(f)
        rows.append((suite, test, expected, actual, status))

    # Sort by status severity (ERROR > FAIL > SKIPPED > PASS), then suite/test.
    def _status_rank(status: str) -> int:
        return {"ERROR": 0, "FAIL": 1, "SKIPPED": 2, "PASS": 3}.get(status, 1)

    rows.sort(
        key=lambda r: (
            _status_rank(r[4]),
            str(r[0]).lower(),
            str(r[1]).lower(),
        )
    )

    # Allocate column widths: cap suite/test, keep status compact,
    # and guarantee expected/actual at least 10 characters each.
    col_count = 5
    padding = table_padding(col_count)
    suite_w = min(max((len("Test Suite"), *(len(str(r[0])) for r in rows))), 25)
    test_w = min(max((len("Test"), *(len(str(r[1])) for r in rows))), 40)
    status_w = min(max((len("Passed"), *(len(str(r[4])) for r in rows))), 10)

    # Shrink suite/test columns on narrow terminals until expected/actual fit.
    min_suite_w, min_test_w = 12, 20
    while (
        suite_w > min_suite_w
        and (suite_w + test_w + status_w + padding + 24) > max_width
    ):
        suite_w -= 1
    while (
        test_w > min_test_w
        and (suite_w + test_w + status_w + padding + 24) > max_width
    ):
        test_w -= 1

    remaining = max(20, max_width - suite_w - test_w - status_w - padding)
    expected_w = max(10, remaining // 2)
    actual_w = max(10, remaining - expected_w)

    truncated = [
        (
            _truncate(suite, suite_w),
            _truncate(test, test_w),
            _truncate(expected, expected_w),
            _truncate(actual, actual_w),
            _truncate(status, status_w),
        )
        for suite, test, expected, actual, status in rows
    ]

    return rows, tabulate(
        truncated,
        headers=("Test Suite", "Test", "Expected", "Actual", "Passed"),
        tablefmt=TABLE_FORMAT,
        stralign="left",
    )


def _artifact_summary_line(data: dict[str, Any]) -> str:
    """Build a one-line counter/severity summary for an analyzer envelope."""
    findings = data.get("findings", [])
    test_summary = data.get("test_summary")
    is_pql = data.get("analyzer") == "pql_test" or (
        findings and _is_pql_test_finding(findings[0])
    )
    if test_summary and is_pql:
        return (
            f"{test_summary.get('total', 0)} tests, "
            f"{test_summary.get('passed', 0)} passed, "
            f"{test_summary.get('failed', 0)} failed, "
            f"{test_summary.get('skipped', 0)} skipped"
        )
    error_count, warning_count = severity_counts(findings)
    sev_summary = f"({error_count} error(s), {warning_count} warning(s))"
    if test_summary:
        return (
            f"{test_summary.get('total', 0)} tests, "
            f"{test_summary.get('passed', 0)} passed, "
            f"{test_summary.get('failed', 0)} failed "
            f"{sev_summary}"
        )
    if findings:
        return f"{len(findings)} finding(s) {sev_summary}"
    return "no findings"


# The rdl wrapper already prints its wrapped findings table at -v; repeating
# it here, truncated, is the duplicate the RDL review found. pbir and bpa
# predate the shared table and still repeat theirs.
_WRAPPER_PRINTS_FINDINGS = frozenset({"rdl"})


def _print_findings_for_artifact(name: str, stem: str, output_dir: Path) -> None:
    """Read an artifact's envelope and print its findings table."""
    envelope = output_dir / name / stem / "envelope.json"
    if not envelope.exists():
        print(f"      (no envelope found at {envelope})")
        return
    try:
        data = json.loads(envelope.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"      (could not read envelope: {exc})")
        return

    findings = data.get("findings", [])
    if not findings:
        print("      No findings recorded.")
        return

    print(f"    {_artifact_summary_line(data)}")
    table = _format_findings(findings)
    if table:
        print("    Findings:")
        print("\n".join(f"      {line}" for line in table.splitlines()))


def _artifact_summary_prefix(code: int, status: str = "") -> str:
    """Return the icon for an artifact summary line.

    ``status`` distinguishes the one case an exit code cannot: an analyzer
    that exited 0 while warning it did no work.
    """
    if code != 0:
        return "❌"
    return "⚠️" if status == "warning" else "✅"


def _read_artifact_envelope(
    output_dir: Path,
    analyzer: str,
    stem: str,
) -> dict[str, Any] | None:
    """Read an envelope file if present and parseable."""
    envelope = output_dir / analyzer / stem / "envelope.json"
    if not envelope.exists():
        return None
    try:
        return json.loads(envelope.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _envelope_error_warning_counts(data: dict[str, Any] | None) -> tuple[int, int]:
    """Return (error_count, warning_count) from an envelope dict."""
    if data is None:
        return 0, 0
    findings = data.get("findings", [])
    return severity_counts(findings)


def _report_path_for(envelope: dict[str, Any] | None) -> str | None:
    """Return the human-readable report path from an envelope, or None.

    Reads the optional ``native_html_output_path`` key. None covers three
    cases a caller should not have to distinguish: no envelope (a dry run
    read nothing), an analyzer that produces no report, and a key present
    but empty.
    """
    if not envelope:
        return None
    return envelope.get("native_html_output_path") or None


def _display_path(path: Path | str) -> str:
    """Return ``path`` relative to the working directory when it sits inside it.

    Result paths were truncated to fit the summary table, which cut off
    the analyzer and artifact segments and left a string that could be
    neither clicked nor copied. A terminal resolves a relative path
    against its own cwd, so the short form stays clickable and still fits.

    A path outside the working directory -- an ``--output-dir`` somewhere
    else -- keeps its absolute form. `relative_to` refuses those rather
    than emitting a ``../../`` chain, which is the behavior wanted here:
    such a chain would be longer than the absolute path and harder to read.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(Path.cwd()))
    except ValueError:
        return str(resolved)


def _artifact_status(data: dict[str, Any] | None, code: int, errors: int, warnings: int) -> str:
    """Classify one artifact's outcome from its envelope and the analyzer's exit code."""
    if code != 0 or (data and data.get("status") == "failed") or errors > 0:
        return "failed"
    if data and data.get("status") == "skipped":
        return "skipped"
    # An analyzer that exited 0 can still be warning us -- pql-test does when
    # no test managed to run. Falling through would paint that green.
    if data and data.get("status") == "warning":
        return "warning"
    return "warning" if warnings > 0 else "passed"


def build_all_summary_rows(
    output_dir: Path,
    analyzers: tuple[str, ...],
    codes: list[int],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    """Return one row per analyzer/artifact pair, before any rendering.

    Separated from printing so the rows can be asserted directly instead of
    by parsing captured stdout -- and so the per-run index can be built
    from the same rows the table shows, which is what stops the two
    reporting different counts.
    """
    artifact_dir = Path(args.artifact_dir)
    # Must be the resolved target, not args.artifact: this runs its own
    # discovery pass, and a raw stem string would ignore a positional
    # target entirely and reach discover_artifacts as the wrong type.
    target = target_from_args(args)
    dry_run = getattr(args, "dry_run", False)

    rows: list[dict[str, Any]] = []
    for analyzer, code in zip(analyzers, codes):
        glob, _ = ANALYZER_REGISTRY[analyzer]
        stems = service_row_stems(analyzer, args)  # a service run names what it ran, never the checkout
        if stems is None:
            stems = [a.stem for a in discover_artifacts(artifact_dir, glob, target, output_dir=output_dir)]
        if not stems:
            rows.append({
                "analyzer": analyzer,
                "artifact": "(none)",
                "status": "—",
                "errors": 0,
                "warnings": 0,
                "output_path": "",
                "report_path": None,
            })
            continue
        for stem in stems:
            data = None
            if dry_run:
                errors, warnings = 0, 0
                status = "dry-run"
            else:
                data = _read_artifact_envelope(output_dir, analyzer, stem)
                errors, warnings = _envelope_error_warning_counts(data)
                status = _artifact_status(data, code if data is None else 0, errors, warnings)  # envelope wins
            rows.append({
                "analyzer": analyzer,
                "artifact": stem,
                "status": status,
                "errors": errors,
                "warnings": warnings,
                "output_path": str(output_dir / analyzer / stem / "envelope.json"),
                "report_path": _report_path_for(data),
            })
    return rows


def _write_and_open_index(
    rows: list[dict[str, Any]],
    output_dir: Path,
    args: argparse.Namespace,
    analyzers: tuple[str, ...],
) -> None:
    """Write the `fab-test all` index and open it under `--open-report`.

    Split out of `_print_all_summary` to keep that function under the
    branch budget -- this is one self-contained decision (write, name,
    maybe open), not several the caller needs to see.
    """
    report_on = resolve_report(args)
    open_wanted = resolve_open_report(args)
    if report_on and len(analyzers) > 1:
        index = write_index(rows, output_dir)
        if index:
            print(f"  Index:  {_display_path(index)}")
            if open_wanted:
                open_report_in_browser(index)
    elif open_wanted and not report_on:
        # Should not happen -- --open-report auto-enables report generation
        # (resolve_report) -- but never open a stale or nonexistent report
        # from a prior run if it somehow does.
        print(
            "  ⚠ fab-test: --open-report resolved on but report generation "
            "resolved off; skipping"
        )


def _print_all_summary(
    output_dir: Path,
    analyzers: tuple[str, ...],
    codes: list[int],
    args: argparse.Namespace,
) -> int:
    """Print the aggregate summary after `fab-test all` finishes."""
    dry_run = getattr(args, "dry_run", False)
    output_format = getattr(args, "output_format", "text")
    rows = build_all_summary_rows(output_dir, analyzers, codes, args)
    total_errors = sum(int(r["errors"] or 0) for r in rows)
    total_warnings = sum(int(r["warnings"] or 0) for r in rows)
    worst = max(codes, default=0)

    if not rows or all(r["artifact"] == "(none)" for r in rows):
        if output_format == "json":
            print(json.dumps({"artifacts": [], "totals": {"errors": 0, "warnings": 0}}))
        else:
            print("  No artifacts were analyzed.")
        return 0

    if output_format == "json":
        summary = {
            "artifacts": rows,
            "totals": {
                "errors": total_errors,
                "warnings": total_warnings,
            },
            "dry_run": dry_run,
        }
        print(json.dumps(summary, indent=2))
        return worst

    if getattr(args, "quiet", False):
        # Every artifact already printed its own line as its analyzer finished.
        if not dry_run:
            _write_and_open_index(rows, output_dir, args, analyzers)
        return worst

    sep = "═" * 60
    print(f"\n{sep}")
    print("  fab-test all — aggregate summary")
    print(sep)

    # Keep failures/warnings at the top for visibility.
    status_order = {
        "failed": 0,
        "warning": 1,
        "dry-run": 2,
        "passed": 3,
        "skipped": 4,
        "—": 5,
    }
    rows.sort(
        key=lambda r: (
            status_order.get(r["status"], 3),
            r["analyzer"].lower(),
            r["artifact"].lower(),
        )
    )

    # Paths are listed below the table rather than in it. A full envelope
    # path runs ~60 characters and is identical in shape for every row, so
    # two path columns pushed the table past 200 characters -- it wrapped
    # three times in an 80-column terminal, which is what made it
    # unreadable. Out of the grid they stay whole, and therefore clickable.
    # Text format only: --format json returned above, so nothing here can
    # reach a stdout that is contractually one JSON document.
    paint = color_enabled()

    def _count(value: int, color: str) -> str:
        # Zero stays plain so the eye lands only on what needs work.
        return _paint(str(value), color if value else None, enabled=paint)

    table = tabulate(
        [
            (
                r["analyzer"],
                r["artifact"],
                _paint(
                    label := _status_label(r["status"]),
                    _STATUS_COLORS.get(label),
                    enabled=paint,
                ),
                _count(r["errors"], "red"),
                _count(r["warnings"], "yellow"),
            )
            for r in rows
        ],
        headers=("Analyzer", "Artifact", "Status", "Err", "Warn"),
        tablefmt=TABLE_FORMAT,
        stralign="left",
    )
    print("\n".join(f"  {line}" for line in table.splitlines()))

    # One clickable line per artifact: the report when there is one, since
    # that is what a person opens, and the envelope otherwise.
    located = [
        (r, r.get("report_path") or r.get("output_path"))
        for r in rows
        if r["artifact"] != "(none)"
    ]
    if any(path for _r, path in located):
        print()
        for r, path in located:
            if not path:
                continue
            print(f"  {r['analyzer']}/{r['artifact']}")
            print(f"    {_display_path(path)}")

    print(sep)
    analyzed = sum(1 for r in rows if r["artifact"] != "(none)")
    if dry_run:
        print(f"  Dry run: {analyzed} artifact(s) would be analyzed.")
    else:
        print(
            f"  Totals: {_count(total_errors, 'red')} error(s), "
            f"{_count(total_warnings, 'yellow')} warning(s) "
            f"across {analyzed} artifact(s)"
        )
        # Built from these same rows, so the index can never report counts
        # that disagree with the table just printed. Only for a multi-analyzer
        # run: indexing one analyzer is a page pointing at a single link.
        _write_and_open_index(rows, output_dir, args, analyzers)
    print(sep)
    return worst


def _artifact_line(
    name: str, stem: str, output_dir: Path | None
) -> tuple[str, str | None, str]:
    """Return one artifact's summary suffix, its report path, and its status.

    Split out of `_print_summary` so that reading an envelope and deciding
    how to describe it is one job, and printing is another. The status rides
    along because the caller needs it to pick an icon, and reading the
    envelope twice to learn it would be the same file read done twice.
    """
    if output_dir is None:
        return "", None, ""
    envelope = output_dir / name / stem / "envelope.json"
    if not envelope.exists():
        return "", None, ""
    try:
        data = json.loads(envelope.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "  — (could not parse envelope)", None, ""
    report = _report_path_for(data)
    return (
        f"  — {_artifact_summary_line(data)}",
        _display_path(report) if report else None,
        str(data.get("status", "")),
    )


def _print_quiet_summary(name: str, results: list[tuple[str, int]], output_dir: Path | None) -> int:
    """Print one ``-q`` line per artifact and return the worst exit code.

    The line is ``<analyzer> <status> e=<errors> w=<warnings> <where>``.
    ``<where>`` is the envelope path relative to the working directory, or the
    artifact name when the analyzer wrote no envelope. Artifact names hold
    spaces, so it stays the last field. Status is a word, never an icon.
    """
    for stem, code in results:
        data = _read_artifact_envelope(output_dir, name, stem) if output_dir else None
        errors, warnings = _envelope_error_warning_counts(data)
        status = _artifact_status(data, code, errors, warnings)
        where = _display_path(output_dir / name / stem / "envelope.json") if data else stem
        print(f"{name} {status} e={errors} w={warnings} {where}")
    return max((code for _, code in results), default=0)


def _print_summary(
    name: str,
    results: list[tuple[str, int]],
    output_dir: Path | None = None,
    verbosity: str = "",
    output_format: str = "text",
    *,
    show_reports: bool = True,
    args: argparse.Namespace | None = None,
) -> int:
    """Print the per-analyzer summary and return the worst artifact exit code.

    ``show_reports`` is False under `fab-test all`, which lists every
    report beneath its aggregate table -- printing them here too named
    each one twice. `local` keeps them, because it has no aggregate
    listing and would otherwise lose the information entirely. ``args``
    is optional (existing callers don't pass it) and gates `--open-report`
    handling the same way -- no `args`, no opening, same as before this
    parameter existed.
    """
    if output_format == "json":
        rows: list[dict[str, Any]] = []
        for stem, code in results:
            data = None
            if output_dir is not None:
                data = _read_artifact_envelope(output_dir, name, stem)
            errors, warnings = _envelope_error_warning_counts(data)
            if data and data.get("status") in {"skipped", "warning"} and code == 0:
                row_status = data["status"]
            else:
                row_status = "failed" if code != 0 else "passed"
            rows.append({
                "artifact": stem,
                "status": row_status,
                "errors": errors,
                "warnings": warnings,
                "output_path": str(output_dir / name / stem / "envelope.json")
                if output_dir
                else "",
                # Same key as the `all` summary emits. A consumer should not
                # have to branch on how many analyzers happened to run.
                "report_path": _report_path_for(data),
            })
        print(json.dumps({"analyzer": name, "artifacts": rows}, indent=2))
        return max((code for _, code in results), default=0)

    if getattr(args, "quiet", False):
        return _print_quiet_summary(name, results, output_dir)

    sep = "─" * 52
    print(f"\n{sep}")
    print(f"  fab-test {name} — summary ({len(results)} artifact(s))")
    print(sep)
    verbose = verbosity in ("verbose", "debug")
    reports: list[str] = []
    for stem, code in results:
        summary, report, status = _artifact_line(name, stem, output_dir)
        if report:
            reports.append(report)
        print(f"  {_artifact_summary_prefix(code, status)}  {stem}{summary}")
        if code != 0 and verbose and output_dir is not None and name not in _WRAPPER_PRINTS_FINDINGS:
            _print_findings_for_artifact(name, stem, output_dir)

    # A report that is written but never named reads as a flag that did
    # nothing -- which is exactly how `--report` was first reported as broken.
    if show_reports:
        for report in reports:
            print(f"  Report: {report}")
        if args is not None:
            _open_single_analyzer_report(args, name, results, reports, output_dir)
    return max((code for _, code in results), default=0)


def _open_single_analyzer_report(
    args: argparse.Namespace,
    name: str,
    results: list[tuple[str, int]],
    reports: list[str],
    output_dir: Path | None,
) -> None:
    """Build and/or open a single-analyzer run's report(s).

    Split out of `_print_summary` to keep that function under the branch
    budget -- this is one self-contained decision (open the sole report,
    or build and maybe open an index), not several the caller needs to
    see. Mirrors `_write_and_open_index` exactly: an index is written
    whenever a report is on and there is more than one artifact,
    independent of `--open-report`, so `fab-test a11y` (or `bpa`, `pbir`,
    ...) with several artifacts gets the same `fab-test-results/index.html`
    that `fab-test all` gets with several analyzers -- not only when the
    browser-opening flag happens to be set too.
    """
    report_on = resolve_report(args)
    open_wanted = resolve_open_report(args)
    if open_wanted and not report_on:
        # Should not happen -- --open-report auto-enables report generation
        # -- but never open a stale or nonexistent report from a prior run
        # if it somehow does.
        print(
            "  ⚠ fab-test: --open-report resolved on but report generation "
            "resolved off; skipping"
        )
        return
    if len(results) == 1:
        if open_wanted and reports:
            open_report_in_browser(reports[0])
        return
    if len(results) > 1 and report_on and output_dir is not None:
        rows = [
            {
                "analyzer": name,
                "artifact": stem,
                **_index_row_fields(output_dir, name, stem, code),
            }
            for stem, code in results
        ]
        index = write_index(rows, output_dir)
        if index:
            print(f"  Index:  {_display_path(index)}")
            if open_wanted:
                open_report_in_browser(index)


def _index_row_fields(
    output_dir: Path, analyzer: str, stem: str, code: int
) -> dict[str, Any]:
    """Return the status/count/path fields `write_index` needs for one artifact.

    Same envelope-reading logic `build_all_summary_rows` uses for `fab-test
    all`, factored out so a single-analyzer index is built from identical
    rules -- one status classification, not two that could drift apart.
    """
    data = _read_artifact_envelope(output_dir, analyzer, stem)
    errors, warnings = _envelope_error_warning_counts(data)
    return {
        "status": _artifact_status(data, code, errors, warnings),
        "errors": errors,
        "warnings": warnings,
        "output_path": str(output_dir / analyzer / stem / "envelope.json"),
        "report_path": _report_path_for(data),
    }
