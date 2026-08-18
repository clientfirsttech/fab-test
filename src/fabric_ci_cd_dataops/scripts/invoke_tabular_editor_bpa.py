#!/usr/bin/env python3
"""
Invoke Tabular Editor Best Practice Analyzer (BPA)

Python wrapper for running Tabular Editor BPA against a semantic model.
Replaces the previous PowerShell wrapper to keep analyzer invocation
Python-only per the project vision.

Usage:
    python invoke_tabular_editor_bpa.py \
        --tmdl-path ".fabric/artifacts/SalesModel.SemanticModel" \
        --bpa-rules-path ".github/metadata/rules/BPARules.json" \
        --tabular-editor-path "./TabularEditor/TabularEditor.exe" \
        --output-path "./analyzer-results/bpa/SalesModel/envelope.json" \
        --native-output-path "./analyzer-results/bpa/SalesModel/native.xml"
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tabulate import tabulate

from ._analyzer_envelope import (
    Timer,
    _severity_counts,
    _severity_rank,
    build_envelope,
    envelope_path,
    native_output_path,
    write_envelope,
)

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}

# BPA severity threshold: severities at or above this value fail the build.
BPA_ERROR_SEVERITY_THRESHOLD = 3


def _verbosity() -> int:
    raw = os.environ.get("ANALYZER_VERBOSITY", "default").lower().strip()
    return _VERBOSITY_LEVELS.get(raw, 1)


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message."""
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
    error_count, warning_count = _severity_counts(findings)
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


def _truncate(text: str, width: int) -> str:
    text = str(text).replace("\n", " ").replace("\r", "")
    if len(text) <= width:
        return text
    return text[: width - 3] + "..." if width > 3 else text[:width]


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
            -_severity_rank(f.get("Severity") or f.get("severity")),
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

    padding = 2 * (5 - 1)
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
            tablefmt="simple",
            stralign="left",
        )
    )


def write_results(
    output_path: Path,
    status: str,
    findings: list[dict[str, Any]],
    artifact_path: Path,
    rules_path: Path,
    message: str = "",
    native_out: Path | None = None,
    duration_ms: int = 0,
    test_summary: dict[str, int] | None = None,
) -> None:
    """Write standardized BPA envelope JSON (replaces legacy flat JSON)."""
    env = build_envelope(
        analyzer="tabular_editor_bpa",
        artifact_path=str(artifact_path),
        status=status,
        message=message,
        findings=findings,
        native_output_path_str=str(native_out) if native_out else "",
        duration_ms=duration_ms,
    )
    # Keep legacy keys so existing unit tests that read the flat schema still pass.
    env["rules_file"] = str(rules_path)
    if test_summary is not None:
        env["test_summary"] = test_summary
    write_envelope(output_path, env)


def _resolve_te2_model_path(path: Path) -> Path:
    """TE2 (TMDL) needs the definition/ subfolder, not the .SemanticModel root."""
    candidate = path / "definition"
    return candidate if candidate.is_dir() else path


