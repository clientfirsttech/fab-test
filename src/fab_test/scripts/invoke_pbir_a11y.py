#!/usr/bin/env python3
"""
Invoke pbir-a11y

Python wrapper for running pbir-a11y (accessibility checks for Power BI
PBIR reports -- contrast, alt text, tab order, target size, and more)
against a Report artifact, emitting the standard fab-test result envelope.

Mirrors invoke_pbir_inspector.py's shape, with one structural difference:
pbir-a11y's `--json` output goes to stdout only (the CLI has no `--output`
flag for it), so this wrapper is what persists that JSON to `native.json`
rather than locating a file the tool wrote itself.

Usage:
    python invoke_pbir_a11y.py \
        --artifact-path "fabric-artifacts/SalesReport.Report" \
        --a11y-path "./pbir-a11y/dist/cli.js" \
        --output-path "./a11y-results.json"
"""

import argparse
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
from ._report_html import attach_report

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}


def _verbosity() -> int:
    raw = os.environ.get("ANALYZER_VERBOSITY", "default").lower().strip()
    return _VERBOSITY_LEVELS.get(raw, 1)


# pbir-a11y is a single-pass static parse of files already on disk -- no
# network, no subprocess of its own -- so this is generous headroom, not a
# measured ceiling.
A11Y_TIMEOUT_SECONDS = 120

DEFAULT_OUTPUT_PATH = "./a11y-results.json"

# Matches pbir-a11y's own CLI default (`--fail-on <severity>`, default
# "fail"): only a fail-severity issue blocks the run when the caller passes
# no explicit --fail-on, so a warn/info finding is reported without failing.
DEFAULT_FAIL_ON = "fail"


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message.

    Routes to stderr when ANALYZER_OUTPUT_MODE=json (set by fab-test under
    --format json) so only the envelope write touches stdout/disk.
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


def build_a11y_command(node_path: str, a11y_path: Path, artifact_path: Path, fail_on: str) -> list[str]:
    """Build the pbir-a11y CLI command.

    Always passes `--json` -- this wrapper parses stdout itself rather than
    exposing a human-formatted mode, since the envelope is the contract
    every fab-test caller reads.
    """
    return [node_path, str(a11y_path), "check", str(artifact_path), "--json", "--fail-on", fail_on]


def write_results(result: WrapperResult) -> None:
    """Write the standardized pbir-a11y envelope JSON.

    ``attach_report`` renders `report.html` beside the envelope when
    `--report` is enabled (a no-op otherwise) -- pbir-a11y has no native
    HTML output of its own to defer to, unlike PBIR Inspector.
    """
    env = build_envelope(
        EnvelopeIdentity("pbir_a11y", str(result.artifact_path)),
        status=result.status,
        message=result.message,
        findings=result.findings,
        native_output_path_str=str(result.native_out) if result.native_out else "",
        duration_ms=result.duration_ms,
    )
    attach_report(env, result.output_path)
    write_envelope(result.output_path, env)


def parse_a11y_json(raw_text: str) -> dict[str, Any] | None:
    """Parse pbir-a11y's `--json` stdout. Returns None for empty/invalid output
    (the tool-error path: a bad or unreadable project path writes nothing)."""
    if not raw_text.strip():
        return None
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return None


# pbir-a11y reports four severities; fab-test's shared vocabulary has three
# (error/warning/info). "pass" never appears on a real issue in practice --
# it exists in the tool's own type union, not its actual output -- so it is
# mapped defensively rather than assumed unreachable.
_A11Y_SEVERITY_MAP = {"fail": "error", "warn": "warning", "info": "info", "pass": "info"}


def _map_a11y_severity(severity: str | None) -> str:
    return _A11Y_SEVERITY_MAP.get((severity or "").lower(), "warning")


def _visual_label(visual: dict[str, Any]) -> str:
    """Best available human label for a visual, from the fields pbir-a11y ships."""
    return visual.get("displayName") or visual.get("type") or visual.get("id") or "?"


def _normalize_a11y_issue(page_name: str, visual_name: str | None, issue: dict[str, Any]) -> dict[str, Any]:
    """Translate one pbir-a11y issue into the shared finding schema.

    The shared schema's four columns (rule/severity/object/message) are
    always present; `category`, `page`, and `visual` are additive extra
    keys -- ignored by the shared renderer, available to a caller reading
    the raw envelope JSON who wants to filter or group by them (the
    `--report` task groups by category using these).
    """
    location = f"{page_name} / {visual_name}" if visual_name else page_name
    category = issue.get("category") or "?"
    return {
        "rule": issue.get("id") or "",
        "severity": _map_a11y_severity(issue.get("severity")),
        "object": location,
        "message": f"[{category}] {issue.get('title', '')}: {issue.get('detail', '')}".strip(),
        "category": issue.get("category"),
        "page": page_name,
        "visual": visual_name,
    }


