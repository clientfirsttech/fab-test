#!/usr/bin/env python3
"""Invoke pql-test against a semantic model artifact.

This wrapper stays offline-friendly by accepting a path to the artifact and
emitting the same JSON result envelope used by the other analyzer wrappers.
The implementation tries to use the published ``pql-test`` CLI when available,
but it also supports a fallback of ``python -m pql_test`` if the console entry
point is not installed.
"""

import argparse
import json
import os
import shutil
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
from ._analyzer_process import run_tool
from ._report_html import attach_report

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}


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


def build_command(
    artifact_path: Path,
    output_path: Path,
    env: str = "",
    workspace_id: str = "",
) -> list[str]:
    """Build the pql-test run-tests command."""
    command = ["pql-test", "run-tests", str(artifact_path)]
    if env:
        command.extend(["--env", env])
    if workspace_id:
        command.extend(["--workspace-id", workspace_id])
    command.extend(["--output", str(output_path)])
    return command


def _pql_env() -> dict[str, str]:
    """Map Fabric credential env vars to pql-test env vars.

    Keeps service principal secrets out of command lines and process listings
    by passing them through the environment rather than CLI flags.
    """
    env = {**os.environ}
    tenant_id = os.getenv("FABRIC_TENANT_ID")
    client_id = os.getenv("FABRIC_SERVICE_PRINCIPAL_ID")
    client_secret = os.getenv("FABRIC_SERVICE_PRINCIPAL_SECRET")
    if tenant_id:
        env["PQL_TENANT_ID"] = tenant_id
    if client_id:
        env["PQL_CLIENT_ID"] = client_id
    if client_secret:
        env["PQL_CLIENT_SECRET"] = client_secret
    return env


def _is_pql_test_skipped(result: dict[str, Any]) -> bool:
    """Return True when a pql-test result entry represents a skipped test."""
    return bool(result.get("skipped"))


