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
import subprocess
import sys
from pathlib import Path
from typing import Any

from ._analyzer_envelope import (
    Timer,
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
    output_path: Path,
    status: str,
    findings: list[dict[str, Any]],
    artifact_path: Path,
    test_results: "list[dict[str, Any]] | None" = None,
    message: str = "",
    native_out: "Path | None" = None,
    duration_ms: int = 0,
    test_summary: "dict[str, int] | None" = None,
    desktop_port: "int | None" = None,
    desktop_model_name: str = "",
) -> None:
    """Write standardized pql-test envelope JSON."""
    env = build_envelope(
        analyzer="pql_test",
        artifact_path=str(artifact_path),
        status=status,
        message=message,
        findings=findings,
        native_output_path_str=str(native_out) if native_out else "",
        duration_ms=duration_ms,
    )
    env["test_results"] = test_results or []
    if test_summary is not None:
        env["test_summary"] = test_summary
    if desktop_port is not None:
        env["desktop"] = {"port": desktop_port, "model_name": desktop_model_name}
    # pql-test emits JSON only, so the readable report is rendered from the
    # envelope. No-op unless --report was passed.
    attach_report(env, output_path)
    write_envelope(output_path, env)


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
    if level >= _VERBOSITY_LEVELS["default"]:
        log("================================")
        log(f"pql-test -> {artifact_name}")
        log("================================")
        log(f"📋 Artifact: {artifact_path}")
        log(f"📊 Envelope: {output_path}")
        log(f"📄 Native:   {nat_out}")
        log("")

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

    executable = shutil.which(command[0])
    if not executable:
        # Also check the repo's local .venv (Scripts on Windows, bin on Unix).
        # Use cwd/repo root rather than the installed package location so the
        # fallback works whether fab-test is run from source or a wheel.
        _repo_root = Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve()
        for venv_subdir in ("Scripts", "bin"):
            candidate = _repo_root / ".venv" / venv_subdir / command[0]
            if sys.platform == "win32" and not candidate.suffix:
                candidate = candidate.with_suffix(".exe")
            if candidate.exists():
                executable = str(candidate)
                break
    if executable:
        command[0] = executable
    elif command[0] == "pql-test":
        command = [sys.executable, "-m", "pql_test", *command[1:]]
    else:
        command = [command[0], *command[1:]]

    with Timer() as timer:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                env=pql_env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            message = "pql-test timed out after 5 minutes"
            write_results(
                output_path, "timeout", [], artifact_path,
                message=message, native_out=nat_out,
                desktop_port=desktop_port, desktop_model_name=desktop_model_name,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except FileNotFoundError:
            message = "pql-test executable not found"
            write_results(
                output_path, "error", [], artifact_path,
                message=message, native_out=nat_out,
                desktop_port=desktop_port, desktop_model_name=desktop_model_name,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - wrapper boundary: failures become an error envelope
            message = f"Unexpected error running pql-test: {exc}"
            write_results(
                output_path, "error", [], artifact_path,
                message=message, native_out=nat_out,
                desktop_port=desktop_port, desktop_model_name=desktop_model_name,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1

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
    if test_summary is None and test_results:
        total = len(test_results)
        passed = sum(1 for r in test_results if isinstance(r, dict) and r.get("passed"))
        skipped = sum(
            1
            for r in test_results
            if isinstance(r, dict) and _is_pql_test_skipped(r)
        )
        failed = total - passed - skipped
        test_summary = {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": total,
        }

    passed = test_summary.get("passed", 0) if test_summary else 0
    failed = test_summary.get("failed", 0) if test_summary else 0
    skipped = test_summary.get("skipped", 0) if test_summary else 0
    total = test_summary.get("total", 0) if test_summary else 0

    counter_msg = f"{total} tests, {passed} passed, {failed} failed, {skipped} skipped"

    # Skipped tests are not failures when the underlying platform/workspace is
    # unavailable (vision §2.7: "platform gaps degrade to skips"). Treat an
    # all-skipped run as a skipped analyzer so CI does not fail for missing
    # credentials, while still failing on actual assertion failures.
    all_skipped = (
        test_summary is not None
        and total > 0
        and passed == 0
        and failed == 0
        and skipped == total
    )

    success = proc.returncode == 0 and not findings

    if success:
        status = "passed"
        message = f"pql-test passed: {counter_msg}"
    elif all_skipped:
        status = "skipped"
        message = f"pql-test skipped: {counter_msg}"
    else:
        status = "failed"
        message = f"pql-test failed: {counter_msg}"

    if status in {"passed", "skipped"}:
        write_results(
            output_path,
            status,
            findings if status == "failed" else [],
            artifact_path,
            test_results=test_results,
            test_summary=test_summary,
            message=message,
            native_out=nat_out,
            duration_ms=timer.elapsed_ms,
            desktop_port=desktop_port,
            desktop_model_name=desktop_model_name,
        )
        if level >= _VERBOSITY_LEVELS["default"]:
            icon = "✅" if status == "passed" else "⏭️"
            log(f"{icon} {message}")
            log(f"📁 Envelope: {output_path}")
            log(f"📄 Native:   {nat_out}")
        return 0

    write_results(
        output_path,
        status,
        findings,
        artifact_path,
        test_results=test_results,
        test_summary=test_summary,
        message=message,
        native_out=nat_out,
        duration_ms=timer.elapsed_ms,
        desktop_port=desktop_port,
        desktop_model_name=desktop_model_name,
    )
    if level >= _VERBOSITY_LEVELS["default"]:
        log(f"📁 Envelope: {output_path}")
        log(f"📄 Native:   {nat_out}")
    if level >= _VERBOSITY_LEVELS["verbose"]:
        for f in findings:
            suite = f.get("suite_name") or "?"
            test = f.get("test_name") or "?"
            log(f"  • {suite} :: {test}")
    if proc.stderr:
        print(f"::error::{proc.stderr}", file=sys.stderr)
    print(f"::error::{message}", file=sys.stderr)
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
