#!/usr/bin/env python3
"""Invoke pqlint against a semantic-model artifact.

The wrapper is intentionally local-first: it accepts the artifact path and writes
standardized JSON results so it can be exercised by pytest without requiring a
subscription key or remote service.
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

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}


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


def build_command(artifact_path: Path, output_path: Path) -> list[str]:
    """Build the pqlint command."""
    return ["pqlint", str(artifact_path), "--output", str(output_path)]


def parse_findings(raw_text: str) -> list[dict[str, Any]]:
    """Parse pqlint JSON output into a list of findings."""
    if not raw_text.strip():
        return []

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed

    if isinstance(parsed, dict):
        for key in ("findings", "results"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value

    return []


def write_results(
    output_path: Path,
    status: str,
    findings: list[dict[str, Any]],
    artifact_path: Path,
    message: str = "",
    native_out: "Path | None" = None,
    duration_ms: int = 0,
) -> None:
    """Write standardized pqlint envelope JSON."""
    env = build_envelope(
        analyzer="pqlint",
        artifact_path=str(artifact_path),
        status=status,
        message=message,
        findings=findings,
        native_output_path_str=str(native_out) if native_out else "",
        duration_ms=duration_ms,
    )
    write_envelope(output_path, env)


def run_pqlint(args: argparse.Namespace) -> int:
    """Run pqlint and return an exit code."""
    artifact_path = validate_path(args.artifact_path, "Artifact path")

    _env_out = envelope_path("pqlint", artifact_path.stem)
    _nat_out = native_output_path("pqlint", artifact_path.stem, "json")
    output_path = Path(args.output_path) if args.output_path else _env_out
    nat_out = _nat_out

    level = _verbosity()
    if level >= _VERBOSITY_LEVELS["default"]:
        log("================================")
        log(f"pqlint  →  {artifact_path.stem}")
        log("================================")
        log(f"📋 Artifact: {artifact_path}")
        log(f"📊 Envelope: {output_path}")
        log(f"📄 Native:   {nat_out}")
        log("")

    command = build_command(artifact_path=artifact_path, output_path=nat_out)
    if level >= _VERBOSITY_LEVELS["debug"]:
        log(f"Executing: {' '.join(command)}")
        log("")

    executable = shutil.which(command[0])
    if not executable and command[0] == "pqlint":
        command = [sys.executable, "-m", "pqlint", *command[1:]]

    with Timer() as timer:
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        except subprocess.TimeoutExpired:
            message = "pqlint timed out after 5 minutes"
            write_results(output_path, "timeout", [], artifact_path, message=message, native_out=nat_out)
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except FileNotFoundError:
            message = "pqlint executable not found"
            write_results(output_path, "error", [], artifact_path, message=message, native_out=nat_out)
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - wrapper boundary: failures become an error envelope
            message = f"Unexpected error running pqlint: {exc}"
            write_results(output_path, "error", [], artifact_path, message=message, native_out=nat_out)
            print(f"::error::{message}", file=sys.stderr)
            return 1

    if level >= _VERBOSITY_LEVELS["debug"] and (proc.stdout or proc.stderr):
        log("--- stdout ---")
        log(proc.stdout or "(empty)")
        log("--- stderr ---")
        log(proc.stderr or "(empty)")
        log("")

    findings = parse_findings(proc.stdout or "")
    success = proc.returncode == 0 and not findings

    if success:
        message = "pqlint passed with no findings"
        write_results(
            output_path, "passed", [], artifact_path,
            message=message, native_out=nat_out, duration_ms=timer.elapsed_ms,
        )
        if level >= _VERBOSITY_LEVELS["default"]:
            log(f"✅ {message}")
            log(f"📁 Envelope: {output_path}")
        return 0

    message = f"pqlint found {len(findings)} finding(s)"
    write_results(
        output_path, "failed", findings, artifact_path,
        message=message, native_out=nat_out, duration_ms=timer.elapsed_ms,
    )
    if level >= _VERBOSITY_LEVELS["default"]:
        log(f"📁 Envelope: {output_path}")
    if level >= _VERBOSITY_LEVELS["verbose"]:
        for f in findings:
            rule = f.get("rule") or "?"
            sev = f.get("severity") or ""
            log(f"  • {rule}  sev={sev}")
    if proc.stderr:
        print(f"::error::{proc.stderr}", file=sys.stderr)
    print(f"::error::{message}", file=sys.stderr)
    return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run pqlint from Python")
    parser.add_argument("--artifact-path", required=True, help="Path to the artifact")
    parser.add_argument("--output-path", default="", help="Path to write JSON results")
    parser.add_argument("--subscription-key", default="", help="Optional subscription key")
    args = parser.parse_args()
    raise SystemExit(run_pqlint(args))


if __name__ == "__main__":
    main()
