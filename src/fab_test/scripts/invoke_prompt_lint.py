#!/usr/bin/env python3
"""Simple prompt-lint wrapper for Agent artifacts.

The wrapper validates a small set of prompt-contract rules locally and emits a
standard result envelope so it can be exercised without any external service.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from ._analyzer_envelope import (
    EnvelopeIdentity,
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


def validate_prompt_file(path: Path) -> list[dict[str, Any]]:
    """Perform deterministic prompt-lint checks."""
    findings: list[dict[str, Any]] = []
    if not path.is_file():
        findings.append({"rule": "prompt_file_missing", "message": f"Prompt file not found: {path}"})
        return findings

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        findings.append({"rule": "empty_prompt", "message": "Prompt file is empty"})

    if "{{" in text and "}}" in text:
        findings.append({
            "rule": "template_placeholders",
            "message": "Prompt contains unresolved template placeholders",
        })

    return findings


def write_results(
    output_path: Path,
    status: str,
    findings: list[dict[str, Any]],
    artifact_path: Path,
    message: str = "",
    native_out: "Path | None" = None,
    duration_ms: int = 0,
) -> None:
    """Write standardized prompt-lint envelope JSON."""
    env = build_envelope(
        EnvelopeIdentity("prompt_lint", str(artifact_path)),
        status=status,
        message=message,
        findings=findings,
        native_output_path_str=str(native_out) if native_out else "",
        duration_ms=duration_ms,
    )
    write_envelope(output_path, env)


def run_prompt_lint(args: argparse.Namespace) -> int:
    """Run prompt linting and return an exit code."""
    artifact_path = validate_path(args.artifact_path, "Artifact path")

    _env_out = envelope_path("prompt_lint", artifact_path.stem)
    output_path = Path(args.output_path) if args.output_path else _env_out
    nat_out = native_output_path("prompt_lint", artifact_path.stem, "json", beside=output_path)

    level = _verbosity()
    if level >= _VERBOSITY_LEVELS["default"]:
        log(f"📋 prompt_lint  →  {artifact_path.stem}")

    with Timer() as timer:
        findings = validate_prompt_file(artifact_path)
    success = not findings

    if success:
        message = "Prompt lint passed"
        write_results(
            output_path, "passed", [], artifact_path,
            message=message, native_out=nat_out, duration_ms=timer.elapsed_ms,
        )
        log(f"✅ {message}")
        log(f"📁 Envelope: {output_path}")
        return 0

    message = f"Prompt lint found {len(findings)} finding(s)"
    write_results(
        output_path, "failed", findings, artifact_path,
        message=message, native_out=nat_out, duration_ms=timer.elapsed_ms,
    )
    if level >= _VERBOSITY_LEVELS["verbose"]:
        for f in findings:
            log(f"  • {f.get('rule', '?')}: {f.get('message', '')}")
    print(f"::error::{message}", file=sys.stderr)
    return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run prompt lint from Python")
    parser.add_argument("--artifact-path", required=True, help="Path to the prompt artifact")
    parser.add_argument("--output-path", default="", help="Path to write JSON results")
    args = parser.parse_args()
    raise SystemExit(run_prompt_lint(args))


if __name__ == "__main__":
    main()
