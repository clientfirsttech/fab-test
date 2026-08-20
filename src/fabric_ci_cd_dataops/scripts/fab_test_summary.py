"""Summary formatting and table rendering for ``fab-test``.

This module keeps ``fab_test.py`` focused on orchestration. It reads analyzer
envelopes, renders findings tables, and prints per-analyzer and aggregate
summaries for both text and JSON output formats.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from tabulate import tabulate

from ._analyzer_envelope import _severity_counts, normalize_findings
from ._report_html import resolve_report, write_index
from ._target import target_from_args
from .fab_test_registry import ANALYZER_REGISTRY, discover_artifacts


def _print_list(rows: list[dict[str, Any]], output_format: str = "text") -> int:
    """Print the `fab-test list` capability report. Always exits 0."""
    if output_format == "json":
        print(json.dumps({"analyzers": rows}, indent=2))
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
        tablefmt="simple",
        stralign="left",
    )
    print(table)
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
    print(tabulate(rows, headers=("Check", "Value"), tablefmt="simple", stralign="left"))
    if payload.get("detail"):
        print(f"\n  {payload['detail']}")
    if payload.get("remediation"):
        print(f"  → {payload['remediation']}")
    return exit_code


def _print_doctor(rows: list[dict[str, Any]], output_format: str = "text") -> int:
    """Print the `fab-test doctor` readiness report.

    Returns 0 if at least one analyzer is ready, else 1.
    """
    any_ready = any(r["ready"] for r in rows)

    if output_format == "json":
        print(json.dumps({"analyzers": rows}, indent=2))
        return 0 if any_ready else 1

    for r in rows:
        icon = "✅" if r["ready"] else "❌"
        location = f" — {r['resolved_path']}" if r["resolved_path"] else ""
        print(f"{icon} {r['analyzer']}: {r['reason']}{location}")
        if not r["ready"] and r["remediation"]:
            print(f"   → {r['remediation']}")
    return 0 if any_ready else 1


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


def _pql_test_status(finding: dict) -> str:
    """Map a pql-test result dict to a terminal status label."""
    if finding.get("error"):
        return "ERROR"
    if finding.get("skipped"):
        return "SKIPPED"
    if finding.get("passed"):
        return "PASS"
    return "FAIL"


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
    padding = 2 * (4 - 1)  # 2 spaces between each of the 4 columns
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
        tablefmt="simple",
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
        status = _pql_test_status(f)
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
    padding = 2 * (col_count - 1)
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
        tablefmt="simple",
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
    error_count, warning_count = _severity_counts(findings)
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


def _artifact_summary_prefix(code: int) -> str:
    """Return the icon for an artifact summary line."""
    return "✅" if code == 0 else "❌"


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
    return _severity_counts(findings)


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


def _print_all_summary(
    output_dir: Path,
    analyzers: tuple[str, ...],
    codes: list[int],
    args: argparse.Namespace,
) -> int:
    """Print aggregate summary after `fab-test all` finishes."""
    artifact_dir = Path(args.artifact_dir)
    # Must be the resolved target, not args.artifact: this runs its own
    # discovery pass, and a raw stem string would ignore a positional
    # target entirely and reach discover_artifacts as the wrong type.
    target = target_from_args(args)
    dry_run = getattr(args, "dry_run", False)
    output_format = getattr(args, "output_format", "text")

    rows: list[dict[str, Any]] = []
    total_errors = 0
    total_warnings = 0
    any_failed = any(c != 0 for c in codes)

    for analyzer, code in zip(analyzers, codes):
        glob, _ = ANALYZER_REGISTRY[analyzer]
        stems = [a.stem for a in discover_artifacts(artifact_dir, glob, target)]
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
                if code != 0 or (data and data.get("status") == "failed") or errors > 0:
                    status = "failed"
                elif data and data.get("status") == "skipped":
                    status = "skipped"
                elif warnings > 0:
                    status = "warning"
                else:
                    status = "passed"
            total_errors += errors
            total_warnings += warnings
            output_path = str(output_dir / analyzer / stem / "envelope.json")
            rows.append({
                "analyzer": analyzer,
                "artifact": stem,
                "status": status,
                "errors": errors,
                "warnings": warnings,
                "output_path": output_path,
                "report_path": _report_path_for(data),
            })

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
        return 1 if any_failed else 0

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

    def _status_label(status: str) -> str:
        if status == "passed":
            return "✅ passed"
        if status == "warning":
            return "⚠️ warning"
        if status == "failed":
            return "❌ failed"
        if status == "dry-run":
            return "💨 dry-run"
        if status == "skipped":
            return "⏭️ skipped"
        return status

    # Only worth a column when something in this run actually produced a
    # report; otherwise it is a header over nothing but blanks.
    any_report = any(r.get("report_path") for r in rows)

    def _cells(r: dict[str, Any]) -> tuple[str, ...]:
        base = (
            r["analyzer"],
            r["artifact"],
            _status_label(r["status"]),
            str(r["errors"]),
            str(r["warnings"]),
            # Not truncated: a cut path is neither clickable nor copyable,
            # and the tail is the half that says which analyzer it came from.
            _display_path(r["output_path"]) if r["output_path"] else "",
        )
        if not any_report:
            return base
        report = r.get("report_path")
        return (*base, _display_path(report) if report else "")

    headers = ["Analyzer", "Artifact", "Status", "Errors", "Warnings", "Output"]
    if any_report:
        headers.append("Report")

    table = tabulate(
        [_cells(r) for r in rows],
        headers=headers,
        tablefmt="simple",
        stralign="left",
    )
    print("\n".join(f"  {line}" for line in table.splitlines()))
    print(sep)
    analyzed = sum(1 for r in rows if r["artifact"] != "(none)")
    if dry_run:
        print(f"  Dry run: {analyzed} artifact(s) would be analyzed.")
    else:
        print(
            f"  Totals: {total_errors} error(s), {total_warnings} warning(s) "
            f"across {analyzed} artifact(s)"
        )
        # Built from these same rows, so the index can never report counts
        # that disagree with the table just printed. Only for a multi-analyzer
        # run: indexing one analyzer is a page pointing at a single link.
        if resolve_report(args) and len(analyzers) > 1:
            index = write_index(rows, output_dir)
            if index:
                print(f"  Index:  {_display_path(index)}")
    print(sep)
    return 1 if any_failed else 0


def _print_summary(
    name: str,
    results: list[tuple[str, int]],
    output_dir: Path | None = None,
    verbosity: str = "",
    output_format: str = "text",
) -> int:
    if output_format == "json":
        rows: list[dict[str, Any]] = []
        for stem, code in results:
            data = None
            if output_dir is not None:
                data = _read_artifact_envelope(output_dir, name, stem)
            errors, warnings = _envelope_error_warning_counts(data)
            if data and data.get("status") == "skipped" and code == 0:
                row_status = "skipped"
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
            })
        print(json.dumps({"analyzer": name, "artifacts": rows}, indent=2))
        return 1 if any(code != 0 for _, code in results) else 0

    sep = "─" * 52
    print(f"\n{sep}")
    print(f"  fab-test {name} — summary ({len(results)} artifact(s))")
    print(sep)
    any_failed = False
    verbose = verbosity in ("verbose", "debug")
    for stem, code in results:
        icon = _artifact_summary_prefix(code)
        summary = ""
        if output_dir is not None:
            envelope = output_dir / name / stem / "envelope.json"
            if envelope.exists():
                try:
                    data = json.loads(envelope.read_text(encoding="utf-8"))
                    summary = f"  — {_artifact_summary_line(data)}"
                except (json.JSONDecodeError, OSError):
                    summary = "  — (could not parse envelope)"
        print(f"  {icon}  {stem}{summary}")
        if code != 0:
            any_failed = True
            if verbose and output_dir is not None:
                _print_findings_for_artifact(name, stem, output_dir)
    return 1 if any_failed else 0