def extract_findings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten pbir-a11y's page/visual-nested issues into the shared finding list.

    Every issue is included regardless of severity -- pbir-a11y itself
    always reports fail/warn/info together and only `--fail-on` changes
    which of them block the exit code, not which are surfaced.
    """
    findings = []
    for page_report in result.get("pages", []) or []:
        page = page_report.get("page", {}) or {}
        page_name = page.get("displayName") or page.get("id") or "?"
        findings.extend(
            _normalize_a11y_issue(page_name, None, issue) for issue in page_report.get("issues", []) or []
        )
        for visual_report in page_report.get("visuals", []) or []:
            visual_name = _visual_label(visual_report.get("visual", {}) or {})
            findings.extend(
                _normalize_a11y_issue(page_name, visual_name, issue)
                for issue in visual_report.get("issues", []) or []
            )
    return findings


def _write_a11y_failure(
    output_path: Path, artifact_path: Path, native_out: Path, message: str
) -> int:
    """Write a failure envelope for a run that never produced tool output."""
    write_results(
        WrapperResult(output_path, "error", [], artifact_path, message=message, native_out=native_out)
    )
    print(f"::error::{message}", file=sys.stderr)
    return 1


def _run_a11y_process(
    command: list[str], artifact_path: Path, output_path: Path, native_out: Path
) -> "tuple[subprocess.CompletedProcess, int] | int":
    """Run pbir-a11y, timed. Returns ``(proc, elapsed_ms)`` on success, or
    writes a failure envelope and returns an exit code if it could not run."""
    with Timer() as timer:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                # Node writes UTF-8 to stdout regardless of platform; without
                # an explicit encoding, `text=True` decodes with the OS
                # default (cp1252 on Windows), corrupting any non-ASCII
                # character pbir-a11y reports (e.g. "Card · fields: ...").
                encoding="utf-8",
                timeout=A11Y_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired:
            message = f"pbir-a11y timed out after {A11Y_TIMEOUT_SECONDS} seconds"
            return _write_a11y_failure(output_path, artifact_path, native_out, message)
        except FileNotFoundError:
            message = f"Could not run pbir-a11y: {command[0]} not found"
            return _write_a11y_failure(output_path, artifact_path, native_out, message)
        except Exception as exc:  # noqa: BLE001 - wrapper boundary; failures become an envelope
            message = f"Unexpected error running pbir-a11y: {exc}"
            return _write_a11y_failure(output_path, artifact_path, native_out, message)
    return proc, timer.elapsed_ms


def _classify_a11y_result(proc_returncode: int, findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive status/message/counts, keying tool-error vs. rule-violation off
    pbir-a11y's own exit code (2 = tool error) rather than reinventing it.
    """
    error_count = sum(1 for f in findings if f["severity"] == "error")
    warning_count = sum(1 for f in findings if f["severity"] == "warning")
    if proc_returncode == 2:
        return {
            "status": "error",
            "message": "pbir-a11y reported a tool error (a bad or unreadable project path)",
            "has_errors": True,
            "error_count": error_count,
            "warning_count": warning_count,
        }
    if not findings:
        return {
            "status": "passed",
            "message": "pbir-a11y passed with no findings",
            "has_errors": False,
            "error_count": 0,
            "warning_count": 0,
        }
    has_errors = proc_returncode == 1
    message = (
        f"pbir-a11y found {len(findings)} finding(s) "
        f"(errors: {error_count}, warnings: {warning_count}, exit code {proc_returncode})"
    )
    return {
        "status": "failed" if has_errors else "warning",
        "message": message,
        "has_errors": has_errors,
        "error_count": error_count,
        "warning_count": warning_count,
    }


def _log_run_header(
    level: int, artifact_stem: str, artifact_path: Path, a11y_path: Path, output_path: Path, native_out: Path
) -> None:
    if level < _VERBOSITY_LEVELS["default"]:
        return
    log("================================")
    log(f"pbir-a11y  ->  {artifact_stem}")
    log("================================")
    log(f"Artifact: {artifact_path}")
    # Identical for every artifact, so only -v pays for it.
    if level >= _VERBOSITY_LEVELS["verbose"]:
        log(f"Tool:     {a11y_path}")
    log(f"Envelope: {output_path}")
    log(f"Native JSON: {native_out}")
    log("")