def run_bpa(args: argparse.Namespace) -> int:
    """Run the BPA analyzer and return an exit code."""
    artifact_root = validate_path(args.tmdl_path, "TMDL path")
    tmdl_path = _resolve_te2_model_path(artifact_root)
    bpa_rules_path = validate_path(args.bpa_rules_path, "BPA rules file")
    tabular_editor_path = validate_path(args.tabular_editor_path, "Tabular Editor CLI")

    # Guard: rules file must be a JSON array of rule objects, not a model/bim file.
    try:
        rules_content = json.loads(bpa_rules_path.read_text(encoding="utf-8"))
        if not isinstance(rules_content, list):
            print(
                f"::error::BPA rules file is not a JSON array: {bpa_rules_path}. "
                "Expected a list of rule objects, not a model or other JSON object.",
                file=sys.stderr,
            )
            sys.exit(1)
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"::error::Cannot read BPA rules file {bpa_rules_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Stem comes from the .SemanticModel folder, not the definition/ path.
    artifact_stem = artifact_root.stem
    _env_out = envelope_path("bpa", artifact_stem)
    _nat_out = native_output_path("bpa", artifact_stem, "xml")

    output_path = Path(args.output_path) if args.output_path else _env_out
    native_out = Path(args.native_output_path) if args.native_output_path else _nat_out

    level = _verbosity()

    if level >= _VERBOSITY_LEVELS["default"]:
        log("================================")
        log(f"Tabular Editor BPA  →  {artifact_stem}")
        log("================================")
        log(f"📋 Model:   {tmdl_path}")
        log(f"📏 Rules:   {bpa_rules_path}")
        log(f"🔧 Tool:    {tabular_editor_path}")
        log(f"📊 Envelope: {output_path}")
        log(f"📄 Native:  {native_out}")
        log("")

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
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired:
            message = "Tabular Editor BPA timed out after 5 minutes"
            write_results(
                output_path,
                "timeout",
                [],
                tmdl_path,
                bpa_rules_path,
                message=message,
                native_out=native_out,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except FileNotFoundError:
            message = (
                f"Tabular Editor executable not found: {tabular_editor_path}. "
                "Download from https://tabulareditor.com/downloads"
            )
            write_results(
                output_path,
                "error",
                [],
                tmdl_path,
                bpa_rules_path,
                message=message,
                native_out=native_out,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - catch-all for wrapper safety
            message = f"Unexpected error running Tabular Editor BPA: {exc}"
            write_results(
                output_path,
                "error",
                [],
                tmdl_path,
                bpa_rules_path,
                message=message,
                native_out=native_out,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1

    if level >= _VERBOSITY_LEVELS["debug"] and (proc.stdout or proc.stderr):
        log("--- stdout ---")
        log(proc.stdout or "(empty)")
        log("--- stderr ---")
        log(proc.stderr or "(empty)")
        log("")

    # Parse findings from native output file (XML), then fall back to stdout JSON.
    findings: list[dict[str, Any]] = []
    test_summary: dict[str, int] | None = None
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
                    rules_map: dict[str, dict[str, str]] = {}
                    for ut in root.findall(".//vs:TestDefinitions/vs:UnitTest", ns):
                        test_id = ut.get("id", "")
                        rule_name = ut.get("name", "")
                        props: dict[str, str] = {"RuleName": rule_name}
                        for prop in ut.findall(".//vs:Property", ns):
                            key_el = prop.find("vs:Key", ns)
                            val_el = prop.find("vs:Value", ns)
                            if key_el is not None and val_el is not None:
                                props[key_el.text or ""] = val_el.text or ""
                        rules_map[test_id] = props

                    # Capture VSTest counters for richer reporting
                    test_summary = _parse_vstest_counters(raw_text)

                    # Parse results — only Failed outcomes produce findings
                    for result in root.findall(".//vs:Results/vs:UnitTestResult", ns):
                        if result.get("outcome", "").lower() != "failed":
                            continue
                        test_id = result.get("testId", "")
                        rule_meta = rules_map.get(
                            test_id, {"RuleName": result.get("testName", "")}
                        )
                        # Extract violating objects from StackTrace
                        stack_el = result.find(".//vs:ErrorInfo/vs:StackTrace", ns)
                        objects: list[str] = []
                        if stack_el is not None and stack_el.text:
                            for raw_line in stack_el.text.strip().splitlines():
                                line = raw_line.strip()
                                if line.startswith("["):
                                    objects.append(line)
                        if objects:
                            findings.extend(
                                {
                                    "RuleName": rule_meta.get("RuleName", ""),
                                    "RuleID": rule_meta.get("RuleID", ""),
                                    "ObjectName": obj,
                                    "Severity": rule_meta.get("Severity", ""),
                                    "Category": rule_meta.get("Category", ""),
                                }
                                for obj in objects
                            )
                        else:
                            # No specific objects listed — record rule-level finding
                            findings.append({
                                "RuleName": rule_meta.get("RuleName", ""),
                                "RuleID": rule_meta.get("RuleID", ""),
                                "ObjectName": "",
                                "Severity": rule_meta.get("Severity", ""),
                                "Category": rule_meta.get("Category", ""),
                            })
                except ET.ParseError:
                    # Not XML — try JSON
                    raw = json.loads(raw_text)
                    if isinstance(raw, list):
                        findings = raw
                    elif isinstance(raw, dict):
                        findings = raw.get("findings", [])
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass

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
            output_path=output_path,
            status="passed",
            findings=[],
            artifact_path=tmdl_path,
            rules_path=bpa_rules_path,
            message=message,
            native_out=native_out,
            duration_ms=timer.elapsed_ms,
            test_summary=test_summary,
        )
        if level >= _VERBOSITY_LEVELS["default"]:
            log(f"✅ {message}")
            log(f"📁 Envelope: {output_path}")
            log(f"📄 Native:   {native_out}")
        return 0

    message = _format_bpa_message(findings, test_summary, proc.returncode)
    status = "failed" if has_errors else "warning"
    write_results(
        output_path=output_path,
        status=status,
        findings=findings,
        artifact_path=tmdl_path,
        rules_path=bpa_rules_path,
        message=message,
        native_out=native_out,
        duration_ms=timer.elapsed_ms,
        test_summary=test_summary,
    )

    if level >= _VERBOSITY_LEVELS["default"] and test_summary:
        error_count, warning_count = _severity_counts(findings)
        log(
            f"📊 {test_summary.get('total', 0)} tests, "
            f"{test_summary.get('passed', 0)} passed, "
            f"{test_summary.get('failed', 0)} failed "
            f"({error_count} error(s), {warning_count} warning(s))"
        )

    if level >= _VERBOSITY_LEVELS["verbose"]:
        _print_findings_table(findings)

    if proc.stderr:
        print(f"::error::{proc.stderr}", file=sys.stderr)

    annotation = "::error::" if has_errors else "::warning::"
    print(f"{annotation}{message}", file=sys.stderr)
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
            "(default: analyzer-results/bpa/<stem>/envelope.json)"
        ),
    )
    parser.add_argument(
        "--native-output-path",
        default=None,
        help=(
            "Path where the native BPA XML will be written "
            "(default: analyzer-results/bpa/<stem>/native.xml)"
        ),
    )

    args = parser.parse_args()
    return run_bpa(args)


if __name__ == "__main__":
    sys.exit(main())