def _parse_native_output(native_path: Path):
    """Read pql-test native JSON output file.

    Returns (findings, test_results, test_summary) or (None, None, None) if unavailable.
    """
    if not native_path.exists():
        return None, None, None
    try:
        data = json.loads(native_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, None, None
    if not isinstance(data, dict):
        return None, None, None
    results = data.get("results", [])
    if not isinstance(results, list):
        results = []
    findings = [
        r
        for r in results
        if isinstance(r, dict)
        and not r.get("passed", True)
        and not _is_pql_test_skipped(r)
    ]
    test_summary = None
    counter_keys = ("passed", "failed", "skipped", "total")
    if all(isinstance(data.get(k), int) for k in counter_keys):
        test_summary = {
            "passed": data["passed"],
            "failed": data["failed"],
            "skipped": data["skipped"],
            "total": data["total"],
        }
    return findings, results, test_summary


def parse_findings(raw_text: str) -> list[dict[str, Any]]:
    """Parse pql-test JSON output into a list of findings."""
    if not raw_text.strip():
        return []

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed

    if isinstance(parsed, dict):
        for key in ("findings", "results", "test_results"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value

    return []


def write_results(
    result: WrapperResult,
    desktop_port: "int | None" = None,
    desktop_model_name: str = "",
) -> None:
    """Write standardized pql-test envelope JSON."""
    env = build_envelope(
        EnvelopeIdentity("pql_test", str(result.artifact_path)),
        status=result.status,
        message=result.message,
        findings=result.findings,
        native_output_path_str=str(result.native_out) if result.native_out else "",
        started_at=result.started_at,
        duration_ms=result.duration_ms,
    )
    env["test_results"] = result.test_results or []
    if result.test_summary is not None:
        env["test_summary"] = result.test_summary
    if desktop_port is not None:
        env["desktop"] = {"port": desktop_port, "model_name": desktop_model_name}
    # pql-test emits JSON only, so the readable report is rendered from the
    # envelope. No-op unless --report was passed.
    attach_report(env, result.output_path)
    write_envelope(result.output_path, env)


def _resolve_pql_command(command: list[str]) -> list[str]:
    """Return ``command`` with its executable resolved, or a module fallback.

    Checks PATH first, then the repository's own ``.venv`` -- keyed off the
    working directory rather than the installed package location, so the
    fallback works whether fab-test runs from source or from a wheel. When
    nothing is found, ``pql-test`` is reachable as ``python -m pql_test``.
    """
    executable = shutil.which(command[0])
    if not executable:
        repo_root = Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve()
        for venv_subdir in ("Scripts", "bin"):
            candidate = repo_root / ".venv" / venv_subdir / command[0]
            if sys.platform == "win32" and not candidate.suffix:
                candidate = candidate.with_suffix(".exe")
            if candidate.exists():
                executable = str(candidate)
                break
    if executable:
        return [executable, *command[1:]]
    if command[0] == "pql-test":
        return [sys.executable, "-m", "pql_test", *command[1:]]
    return list(command)


def _summarize_results(
    test_results: "list[dict[str, Any]] | None",
) -> "dict[str, int] | None":
    """Count passed/failed/skipped when pql-test did not report its own counters."""
    if not test_results:
        return None
    total = len(test_results)
    passed = sum(1 for r in test_results if isinstance(r, dict) and r.get("passed"))
    skipped = sum(
        1 for r in test_results if isinstance(r, dict) and _is_pql_test_skipped(r)
    )
    return {
        "passed": passed,
        "failed": total - passed - skipped,
        "skipped": skipped,
        "total": total,
    }


_CONNECTION_ERROR_MARKER = "a connection cannot be made"


def _is_connection_error(result: dict[str, Any]) -> bool:
    """Whether a failing result's error is pql-test being unable to reach the model.

    pql-test discovers tests statically from the .SemanticModel's PQL
    definitions -- no live connection needed -- then tries to execute each
    one. When the model is unreachable (e.g. a closed Desktop session), each
    execution fails with this ADOMD.NET message rather than an assertion
    mismatch.
    """
    error = result.get("error") or ""
    return _CONNECTION_ERROR_MARKER in str(error).lower()


def _is_connection_skip(findings: list[dict[str, Any]]) -> bool:
    """Whether every failure in this run was pql-test failing to reach the model.

    One genuine assertion failure among connection errors still fails the
    run -- a real failure must never hide behind a platform-availability
    skip.
    """
    return bool(findings) and all(_is_connection_error(f) for f in findings)


_NOTHING_RAN = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}


def _pql_status(
    test_summary: "dict[str, int] | None",
    findings: list[dict[str, Any]],
    returncode: int,
) -> tuple[str, str]:
    """Classify the run and build its message.

    An all-skipped run is reported as skipped, not failed. Skips mean the
    platform or workspace was unavailable, and vision.md is explicit that
    platform gaps degrade to skips -- so CI does not go red for missing
    credentials, while a real assertion failure still does.

    A non-zero exit with no test results at all -- no native output, or a
    total of zero -- means pql-test never connected to the model (most
    commonly a local Desktop session that closed). There is nothing to
    report as a finding, so this degrades to skipped the same way, instead
    of the misleading "0 tests, 0 passed, 0 failed, 0 skipped" failed
    message a bare fall-through would produce.

    A run can also have results -- pql-test discovers tests statically from
    the model's TMDL, so it reports a count of tests it never managed to
    run, each failing with the same connection-refused error rather than an
    assertion mismatch. Nothing executed, so that is reported as a warning
    with no tests: not `failed` (nothing asserted wrong), not `passed`
    (a green check over an empty run is how a developer comes to believe
    tests ran when they did not). Only when every failure shares that
    signature, though -- one genuine assertion failure among connection
    errors must still fail the run.
    """
    counts = test_summary or {}
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0)
    skipped = counts.get("skipped", 0)
    total = counts.get("total", 0)
    counter_msg = f"{total} tests, {passed} passed, {failed} failed, {skipped} skipped"

    # "Did anything run?" is asked before "did it pass?": zero tests passing
    # is not a pass, and a green check is how a developer comes to believe
    # tests ran when none did.
    if total == 0 and not findings:
        if returncode == 0:
            return "warning", "pql-test found no tests to run in this model"
        return "warning", "pql-test ran no tests"
    if returncode == 0 and not findings:
        return "passed", f"pql-test passed: {counter_msg}"
    all_skipped = (
        test_summary is not None and total > 0 and passed == 0 and failed == 0
        and skipped == total
    )
    if all_skipped:
        return "skipped", f"pql-test skipped: {counter_msg}"
    if _is_connection_skip(findings):
        return "warning", "pql-test ran no tests: could not connect to the model"
    return "failed", f"pql-test failed: {counter_msg}"


def _narrate_header(
    artifact_name: str, artifact_path: Path, output_path: Path, nat_out: Path
) -> None:
    """Print the per-artifact banner, unless verbosity is set to summary."""
    if _verbosity() < _VERBOSITY_LEVELS["default"]:
        return
    log("================================")
    log(f"pql-test -> {artifact_name}")
    log("================================")
    log(f"📋 Artifact: {artifact_path}")
    log(f"📊 Envelope: {output_path}")
    log(f"📄 Native:   {nat_out}")
    log("")


def _narrate_outcome(
    status: str,
    message: str,
    findings: list[dict[str, Any]],
    stderr: str,
) -> None:
    """Print the result lines, and the CI annotation when the run failed.

    The annotation goes to stderr regardless of verbosity: it is what a CI
    system reads, not what a person chose to see. A warning annotates as
    `::warning::` rather than `::error::` -- nothing asserted wrong, but
    nothing ran either, so it must not read as a clean pass.
    """
    level = _verbosity()
    icons = {"passed": "✅", "skipped": "⏭️", "warning": "⚠️"}
    if level >= _VERBOSITY_LEVELS["default"] and status in icons:
        log(f"{icons[status]} {message}")
    if status in {"passed", "skipped"}:
        return
    if status == "warning":
        print(f"::warning::{message}", file=sys.stderr)
        return
    if level >= _VERBOSITY_LEVELS["verbose"]:
        for f in findings:
            log(f"  • {f.get('suite_name') or '?'} :: {f.get('test_name') or '?'}")
    if stderr:
        print(f"::error::{stderr}", file=sys.stderr)
    print(f"::error::{message}", file=sys.stderr)