def _log_a11y_outcome(
    outcome: dict[str, Any], findings: list[dict[str, Any]], level: int
) -> None:
    if level < _VERBOSITY_LEVELS["default"]:
        return
    if not findings:
        log(outcome["message"])
    if findings:
        log(
            f"{len(findings)} finding(s) "
            f"({outcome['error_count']} error(s), {outcome['warning_count']} warning(s))"
        )


def run_a11y(args: argparse.Namespace) -> int:
    """Run the pbir-a11y analyzer and return an exit code."""
    artifact_path = validate_path(args.artifact_path, "Report artifact path")
    a11y_path = validate_path(args.a11y_path, "pbir-a11y CLI entry point")

    artifact_stem = artifact_path.stem
    output_path = Path(args.output_path) if args.output_path else envelope_path("a11y", artifact_stem)
    native_out = native_output_path("a11y", artifact_stem, "json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    native_out.parent.mkdir(parents=True, exist_ok=True)

    node_path = shutil.which("node")
    if node_path is None:
        message = "node not found on PATH; install Node.js (https://nodejs.org, >= 18)"
        return _write_a11y_failure(output_path, artifact_path, native_out, message)

    fail_on = getattr(args, "fail_on", None) or DEFAULT_FAIL_ON
    level = _verbosity()
    _log_run_header(level, artifact_stem, artifact_path, a11y_path, output_path, native_out)

    command = build_a11y_command(node_path, a11y_path, artifact_path, fail_on)
    if level >= _VERBOSITY_LEVELS["debug"]:
        log(f"Executing: {' '.join(command)}")
        log("")

    result = _run_a11y_process(command, artifact_path, output_path, native_out)
    if isinstance(result, int):
        return result
    proc, elapsed_ms = result

    if level >= _VERBOSITY_LEVELS["debug"] and (proc.stdout or proc.stderr):
        log("--- stdout ---")
        log(proc.stdout or "(empty)")
        log("--- stderr ---")
        log(proc.stderr or "(empty)")
        log("")

    # pbir-a11y writes its --json output to stdout only (no --output flag),
    # so persisting native.json is this wrapper's job, not the tool's.
    native_out.write_text(proc.stdout or "", encoding="utf-8")

    parsed = parse_a11y_json(proc.stdout or "")
    findings = extract_findings(parsed) if parsed else []
    outcome = _classify_a11y_result(proc.returncode, findings)

    write_results(
        WrapperResult(
            output_path,
            outcome["status"],
            findings,
            artifact_path,
            message=outcome["message"],
            native_out=native_out,
            duration_ms=elapsed_ms,
        )
    )
    _log_a11y_outcome(outcome, findings, level)

    if outcome["status"] == "error":
        print(f"::error::{outcome['message']}", file=sys.stderr)
        if proc.stderr:
            print(f"::error::{proc.stderr}", file=sys.stderr)
        return 1
    if not findings:
        return 0

    annotation = "::error::" if outcome["has_errors"] else "::warning::"
    print(f"{annotation}{outcome['message']}", file=sys.stderr)
    return 1 if outcome["has_errors"] else 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run pbir-a11y from Python")
    parser.add_argument(
        "--artifact-path",
        required=True,
        help="Path to the report artifact directory (PBIR)",
    )
    parser.add_argument(
        "--a11y-path",
        required=True,
        help="Path to the pbir-a11y CLI entry point (dist/cli.js)",
    )
    parser.add_argument(
        "--output-path",
        default=None,
        help=(
            "Path where the pbir-a11y envelope JSON will be written "
            "(default: fab-test-results/a11y/<stem>/envelope.json)"
        ),
    )
    parser.add_argument(
        "--fail-on",
        default=None,
        help="Forwarded to pbir-a11y's own --fail-on (warn|fail; tool default: fail)",
    )
    parser.add_argument(
        "--verbose",
        "--v",
        action="store_true",
        default=False,
        help="Enable verbose output (prints the command and native output)",
    )

    args = parser.parse_args()
    if args.verbose:
        os.environ["ANALYZER_VERBOSITY"] = "verbose"
    return run_a11y(args)


if __name__ == "__main__":
    sys.exit(main())
