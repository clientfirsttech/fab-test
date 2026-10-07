#!/usr/bin/env python3
"""
Invoke PBIR Inspector

Python wrapper for running PBIR Inspector against a Power BI report artifact.
Aligns with the project vision of Python-only analyzer invocation.

Usage:
    python invoke_pbir_inspector.py \
        --artifact-path "fabric-artifacts/SalesReport.Report" \
        --rules-path ".github/metadata/rules/pbi-inspector-custom-rules.json" \
        --inspector-path "./PBIR-Inspector/PBIRInspectorCLI" \
        --output-path "./pbir-results.json"
"""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ._analyzer_envelope import (
    EnvelopeIdentity,
    Timer,
    WrapperResult,
    build_envelope,
    envelope_path,
    native_output_path,
    write_envelope,
)
from ._pbir_report_fixups import fix_favicon_link, fix_log_type_filter, fix_screenshot_images
from ._table_style import findings_table

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}


def _verbosity() -> int:
    raw = os.environ.get("ANALYZER_VERBOSITY", "default").lower().strip()
    return _VERBOSITY_LEVELS.get(raw, 1)


# Default timeout for PBIR Inspector execution (seconds).
INSPECTOR_TIMEOUT_SECONDS = 120

# Default output path when the caller does not specify one.
DEFAULT_OUTPUT_PATH = "./pbir-results.json"


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