def run_pql_test(args: argparse.Namespace) -> int:
    """Run pql-test and return an exit code."""
    artifact_path = validate_path(args.artifact_path, "Artifact path")
    artifact_name = args.artifact_name or artifact_path.stem

    desktop_port_arg = getattr(args, "desktop_port", "")
    desktop_port = int(desktop_port_arg) if desktop_port_arg else None
    desktop_model_name = getattr(args, "desktop_model_name", "")

    _env_out = envelope_path("pql_test", artifact_path.stem)
    _nat_out = native_output_path("pql_test", artifact_path.stem, "json")
    output_path = Path(args.output_path) if args.output_path else _env_out
    nat_out = _nat_out

    level = _verbosity()
    _narrate_header(artifact_name, artifact_path, output_path, nat_out)

    command = build_command(
        artifact_path=artifact_path,
        output_path=nat_out,
        env=getattr(args, "env", ""),
        workspace_id=getattr(args, "workspace_id", ""),
    )
    nat_out.parent.mkdir(parents=True, exist_ok=True)
    pql_env = _pql_env()

    if level >= _VERBOSITY_LEVELS["debug"]:
        log(f"Executing: {' '.join(command)}")
        log("")

    command = _resolve_pql_command(command)

    with Timer() as timer:
        outcome = run_tool(
            command,
            timeout=300,
            label="pql-test",
            timeout_message="pql-test timed out after 5 minutes",
            missing_message="pql-test executable not found",
            env=pql_env,
        )
    if outcome.failed:
        write_results(
            WrapperResult(output_path, outcome.status, [], artifact_path, message=outcome.message, native_out=nat_out),
            desktop_port=desktop_port,
            desktop_model_name=desktop_model_name,
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

    # Prefer the native JSON output file; fall back to parsing stdout
    # (testing / older versions).
    findings, test_results, test_summary = _parse_native_output(nat_out)
    if findings is None:
        findings = parse_findings(proc.stdout or "")
        test_results = findings  # stdout fallback: same list

    # Reconstruct counters from the result list when the native file does not
    # include a summary block (older pql-test versions or mocked stdout).
    test_summary = test_summary or _summarize_results(test_results)
    status, message = _pql_status(test_summary, findings, proc.returncode)

    # pql-test's counts describe tests it discovered from the TMDL, not tests
    # it ran. When none of them executed, reporting any count overstates what
    # happened -- and the counts are what a reader believes, so they have to
    # agree with the status above. native.json keeps pql-test's own numbers.
    if _is_connection_skip(findings):
        test_results = []
        test_summary = dict(_NOTHING_RAN)

    # One call for every outcome: the branch below differs only in narration
    # and exit code. `findings if status == "failed" else []` covers both --
    # a passed or skipped run has nothing to report as a finding.
    write_results(
        WrapperResult(
            output_path,
            status,
            findings if status == "failed" else [],
            artifact_path,
            message=message,
            native_out=nat_out,
            duration_ms=timer.elapsed_ms,
            started_at=timer.started_at,
            test_summary=test_summary,
            test_results=test_results,
        ),
        desktop_port=desktop_port,
        desktop_model_name=desktop_model_name,
    )
    _narrate_outcome(status, message, findings, proc.stderr)
    # A warning exits 0 like pbir-a11y's: nothing asserted wrong, so a
    # platform gap does not turn CI red -- the annotation carries the news.
    if status in {"passed", "skipped", "warning"}:
        return 0
    return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run pql-test from Python"
    )
    parser.add_argument(
        "--artifact-path", required=True,
        help="Path to the semantic model artifact",
    )
    parser.add_argument(
        "--artifact-name", default="", help="Friendly artifact name",
    )
    parser.add_argument(
        "--output-path", default="", help="Path to write JSON results",
    )
    parser.add_argument(
        "--workspace-id", default="", help="Workspace identifier",
    )
    parser.add_argument(
        "--env", default="", help="Environment label (e.g. DEV, PROD, ANY)",
    )
    parser.add_argument(
        "--desktop-port", default="",
        help="Port of the Power BI Desktop instance this run is bound to (envelope-only)",
    )
    parser.add_argument(
        "--desktop-model-name", default="",
        help="Model name of the bound Desktop instance (envelope-only)",
    )
    args = parser.parse_args()
    raise SystemExit(run_pql_test(args))


if __name__ == "__main__":
    main()
