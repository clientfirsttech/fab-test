#!/usr/bin/env python3
"""Invoke fab-test's own RDL (paginated report) static analyzer.

Pure Python, no external tool: parses a ``.rdl`` file and runs the checks
registered in ``_rdl_lint.py`` against its rule catalog. See the RDL
Static Analysis epic and plan/rdl-rule-set.md for what each rule ID means.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from ._analyzer_envelope import (
    EnvelopeIdentity,
    Timer,
    WrapperResult,
    build_envelope,
    envelope_path,
    native_output_path,
    write_envelope,
)
from ._metadata import RDL_RULES, default_repo_root, metadata_path
from ._rdl_lint import CHECKS, RdlParseError, build_test_results, load_rule_catalog, parse_rdl, run_checks
from ._report_html import attach_report
from ._table_style import findings_table

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}


def _verbosity() -> int:
    raw = os.environ.get("ANALYZER_VERBOSITY", "default").lower().strip()
    return _VERBOSITY_LEVELS.get(raw, 1)


def _default_rules_path() -> Path:
    return metadata_path(RDL_RULES, default_repo_root())


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message.

    Routes to stderr under ``ANALYZER_OUTPUT_MODE=json``, matching every
    other wrapper, so only the envelope write touches stdout/disk in JSON
    mode.
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


def write_results(result: WrapperResult, rules_path: Path) -> None:
    """Write the standardized rdl envelope JSON, and a report.html if enabled."""
    env = build_envelope(
        EnvelopeIdentity("rdl", str(result.artifact_path)),
        status=result.status,
        message=result.message,
        findings=result.findings,
        native_output_path_str=str(result.native_out) if result.native_out else "",
        duration_ms=result.duration_ms,
        started_at=result.started_at,
    )
    env["rules_file"] = str(rules_path)
    # Additive: every rule the catalog knows about, passed/skipped/fired --
    # mirrors BPA's and PBIR's own test_results (HTML Report Format epic).
    env["test_results"] = result.test_results or []
    attach_report(env, result.output_path)
    write_envelope(result.output_path, env)


def _log_run_header(
    level: int, artifact_stem: str, artifact_path: Path, rules_path: Path, output_path: Path, native_out: Path
) -> None:
    """Print the pre-run banner, once verbosity clears the default threshold."""
    if level < _VERBOSITY_LEVELS["default"]:
        return
    log("================================")
    log(f"RDL Static Analysis  →  {artifact_stem}")
    log("================================")
    log(f"📋 Artifact: {artifact_path}")
    # Identical for every artifact and already in the envelope, so only -v pays for it.
    if level >= _VERBOSITY_LEVELS["verbose"]:
        log(f"📏 Rules:    {rules_path}")
    log(f"📊 Envelope: {output_path}")
    log(f"📄 Native JSON: {native_out}")
    log("")


def _log_findings(level: int, findings: list[dict]) -> None:
    """Print the findings table at -v; the result line above already counts them."""
    if not findings or level < _VERBOSITY_LEVELS["verbose"]:
        return
    try:
        width = max(shutil.get_terminal_size().columns, 80)
    except OSError:
        width = 120
    log(findings_table(findings, width))


def _severity_counts(findings: list[dict]) -> tuple[int, int]:
    # A missing or unknown severity counts as an error (aidd-analyzer-contract).
    errors = sum(1 for f in findings if f.get("severity") not in ("warning", "info"))
    warnings = sum(1 for f in findings if f.get("severity") == "warning")
    return errors, warnings


def _analyze(
    artifact_path: Path, rules_path: Path
) -> tuple[list[dict], list[dict], tuple[str, str, str] | None]:
    """Load the catalog, parse the report and run the checks.

    Returns ``(catalog, findings, failure)``; ``failure`` is ``(rule, object,
    message)`` when the rules file or the report could not be read, and the
    findings are empty then.
    """
    try:
        catalog = load_rule_catalog(rules_path)
    except (OSError, ValueError) as exc:
        return [], [], ("RULES", rules_path.name, f"could not load rules file {rules_path}: {exc}")
    try:
        root, namespace = parse_rdl(artifact_path)
    except RdlParseError as exc:
        return catalog, [], ("PARSE", artifact_path.name, str(exc))
    return catalog, run_checks(root, namespace, catalog), None


def _outcome(findings: list[dict], test_results: list[dict]) -> tuple[str, str, int, int]:
    """Return ``(status, message, error_count, warning_count)`` for a finished run."""
    error_count, warning_count = _severity_counts(findings)
    if not findings:
        checked = sum(1 for row in test_results if row["status"] == "pass")
        return "passed", f"rdl lint passed with no findings ({checked} rule(s) checked)", 0, 0
    status = "failed" if error_count else ("warning" if warning_count else "passed")
    message = (
        f"rdl lint found {len(findings)} finding(s) "
        f"(errors: {error_count}, warnings: {warning_count})"
    )
    return status, message, error_count, warning_count


def run_rdl_lint(args: argparse.Namespace) -> int:
    """Run the RDL static analyzer and return an exit code."""
    artifact_path = validate_path(args.artifact_path, "RDL artifact path")
    # Not validate_path: a missing rules file must write an error envelope (below),
    # not exit first and leave a stale envelope for the parent to report as current.
    rules_path = Path(getattr(args, "rules_path", "") or str(_default_rules_path())).resolve()

    artifact_stem = artifact_path.stem
    output_path = (
        Path(args.output_path) if getattr(args, "output_path", "") else envelope_path("rdl", artifact_stem)
    )
    native_out = native_output_path("rdl", artifact_stem, "json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    native_out.parent.mkdir(parents=True, exist_ok=True)

    level = _verbosity()
    _log_run_header(level, artifact_stem, artifact_path, rules_path, output_path, native_out)

    with Timer() as timer:
        catalog, findings, failure = _analyze(artifact_path, rules_path)

    if level >= _VERBOSITY_LEVELS["debug"] and failure is None:
        planned = sum(1 for rule in catalog if rule.get("status", "active") != "active")
        log(f"🔎 Rules: {len(catalog) - planned} active, {planned} planned (not run)")

    if failure is not None:
        error_rule, error_object, parse_error = failure
        findings = [{"rule": error_rule, "severity": "error", "object": error_object, "message": parse_error}]
        native_out.write_text(json.dumps(findings, indent=2), encoding="utf-8")
        write_results(
            WrapperResult(
                output_path, "error", findings, artifact_path,
                message=parse_error, native_out=native_out,
                duration_ms=timer.elapsed_ms, started_at=timer.started_at, test_results=[],
            ),
            rules_path,
        )
        if level >= _VERBOSITY_LEVELS["default"]:
            log(f"❌ {parse_error}")
        print(f"::error::{parse_error}", file=sys.stderr)
        return 1

    test_results = build_test_results(catalog, findings, set(CHECKS))
    native_out.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    status, message, error_count, warning_count = _outcome(findings, test_results)

    write_results(
        WrapperResult(
            output_path, status, findings, artifact_path,
            message=message, native_out=native_out,
            duration_ms=timer.elapsed_ms, started_at=timer.started_at, test_results=test_results,
        ),
        rules_path,
    )

    if level >= _VERBOSITY_LEVELS["default"]:
        icon = "✅" if status == "passed" else ("⚠️" if status == "warning" else "❌")
        log(f"{icon} {message}")
        _log_findings(level, findings)

    if error_count:
        print(f"::error::{message}", file=sys.stderr)
        return 1
    if warning_count:
        print(f"::warning::{message}", file=sys.stderr)
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run fab-test's RDL static analyzer")
    parser.add_argument("--artifact-path", required=True, help="Path to the .rdl artifact")
    parser.add_argument(
        "--rules-path", default="", help="Path to the RDL rules JSON file (default: packaged rdl-rules.json)"
    )
    parser.add_argument("--output-path", default="", help="Path to write the envelope JSON")
    parser.add_argument(
        "--verbose", "--v", action="store_true", default=False, help="Enable verbose output"
    )
    args = parser.parse_args()
    if args.verbose:
        os.environ["ANALYZER_VERBOSITY"] = "verbose"
    raise SystemExit(run_rdl_lint(args))


if __name__ == "__main__":
    main()