def ensure_executable(inspector_path: Path) -> None:
    """Ensure the inspector binary has executable permissions."""
    if not inspector_path.is_file():
        print(
            f"::error::PBIR Inspector binary not found: {inspector_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    if os.name == "posix" and not inspector_path.stat().st_mode & 0o111:
        try:
            inspector_path.chmod(inspector_path.stat().st_mode | 0o111)
        except OSError as e:
            print(
                f"::error::Failed to make PBIR Inspector executable: {e}",
                file=sys.stderr,
            )
            sys.exit(1)


def build_inspector_command(
    inspector_path: Path,
    artifact_path: Path,
    rules_path: Path,
    output_path: Path,
    output_format: str = "JSON",
    verbose: bool = True,
) -> list[str]:
    """Build the PBIR Inspector CLI command."""
    command: list[str] = [
        str(inspector_path),
        "-fabricitem",
        str(artifact_path),
        "-rules",
        str(rules_path),
        "-output",
        str(output_path),
        "-formats",
        output_format,
    ]
    if verbose:
        command.extend(["-verbose", "true"])
    return command


def write_results(
    result: WrapperResult,
    rules_path: Path,
    native_html_out: "Path | None" = None,
) -> None:
    """Write standardized PBIR Inspector envelope JSON."""
    env = build_envelope(
        EnvelopeIdentity("pbir_inspector", str(result.artifact_path)),
        status=result.status,
        message=result.message,
        findings=result.findings,
        native_output_path_str=str(result.native_out) if result.native_out else "",
        duration_ms=result.duration_ms,
    )
    env["rules_file"] = str(rules_path)
    if native_html_out is not None:
        env["native_html_output_path"] = str(native_html_out)
    # Additive: every rule PBIR Inspector evaluated, passed or failed --
    # `findings` stays violations-only for callers already reading that
    # meaning. Mirrors BPA's `test_results` (HTML Report Format epic).
    env["test_results"] = result.test_results or []
    write_envelope(result.output_path, env)


def parse_findings(raw_text: str) -> list[dict[str, Any]]:
    """Parse PBIR Inspector JSON output into a list of findings."""
    if not raw_text.strip():
        return []

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed

    if isinstance(parsed, dict):
        # Some versions wrap results under an "items" or "findings" key;
        # PBIR Inspector native output uses "Results".
        for key in ("findings", "items", "results", "Results"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value

    return []


def _coerce_log_type(value: Any) -> int | None:
    """Normalize PBIR LogType to int, tolerating string-encoded values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    return None


def _is_error_finding(finding: dict[str, Any]) -> bool:
    """Return True if a PBIR finding should fail the build.

    PBIR Inspector uses ``LogType`` (0 = Error, 1 = Warning) and ``Pass``.
    A finding is only an error-level violation when ``LogType == 0`` **and**
    ``Pass == false``. Passed results are never violations, regardless of
    ``LogType``.
    """
    log_type = _coerce_log_type(finding.get("LogType"))
    return log_type == 0 and finding.get("Pass") is False


def _is_warning_finding(finding: dict[str, Any]) -> bool:
    """Return True if a PBIR finding is a warning-level violation."""
    return (
        _coerce_log_type(finding.get("LogType")) == 1
        and finding.get("Pass") is False
    )


def _is_violation(finding: dict[str, Any]) -> bool:
    """Return True if the finding represents an actionable violation."""
    return _is_error_finding(finding) or _is_warning_finding(finding)


def _page_name(finding: dict[str, Any]) -> str:
    """Extract a page name from a PBIR finding."""
    parent = finding.get("ParentDisplayName") or ""
    item_path = finding.get("ItemPath") or ""
    if parent:
        return parent
    if item_path:
        parts = [p for p in item_path.replace("\\", "/").split("/") if p]
        if parts:
            return parts[0]
    return ""


def _object_name(finding: dict[str, Any]) -> str:
    """Extract an object name from a PBIR finding."""
    item_path = finding.get("ItemPath") or ""
    if item_path:
        parts = [p for p in item_path.replace("\\", "/").split("/") if p]
        if parts:
            return parts[-1]
    return finding.get("ParentDisplayName") or ""


def _pbir_severity_label(finding: dict[str, Any]) -> str:
    """Return a severity label string for a PBIR finding."""
    return "Error" if _is_error_finding(finding) else "Warning"


def _pbir_severity_rank(finding: dict[str, Any]) -> int:
    """Return numeric severity rank for sorting PBIR findings (errors first)."""
    return 3 if _is_error_finding(finding) else 2


def _pbir_rule_id(finding: dict[str, Any]) -> str:
    """Return the best available rule id for a PBIR finding."""
    return (
        finding.get("RuleId")
        or finding.get("RuleID")
        or finding.get("ruleId")
        or finding.get("rule")
        or ""
    )


def _normalize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Translate a PBIR Inspector result into the shared finding schema.

    The shared schema expects ``rule``, ``severity``, ``object``, and
    ``message``. PBIR Inspector uses ``RuleId``, ``LogType`` (0 = error,
    1 = warning), ``ParentDisplayName``, and ``Message``. The object
    field is surfaced as the page/display name so the verbose table is
    immediately actionable.
    """
    severity = "error" if _is_error_finding(finding) else "warning"
    return {
        "rule": _pbir_rule_id(finding),
        "severity": severity,
        "object": finding.get("ParentDisplayName") or "",
        "message": finding.get("Message") or "",
    }


def _pbir_status(finding: dict[str, Any]) -> str:
    """Map a PBIR finding to the pass/error/warning vocabulary test_results shares."""
    if _is_error_finding(finding):
        return "error"
    if _is_warning_finding(finding):
        return "warning"
    return "pass"


def _pbir_test_results(raw_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one row per rule result PBIR Inspector evaluated, passed or failed.

    ``findings`` stays violations-only for the callers already reading
    that meaning (exit code, printed table); this is the full list --
    additive, same as BPA's ``_bpa_test_results`` -- so telemetry can see
    what ran even on a run with nothing to report.
    """
    return [{**_normalize_finding(f), "status": _pbir_status(f)} for f in raw_findings]


def _print_findings_table(findings: list[dict[str, Any]]) -> None:
    """Print normalized PBIR findings as the shared findings table."""
    if not findings:
        return

    try:
        tw = max(shutil.get_terminal_size().columns, 80)
    except OSError:
        tw = 120

    log(findings_table(findings, tw))


def _log_run_header(
    level: int,
    artifact_stem: str,
    artifact_path: Path,
    rules_path: Path,
    inspector_path: Path,
    output_path: Path,
    native_out: Path,
) -> None:
    """Print the pre-run banner, once verbosity clears the default threshold."""
    if level < _VERBOSITY_LEVELS["default"]:
        return
    log("================================")
    log(f"PBIR Inspector  →  {artifact_stem}")
    log("================================")
    log(f"📋 Artifact: {artifact_path}")
    # Identical for every artifact and already in the envelope, so only -v pays for them.
    if level >= _VERBOSITY_LEVELS["verbose"]:
        log(f"📏 Rules:    {rules_path}")
        log(f"🔧 Tool:     {inspector_path}")
    log(f"📊 Envelope: {output_path}")
    log(f"📄 Native JSON: {native_out}")
    log("")


def _write_inspector_failure(
    output_path: Path,
    artifact_path: Path,
    rules_path: Path,
    native_out: Path,
    status: str,
    message: str,
) -> int:
    """Write a failure envelope for a process that never produced output."""
    write_results(
        WrapperResult(output_path, status, [], artifact_path, message=message, native_out=native_out),
        rules_path,
    )
    print(f"::error::{message}", file=sys.stderr)
    return 1


def _run_inspector_process(
    command: list[str],
    output_path: Path,
    artifact_path: Path,
    rules_path: Path,
    native_out: Path,
    inspector_path: Path,
) -> "tuple[subprocess.CompletedProcess, int] | int":
    """Run the inspector binary, timed. Returns ``(proc, elapsed_ms)`` on success,
    or writes a failure envelope and returns an exit code if it could not run."""
    with Timer() as timer:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=INSPECTOR_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired:
            message = f"PBIR Inspector timed out after {INSPECTOR_TIMEOUT_SECONDS} seconds"
            return _write_inspector_failure(output_path, artifact_path, rules_path, native_out, "timeout", message)
        except FileNotFoundError:
            message = f"PBIR Inspector binary not found: {inspector_path}"
            return _write_inspector_failure(output_path, artifact_path, rules_path, native_out, "error", message)
        except Exception as exc:  # noqa: BLE001 - wrapper boundary; failures become an envelope
            message = f"Unexpected error running PBIR Inspector: {exc}"
            return _write_inspector_failure(output_path, artifact_path, rules_path, native_out, "error", message)
    return proc, timer.elapsed_ms


def _read_native_output(native_out: Path, fallback_stdout: str) -> str:
    """Return PBIR Inspector's raw JSON, preferring the file it wrote to stdout."""
    raw_text = ""
    if native_out.is_dir():
        json_files = sorted(
            native_out.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if json_files:
            try:
                # PBIR Inspector can write a UTF-8 BOM at the start of the
                # JSON file; utf-8-sig strips it before json.loads sees it.
                raw_text = json_files[0].read_text(encoding="utf-8-sig")
            except OSError:
                raw_text = ""
    elif native_out.exists():
        try:
            raw_text = native_out.read_text(encoding="utf-8-sig")
        except OSError:
            raw_text = ""

    if not raw_text.strip() and fallback_stdout:
        raw_text = fallback_stdout
    return raw_text


def _locate_native_html(native_out: Path, emit_html: bool, inspector_path: Path) -> Path | None:
    """Return the generated HTML report, fixing up its embedded assets, if any.

    ``native_out`` is reused run over run for the same artifact, so an
    older report (e.g. from a prior invocation, or one that predates the
    screenshot fix) can linger alongside the fresh one. Sorted newest-first
    by mtime -- the same rule `_read_native_output` already applies to its
    ``*.json`` glob, and for the same reason -- an unsorted glob's order is
    filesystem-dependent and can silently pick the stale file instead.
    """
    if not (emit_html and native_out.is_dir()):
        return None
    html_files = sorted(
        native_out.glob("*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not html_files:
        return None
    native_html_out = html_files[0]
    fix_favicon_link(native_html_out, inspector_path)
    fix_screenshot_images(native_html_out)
    fix_log_type_filter(native_html_out)
    return native_html_out


def _classify_inspector_result(
    findings: list[dict[str, Any]], returncode: int, has_output: bool = True
) -> dict[str, Any]:
    """Derive status/message/counts from findings and the process outcome -- no I/O.

    ``has_output`` distinguishes "ran clean, nothing to report" from "never
    produced output" -- a nonzero exit with no output means the tool did not
    run at all (e.g. the .NET runtime is missing), which reads as a broken
    installation, not a pass. A zero exit with no output is still a pass,
    exactly as before this distinction existed.
    """
    error_count = sum(1 for f in findings if f.get("severity") == "error")
    warning_count = sum(1 for f in findings if f.get("severity") == "warning")
    if not findings:
        if returncode != 0 and not has_output:
            return {
                "status": "error",
                "message": (
                    f"PBIR Inspector failed to run and produced no output "
                    f"(exit code {returncode}); see stderr for the underlying cause"
                ),
                "has_errors": True,
                "error_count": 0,
                "warning_count": 0,
            }
        return {
            "status": "passed",
            "message": "PBIR Inspector passed with no findings",
            "has_errors": False,
            "error_count": 0,
            "warning_count": 0,
        }
    has_errors = error_count > 0
    message = (
        f"PBIR Inspector found {len(findings)} finding(s) "
        f"(errors: {error_count}, warnings: {warning_count}, "
        f"exit code {returncode})"
    )
    return {
        "status": "failed" if has_errors else "warning",
        "message": message,
        "has_errors": has_errors,
        "error_count": error_count,
        "warning_count": warning_count,
    }


def _log_inspector_outcome(
    outcome: dict[str, Any],
    findings: list[dict[str, Any]],
    native_html_out: Path | None,
    level: int,
) -> None:
    """Print the post-run summary lines, matching the pre-split log order."""
    if level < _VERBOSITY_LEVELS["default"]:
        return
    if not findings:
        icon = "✅" if outcome["status"] == "passed" else "❌"
        log(f"{icon} {outcome['message']}")
    if native_html_out:
        log(f"📄 Native HTML: {native_html_out}")
    if findings:
        log(f"📊 {len(findings)} finding(s) ({outcome['error_count']} error(s), {outcome['warning_count']} warning(s))")
        if level >= _VERBOSITY_LEVELS["verbose"]:
            _print_findings_table(findings)


def _clear_stale_screenshot_folder(native_out: Path) -> None:
    """Remove a leftover ``PBIInspectorPNG`` folder before invoking FabInspCLI.

    ``native_out`` is reused run-over-run for the same artifact, but
    FabInspCLI does not regenerate ``PBIInspectorPNG`` against an
    already-populated output directory -- while it does randomize every
    finding's ``Id`` on every run. Left in place, a second run's report
    ends up pointing `fix_screenshot_images`'s lookup at the first run's
    screenshots (PBIR Screenshot Correlation epic: confirmed live, 22/22
    keys matched on a clean run, 0/22 once a stale folder was reused).
    Removing it here forces FabInspCLI to write a fresh set that matches
    the run it belongs to.

    Never raises: a folder that can't be removed is a convenience lost,
    not a reason to fail the run before the inspector has even started.
    """
    folder = native_out / "PBIInspectorPNG"
    with contextlib.suppress(OSError):
        shutil.rmtree(folder)


def run_inspector(args: argparse.Namespace) -> int:
    """Run the PBIR Inspector analyzer and return an exit code."""
    artifact_path = validate_path(args.artifact_path, "Report artifact path")
    rules_path = validate_path(args.rules_path, "Rules file")
    inspector_path = validate_path(args.inspector_path, "PBIR Inspector binary")
    ensure_executable(inspector_path)

    artifact_stem = artifact_path.stem
    output_path = Path(args.output_path) if args.output_path else envelope_path("pbir", artifact_stem)
    native_out = native_output_path("pbir", artifact_stem, "json")
    emit_html: bool = getattr(args, "emit_html", False)

    level = _verbosity()
    _log_run_header(level, artifact_stem, artifact_path, rules_path, inspector_path, output_path, native_out)

    # Ensure output directories exist before invoking the tool.
    native_out.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if emit_html:
        _clear_stale_screenshot_folder(native_out)

    formats = "JSON,HTML" if emit_html else "JSON"
    command = build_inspector_command(
        inspector_path=inspector_path,
        artifact_path=artifact_path,
        rules_path=rules_path,
        output_path=native_out,
        output_format=formats,
    )

    if level >= _VERBOSITY_LEVELS["debug"]:
        log(f"Executing: {' '.join(command)}")
        log("")

    result = _run_inspector_process(command, output_path, artifact_path, rules_path, native_out, inspector_path)
    if isinstance(result, int):
        return result
    proc, elapsed_ms = result

    if level >= _VERBOSITY_LEVELS["debug"] and (proc.stdout or proc.stderr):
        log("--- stdout ---")
        log(proc.stdout or "(empty)")
        log("--- stderr ---")
        log(proc.stderr or "(empty)")
        log("")

    raw_text = _read_native_output(native_out, proc.stdout)
    raw_findings = parse_findings(raw_text)
    findings = [_normalize_finding(f) for f in raw_findings if _is_violation(f)]
    test_results = _pbir_test_results(raw_findings)
    native_html_out = _locate_native_html(native_out, emit_html, inspector_path)

    outcome = _classify_inspector_result(findings, proc.returncode, has_output=bool(raw_findings))
    write_results(
        WrapperResult(
            output_path,
            outcome["status"],
            findings,
            artifact_path,
            message=outcome["message"],
            native_out=native_out,
            duration_ms=elapsed_ms,
            test_results=test_results,
        ),
        rules_path,
        native_html_out=native_html_out,
    )
    _log_inspector_outcome(outcome, findings, native_html_out, level)

    if outcome["status"] == "passed":
        return 0

    if proc.stderr:
        print(f"::error::{proc.stderr}", file=sys.stderr)

    annotation = "::error::" if outcome["has_errors"] else "::warning::"
    print(f"{annotation}{outcome['message']}", file=sys.stderr)
    return 1 if outcome["has_errors"] else 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run PBIR Inspector from Python"
    )
    parser.add_argument(
        "--artifact-path",
        required=True,
        help="Path to the report artifact directory (PBIR)",
    )
    parser.add_argument(
        "--rules-path",
        required=True,
        help="Path to the PBIR Inspector rules JSON file",
    )
    parser.add_argument(
        "--inspector-path",
        required=True,
        help="Path to the PBIR Inspector CLI binary",
    )
    parser.add_argument(
        "--output-path",
        default=None,
        help=(
            "Path where the PBIR Inspector envelope JSON will be written "
            "(default: fab-test-results/pbir/<stem>/envelope.json)"
        ),
    )
    parser.add_argument(
        "--emit-html",
        action="store_true",
        default=False,
        help="Also emit HTML output to native.html/ alongside native.json/",
    )
    parser.add_argument(
        "--verbose",
        "--v",
        action="store_true",
        default=False,
        help="Enable verbose output (prints findings table and paths)",
    )

    args = parser.parse_args()
    if args.verbose:
        os.environ["ANALYZER_VERBOSITY"] = "verbose"
    return run_inspector(args)


if __name__ == "__main__":
    sys.exit(main())
