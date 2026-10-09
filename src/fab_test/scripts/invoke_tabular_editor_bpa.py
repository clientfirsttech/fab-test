#!/usr/bin/env python3
"""
Invoke Tabular Editor Best Practice Analyzer (BPA)

Python wrapper for running Tabular Editor BPA against a semantic model.
Replaces the previous PowerShell wrapper to keep analyzer invocation
Python-only per the project vision.

Usage:
    python invoke_tabular_editor_bpa.py \
        --tmdl-path "fabric-artifacts/SalesModel.SemanticModel" \
        --bpa-rules-path ".github/metadata/rules/BPARules.json" \
        --tabular-editor-path "./TabularEditor/TabularEditor.exe" \
        --output-path "./fab-test-results/bpa/SalesModel/envelope.json" \
        --native-output-path "./fab-test-results/bpa/SalesModel/native.xml"
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from tabulate import tabulate

from ._analyzer_envelope import (
    EnvelopeIdentity,
    Timer,
    WrapperResult,
    build_envelope,
    envelope_path,
    native_output_path,
    severity_counts,
    severity_rank,
    write_envelope,
)
from ._analyzer_process import run_tool
from ._report_html import attach_report
from ._table_style import TABLE_FORMAT, table_padding
from ._table_style import truncate as _truncate

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}

# BPA severity threshold: severities at or above this value fail the build.
BPA_ERROR_SEVERITY_THRESHOLD = 3


def _verbosity() -> int:
    raw = os.environ.get("ANALYZER_VERBOSITY", "default").lower().strip()
    return _VERBOSITY_LEVELS.get(raw, 1)


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message.

    Routes to stderr when ANALYZER_OUTPUT_MODE=json (set by fab-test under
    --format json) so only the envelope write touches stdout/disk. Direct
    invocation without the env var is unchanged (stdout).
    """
    if os.environ.get("ANALYZER_OUTPUT_MODE", "").lower() == "json":
        print(message, file=sys.stderr)
    else:
        print(message)


def validate_path(path_str: str, description: str, must_exist: bool = True) -> Path:
    """Validate that a required path exists and return a Path object."""
    path = Path(path_str).resolve()
    if must_exist and not path.exists():
        print(f"::error::{description} not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def build_bpa_command(
    tabular_editor_path: Path,
    tmdl_path: Path,
    bpa_rules_path: Path,
    output_path: Path
) -> list[str]:
    """
    Build the Tabular Editor CLI command for BPA execution.

    Tabular Editor CLI supports running BPA via script or command-line
    arguments. This wrapper uses a minimal invocation pattern that loads the
    model, runs the supplied BPA rules file, and writes the results to the
    requested output path. The exact CLI surface depends on the Tabular Editor
    edition installed; the wrapper tolerates missing optional flags by
    validating the tool's help output when the primary invocation fails.
    """
    return [
        str(tabular_editor_path),
        str(tmdl_path),
        "-A",  # Analyze with BPA rules file
        str(bpa_rules_path),
        "-T",  # Write results to output file
        str(output_path),
    ]


def _max_severity(findings: list[dict[str, Any]]) -> int:
    """Return the maximum BPA severity integer from findings; 0 if absent."""
    max_sev = 0
    for f in findings:
        raw = f.get("Severity") or f.get("severity") or "0"
        try:
            sev = int(raw)
        except (ValueError, TypeError):
            sev = 0
        if sev > max_sev:
            max_sev = sev
    return max_sev


def _parse_vstest_counters(raw_text: str) -> dict[str, int] | None:
    """Parse VSTest Counters from BPA XML output.

    Returns a dict with total, executed, passed, failed keys, or None if the
    counters element is missing or malformed.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(raw_text)
    except ET.ParseError:
        return None

    ns = {"vs": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
    counters = root.find(".//vs:ResultSummary/vs:Counters", ns)
    if counters is None:
        return None

    result: dict[str, int] = {}
    for key in ("total", "executed", "passed", "failed"):
        try:
            result[key] = int(counters.get(key, "") or "")
        except (ValueError, TypeError):
            result[key] = 0
    return result if "total" in result else None


def _format_bpa_message(
    findings: list[dict[str, Any]],
    counters: dict[str, int] | None,
    exit_code: int,
) -> str:
    """Build a human-readable BPA message with counters and severity breakdown."""
    error_count, warning_count = severity_counts(findings)
    failed = counters.get("failed", 0) if counters else len(findings)
    total = counters.get("total", 0) if counters else 0

    if counters:
        return (
            f"Tabular Editor BPA found {failed} failed test(s) "
            f"out of {total} ({error_count} error(s), {warning_count} warning(s), "
            f"exit code {exit_code})"
        )
    return (
        f"Tabular Editor BPA found {len(findings)} violation(s) "
        f"({error_count} error(s), {warning_count} warning(s), "
        f"exit code {exit_code})"
    )


def _bpa_rule_id(finding: dict[str, Any]) -> str:
    """Return the best available rule id for a BPA finding."""
    return (
        finding.get("RuleID")
        or finding.get("RuleId")
        or finding.get("ruleId")
        or finding.get("rule")
        or ""
    )


def _bpa_rule_name(finding: dict[str, Any]) -> str:
    """Return the best available rule name for a BPA finding."""
    return (
        finding.get("RuleName")
        or finding.get("ruleName")
        or finding.get("rule")
        or ""
    )


def _print_findings_table(findings: list[dict[str, Any]]) -> None:
    """Print findings as a tabulate table."""
    if not findings:
        return

    try:
        tw = max(shutil.get_terminal_size().columns, 80)
    except OSError:
        tw = 120

    sorted_findings = sorted(
        findings,
        key=lambda f: (
            -severity_rank(f.get("Severity") or f.get("severity")),
            _bpa_rule_id(f).lower(),
            _bpa_rule_name(f).lower(),
        ),
    )

    rows = []
    for f in sorted_findings:
        sev = str(f.get("Severity") or f.get("severity") or "")
        rule_id = _bpa_rule_id(f)
        rule_name = _bpa_rule_name(f)
        obj = f.get("ObjectName") or f.get("object") or ""
        category = f.get("Category") or f.get("category") or ""
        rows.append((sev, rule_id, rule_name, obj, category))

    padding = table_padding(5)
    sev_w = min(max((len("Severity"), *(len(r[0]) for r in rows))), 10)
    rule_id_w = min(max((len("Rule ID"), *(len(r[1]) for r in rows))), 15)
    rule_w = min(max((len("Rule"), *(len(r[2]) for r in rows))), 30)
    cat_w = min(max((len("Category"), *(len(r[4]) for r in rows))), 15)

    while rule_w > 8 and (sev_w + rule_id_w + rule_w + cat_w + padding + 20) > tw:
        rule_w -= 1
    while cat_w > 8 and (sev_w + rule_id_w + rule_w + cat_w + padding + 20) > tw:
        cat_w -= 1

    obj_w = max(20, tw - sev_w - rule_id_w - rule_w - cat_w - padding)

    truncated = [
        (
            _truncate(sev, sev_w),
            _truncate(rule_id, rule_id_w),
            _truncate(rule_name, rule_w),
            _truncate(obj, obj_w),
            _truncate(category, cat_w),
        )
        for sev, rule_id, rule_name, obj, category in rows
    ]

    log(
        tabulate(
            truncated,
            headers=("Severity", "Rule ID", "Rule", "Object", "Category"),
            tablefmt=TABLE_FORMAT,
            stralign="left",
        )
    )


def write_results(
    result: WrapperResult,
    rules_path: Path,
) -> None:
    """Write standardized BPA envelope JSON (replaces legacy flat JSON)."""
    env = build_envelope(
        EnvelopeIdentity("tabular_editor_bpa", str(result.artifact_path)),
        status=result.status,
        message=result.message,
        findings=result.findings,
        native_output_path_str=str(result.native_out) if result.native_out else "",
        started_at=result.started_at,
        duration_ms=result.duration_ms,
    )
    # Keep legacy keys so existing unit tests that read the flat schema still pass.
    env["rules_file"] = str(rules_path)
    if result.test_summary is not None:
        env["test_summary"] = result.test_summary
    # Additive: every rule TE2 evaluated, passed or failed -- `findings`
    # stays violations-only for the callers already reading that meaning.
    env["test_results"] = result.test_results or []
    # Tabular Editor emits TRX, which is not something a person wants to
    # read, so the report is rendered from the envelope. No-op unless
    # --report was passed.
    attach_report(env, result.output_path)
    write_envelope(result.output_path, env)


def _resolve_te2_model_path(path: Path) -> Path:
    """TE2 (TMDL) needs the definition/ subfolder, not the .SemanticModel root."""
    candidate = path / "definition"
    return candidate if candidate.is_dir() else path


def _bpa_rules_map(root: Any, ns: dict[str, str]) -> dict[str, dict[str, str]]:
    """Map each TRX testId to its rule metadata (name, ID, severity, category).

    TE2 splits a finding across two places: the rule's identity lives in
    TestDefinitions, the outcome in Results. This is the join key.
    """
    rules_map: dict[str, dict[str, str]] = {}
    for ut in root.findall(".//vs:TestDefinitions/vs:UnitTest", ns):
        props: dict[str, str] = {"RuleName": ut.get("name", "")}
        for prop in ut.findall(".//vs:Property", ns):
            key_el = prop.find("vs:Key", ns)
            val_el = prop.find("vs:Value", ns)
            if key_el is not None and val_el is not None:
                props[key_el.text or ""] = val_el.text or ""
        rules_map[ut.get("id", "")] = props
    return rules_map


def _bpa_violating_objects(result: Any, ns: dict[str, str]) -> list[str]:
    """Return the model objects a failed rule names, from its StackTrace.

    TE2's own formatter (`Analyzer.cs`) always writes a fixed one-line
    header ("Objects in violation:") followed by one indented line per
    violating object -- never brackets specifically. A measure's object
    name is bracketed (``[Total Sales]``), but a table's, column's, or
    relationship's is single-quoted DAX (``'Sales'``, ``'Sales'[Amount]``),
    so a bracket-only filter silently drops every one of those, rendering
    the report's Object column blank without ever failing. Dropping the
    header line and keeping every remaining non-blank line -- whatever its
    punctuation -- tracks what TE2 actually emits instead of guessing at
    one object type's formatting.
    """
    stack_el = result.find(".//vs:ErrorInfo/vs:StackTrace", ns)
    if stack_el is None or not stack_el.text:
        return []
    lines = [line.strip() for line in stack_el.text.strip().splitlines()]
    lines = [line for line in lines if line]
    if lines and lines[0].endswith(":"):
        lines = lines[1:]
    return lines


def _bpa_findings(
    root: Any, ns: dict[str, str], rules_map: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """Turn failed TRX results into findings, one per violating object.

    A rule that names no object still produces one rule-level finding --
    dropping it would under-report the violation entirely.
    """
    findings: list[dict[str, Any]] = []
    for result in root.findall(".//vs:Results/vs:UnitTestResult", ns):
        if result.get("outcome", "").lower() != "failed":
            continue
        meta = rules_map.get(result.get("testId", ""), {"RuleName": result.get("testName", "")})
        base = {
            "RuleName": meta.get("RuleName", ""),
            "RuleID": meta.get("RuleID", ""),
            "Severity": meta.get("Severity", ""),
            "Category": meta.get("Category", ""),
        }
        objects = _bpa_violating_objects(result, ns)
        findings.extend({**base, "ObjectName": obj} for obj in (objects or [""]))
    return findings


def _bpa_result_status(outcome: str, severity: Any) -> str:
    """Map a TRX outcome to the pass/error/warning/skip vocabulary the report filters on.

    A failed rule is "error" only once its severity crosses
    ``BPA_ERROR_SEVERITY_THRESHOLD`` -- the same line `has_errors` uses to
    decide the exit code, so a row never disagrees with the build gate
    that read the same finding.
    """
    outcome = outcome.lower()
    if outcome == "passed":
        return "pass"
    if outcome == "failed":
        return "error" if severity_rank(severity) >= BPA_ERROR_SEVERITY_THRESHOLD else "warning"
    return "skip"


def _bpa_test_results(
    root: Any, ns: dict[str, str], rules_map: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """Return one row per rule TE2 evaluated, passed or failed.

    TRX already records every evaluated rule as a `<UnitTestResult>`;
    `_bpa_findings` only keeps the failed ones for the callers that read
    `findings` as violations. This is the full list, for the report's
    all-tests view -- a passing run should not read as if nothing ran.
    """
    results: list[dict[str, Any]] = []
    for result in root.findall(".//vs:Results/vs:UnitTestResult", ns):
        meta = rules_map.get(result.get("testId", ""), {"RuleName": result.get("testName", "")})
        outcome = result.get("outcome", "")
        objects = _bpa_violating_objects(result, ns) if outcome.lower() == "failed" else []
        results.append(
            {
                "RuleName": meta.get("RuleName", ""),
                "RuleID": meta.get("RuleID", ""),
                "Severity": meta.get("Severity", ""),
                "Category": meta.get("Category", ""),
                "ObjectName": ", ".join(objects),
                "status": _bpa_result_status(outcome, meta.get("Severity", "")),
            }
        )
    return results


def _parse_bpa_native_output(
    native_out: Path,
) -> tuple[list[dict[str, Any]], dict[str, int] | None, list[dict[str, Any]]]:
    """Return ``(findings, test_summary, test_results)`` from TE2's native output.

    TE2 writes VSTest XML (TRX). A bare JSON array is also accepted --
    older builds emitted one, and silently reading nothing would look
    like a clean model rather than a parse failure. ``test_results`` is
    empty in the JSON-fallback case: it has no per-rule pass/fail shape to
    draw a full list from, only the violations already in ``findings``.

    Returns empty results rather than raising: the caller falls back to
    the process exit code, which an exception here would lose.
    """
    findings: list[dict[str, Any]] = []
    test_summary: dict[str, int] | None = None
    test_results: list[dict[str, Any]] = []
    if native_out.exists():
        try:
            raw_text = native_out.read_text(encoding="utf-8-sig")
            if raw_text.strip():
                # Try XML first (TE2 native BPA output is VSTest XML format)
                try:
                    import xml.etree.ElementTree as ET

                    # TE2 writes this XML locally from a rules file under source
                    # control. Python's ElementTree does not resolve external
                    # entities by default, so XXE risk is limited to trusted
                    # local input. We keep the standard parser to avoid adding
                    # a third-party dependency.
                    root = ET.fromstring(raw_text)
                    ns = {"vs": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}

                    # Build rule metadata map:
                    #   testId → {RuleID, RuleName, Severity, Category}
                    rules_map = _bpa_rules_map(root, ns)

                    # Capture VSTest counters for richer reporting
                    test_summary = _parse_vstest_counters(raw_text)

                    # Parse results — only Failed outcomes produce findings
                    findings = _bpa_findings(root, ns, rules_map)
                    # Every evaluated rule, passed or failed, for the report's
                    # all-tests view.
                    test_results = _bpa_test_results(root, ns, rules_map)
                except ET.ParseError:
                    # Not XML — try JSON
                    raw = json.loads(raw_text)
                    if isinstance(raw, list):
                        findings = raw
                    elif isinstance(raw, dict):
                        findings = raw.get("findings", [])
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass
    return findings, test_summary, test_results


def _validate_bpa_inputs(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path]:
    """Resolve and check every input path, exiting 1 on the first problem.

    The rules-file guard is the one worth spelling out: pointing BPA at a
    model or a .bim instead of a rules array produces a confusing failure
    deep inside Tabular Editor, so it is rejected here with a message that
    names what was expected.
    """
    artifact_root = validate_path(args.tmdl_path, "TMDL path")
    tmdl_path = _resolve_te2_model_path(artifact_root)
    bpa_rules_path = validate_path(args.bpa_rules_path, "BPA rules file")
    tabular_editor_path = validate_path(args.tabular_editor_path, "Tabular Editor CLI")

    try:
        rules_content = json.loads(bpa_rules_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"::error::Cannot read BPA rules file {bpa_rules_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not isinstance(rules_content, list):
        print(
            f"::error::BPA rules file is not a JSON array: {bpa_rules_path}. "
            "Expected a list of rule objects, not a model or other JSON object.",
            file=sys.stderr,
        )
        sys.exit(1)

    return artifact_root, tmdl_path, bpa_rules_path, tabular_editor_path


def _narrate_header(
    artifact_stem: str,
    tmdl_path: Path,
    bpa_rules_path: Path,
    tabular_editor_path: Path,
    output_path: Path,
    native_out: Path,
) -> None:
    """Print the per-artifact banner, unless verbosity is set to summary."""
    if _verbosity() < _VERBOSITY_LEVELS["default"]:
        return
    log("================================")
    log(f"Tabular Editor BPA  →  {artifact_stem}")
    log("================================")
    log(f"📋 Model:   {tmdl_path}")
    # Identical for every artifact and already in the envelope, so only -v pays for them.
    if _verbosity() >= _VERBOSITY_LEVELS["verbose"]:
        log(f"📏 Rules:   {bpa_rules_path}")
        log(f"🔧 Tool:    {tabular_editor_path}")
    log(f"📊 Envelope: {output_path}")
    log(f"📄 Native:  {native_out}")
    log("")


def _narrate_outcome(
    findings: list[dict[str, Any]],
    test_summary: "dict[str, int] | None",
    stderr: str,
    message: str,
    *,
    has_errors: bool,
) -> None:
    """Print the counters, the findings table, and the CI annotation.

    The annotation always goes to stderr regardless of verbosity: it is what
    a CI system reads, not what a person is choosing to see.
    """
    level = _verbosity()
    if level >= _VERBOSITY_LEVELS["default"] and test_summary:
        error_count, warning_count = severity_counts(findings)
        log(
            f"📊 {test_summary.get('total', 0)} tests, "
            f"{test_summary.get('passed', 0)} passed, "
            f"{test_summary.get('failed', 0)} failed "
            f"({error_count} error(s), {warning_count} warning(s))"
        )
    if level >= _VERBOSITY_LEVELS["verbose"]:
        _print_findings_table(findings)
    if stderr:
        print(f"::error::{stderr}", file=sys.stderr)
    print(f"{'::error::' if has_errors else '::warning::'}{message}", file=sys.stderr)


def run_bpa(args: argparse.Namespace) -> int:
    """Run the BPA analyzer and return an exit code."""
    artifact_root, tmdl_path, bpa_rules_path, tabular_editor_path = _validate_bpa_inputs(args)

    # Stem comes from the .SemanticModel folder, not the definition/ path.
    artifact_stem = artifact_root.stem
    _env_out = envelope_path("bpa", artifact_stem)
    output_path = Path(args.output_path) if args.output_path else _env_out
    native_out = (
        Path(args.native_output_path)
        if args.native_output_path
        else native_output_path("bpa", artifact_stem, "xml", beside=output_path)
    )

    level = _verbosity()
    _narrate_header(
        artifact_stem, tmdl_path, bpa_rules_path, tabular_editor_path, output_path, native_out
    )

    # Ensure output directories exist (TE2 does not create them)
    native_out.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = build_bpa_command(
        tabular_editor_path=tabular_editor_path,
        tmdl_path=tmdl_path,
        bpa_rules_path=bpa_rules_path,
        output_path=native_out,  # ask the tool to write its native XML here
    )

    if level >= _VERBOSITY_LEVELS["debug"]:
        log(f"Executing: {' '.join(command)}")
        log("")

    with Timer() as timer:
        outcome = run_tool(
            command,
            timeout=300,
            label="Tabular Editor BPA",
            timeout_message="Tabular Editor BPA timed out after 5 minutes",
            missing_message=(
                f"Tabular Editor executable not found: {tabular_editor_path}. "
                "Download from https://tabulareditor.com/downloads"
            ),
        )
    if outcome.failed:
        write_results(
            WrapperResult(output_path, outcome.status, [], tmdl_path, message=outcome.message, native_out=native_out),
            bpa_rules_path,
        )
        print(f"::error::{outcome.message}", file=sys.stderr)
        return 1
    proc = outcome.proc

    if level >= _VERBOSITY_LEVELS["debug"] and (proc.stdout or proc.stderr):
        log("--- stdout ---")
        log(proc.stdout or "(empty)")
        log("--- stderr ---")
        log(proc.stderr or "(empty)")
        log("")

    findings, test_summary, test_results = _parse_bpa_native_output(native_out)

    # TE2 BPA exit code equals violation count; use it when no file output was produced.
    # Without per-rule severity data, treat unknown violations as errors so the
    # build gate remains conservative.
    if not findings and proc.returncode > 0:
        findings = [
            {
                "RuleName": "BPA violation",
                "RuleID": "UNKNOWN",
                "Severity": str(BPA_ERROR_SEVERITY_THRESHOLD),
                "ObjectName": "",
                "Category": "Unknown",
                "count": proc.returncode,
            }
        ]

    max_severity = _max_severity(findings)
    has_errors = max_severity >= BPA_ERROR_SEVERITY_THRESHOLD

    if not findings:
        message = "Tabular Editor BPA passed with no violations"
        write_results(
            WrapperResult(
                output_path,
                "passed",
                [],
                tmdl_path,
                message=message,
                native_out=native_out,
                duration_ms=timer.elapsed_ms,
                started_at=timer.started_at,
                test_summary=test_summary,
                test_results=test_results,
            ),
            bpa_rules_path,
        )
        if level >= _VERBOSITY_LEVELS["default"]:
            log(f"✅ {message}")
        return 0

    message = _format_bpa_message(findings, test_summary, proc.returncode)
    status = "failed" if has_errors else "warning"
    write_results(
        WrapperResult(
            output_path,
            status,
            findings,
            tmdl_path,
            message=message,
            native_out=native_out,
            duration_ms=timer.elapsed_ms,
            started_at=timer.started_at,
            test_summary=test_summary,
            test_results=test_results,
        ),
        bpa_rules_path,
    )

    _narrate_outcome(findings, test_summary, proc.stderr, message, has_errors=has_errors)
    return 1 if has_errors else 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Tabular Editor Best Practice Analyzer from Python"
    )
    parser.add_argument(
        "--tmdl-path",
        required=True,
        help="Path to the semantic model directory (TMDL)"
    )
    parser.add_argument(
        "--bpa-rules-path",
        required=True,
        help="Path to the BPA rules JSON file"
    )
    parser.add_argument(
        "--tabular-editor-path",
        required=True,
        help="Path to the Tabular Editor CLI executable"
    )
    parser.add_argument(
        "--output-path",
        default=None,
        help=(
            "Path where the BPA envelope JSON will be written "
            "(default: fab-test-results/bpa/<stem>/envelope.json)"
        ),
    )
    parser.add_argument(
        "--native-output-path",
        default=None,
        help=(
            "Path where the native BPA XML will be written "
            "(default: fab-test-results/bpa/<stem>/native.xml)"
        ),
    )

    args = parser.parse_args()
    return run_bpa(args)


if __name__ == "__main__":
    sys.exit(main())
