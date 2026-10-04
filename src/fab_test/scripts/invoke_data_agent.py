#!/usr/bin/env python3
"""Invoke promptfoo against a Fabric Data Agent artifact."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from ._analyzer_envelope import EnvelopeIdentity, Timer, build_envelope, write_envelope
from ._credentials import (
    IncompleteServicePrincipalError,
    _parse_env_file,
    _resolve_env_path,
    resolve_service_principal,
)
from ._data_agent_resolution import resolve_data_agent_url
from ._report_html import attach_report
from ._service_export import build_service_client

_SUITE_FALLBACK = "Data Agent"


def _native_output(output_path: Path) -> Path:
    return output_path.with_name("native.json")


def _generated_config(output_path: Path) -> Path:
    return output_path.with_name("promptfooconfig.effective.yaml")


def _status(test_results: list[dict[str, Any]]) -> tuple[str, str]:
    total = len(test_results)
    failed = sum(1 for row in test_results if not row.get("passed", False))
    if total == 0:
        return "warning", "promptfoo ran no tests"
    if failed:
        return "failed", f"promptfoo failed: {failed} of {total} tests failed"
    return "passed", f"promptfoo passed: {total} tests"


def generate_effective_config(
    *,
    artifact_path: Path,
    output_path: Path,
    provider_path: Path,
    agent_url: str,
) -> Path:
    """Write the promptfoo config fab-test actually runs."""
    authored = artifact_path / "promptfooconfig.yaml"
    data = yaml.safe_load(authored.read_text(encoding="utf-8")) or {}
    providers = data.get("providers") or []
    configured_urls = (((providers[0] if providers else {}).get("config") or {}).get("fabric_urls") or {})
    merged_urls = {"agent1": agent_url, **configured_urls}
    data["providers"] = [
        {
            "id": f"file://{provider_path}",
            "config": {
                "base_url": agent_url,
                "fabric_urls": merged_urls,
                "timeout": 60,
                "max_retries": 1,
                "retry_delay": 2,
            },
        }
    ]
    data["evaluateOptions"] = {**(data.get("evaluateOptions") or {}), "maxConcurrency": 1}
    data["commandLineOptions"] = {**(data.get("commandLineOptions") or {}), "workers": 1}
    generated = _generated_config(output_path)
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return generated


def map_promptfoo_results(
    result_path: Path, *, suite_name: str = _SUITE_FALLBACK
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Map promptfoo JSON results to fab-test findings and test_results."""
    data = json.loads(result_path.read_text(encoding="utf-8"))
    rows = ((data.get("results") or {}).get("results") or [])
    findings: list[dict[str, Any]] = []
    test_results: list[dict[str, Any]] = []
    for row in rows:
        description = str(row.get("description") or row.get("test") or "unnamed promptfoo test")
        passed = bool(row.get("success"))
        response = (row.get("response") or {}).get("output") or ""
        components = ((row.get("gradingResult") or {}).get("componentResults") or [])
        failure_reason = next(
            (
                component.get("reason")
                or f"{(component.get('assertion') or {}).get('type', 'assertion')} failed"
                for component in components
                if not component.get("pass", False)
            ),
            "",
        )
        if not passed and not failure_reason:
            failure_reason = response or "assertion failed"
        test_results.append(
            {
                "suite_name": suite_name,
                "test_name": description,
                "expected": "all assertions pass",
                "actual": response or failure_reason,
                "passed": passed,
                "status": "pass" if passed else "fail",
            }
        )
        if not passed:
            findings.append(
                {
                    "rule": "promptfoo_assertion_failed",
                    "severity": "error",
                    "object": description,
                    "message": str(failure_reason),
                }
            )
    return findings, test_results, str(data.get("outputPath") or "")


def _write_envelope(
    output_path: Path,
    *,
    artifact_path: Path,
    status: str,
    message: str,
    timer: Timer,
    payload: dict[str, Any] | None = None,
) -> None:
    payload = payload or {}
    native_output_path = payload.get("native_output_path")
    envelope = build_envelope(
        EnvelopeIdentity("data_agent", str(artifact_path)),
        status=status,
        message=message,
        findings=payload.get("findings") or [],
        native_output_path_str=str(native_output_path) if native_output_path else "",
        native_html_output_path_str=str(payload.get("native_html_output_path") or ""),
        started_at=timer.started_at,
        duration_ms=timer.elapsed_ms,
    )
    test_results = payload.get("test_results")
    if test_results is not None:
        envelope["test_results"] = test_results
    attach_report(envelope, output_path)
    write_envelope(output_path, envelope)


def _provider_env(principal, env_file: str | None) -> dict[str, str]:
    env = {**os.environ}
    if env_file:
        resolved = _resolve_env_path(env_file)
        if resolved.exists():
            env.update(_parse_env_file(resolved))
    env["FABRIC_TENANT_ID"] = principal.tenant_id
    env["FABRIC_CLIENT_ID"] = principal.client_id
    env["FABRIC_CLIENT_SECRET"] = principal.client_secret
    return env


def run_promptfoo_eval(
    promptfoo_path: str,
    config_path: Path,
    output_path: Path,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run promptfoo eval and capture its JSON output file."""
    executable = Path(promptfoo_path)
    if executable.suffix == ".js":
        command = [
            "node",
            str(executable),
            "eval",
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ]
    else:
        command = [str(executable), "eval", "--config", str(config_path), "--output", str(output_path)]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def _resolve_promptfoo_path(raw: str) -> str:
    if raw:
        return raw
    if os.environ.get("PROMPTFOO_PATH", "").strip():
        return os.environ["PROMPTFOO_PATH"].strip()
    found = shutil.which("promptfoo")
    if found:
        return found
    raise RuntimeError("promptfoo not found. Set PROMPTFOO_PATH or run `fab-test doctor --analyzer data_agent`.")


def _service_principal_error() -> str:
    return (
        "Data Agent evaluation needs FABRIC_TENANT_ID, FABRIC_CLIENT_ID, and "
        "FABRIC_CLIENT_SECRET. Run `fab-test auth status` to inspect the resolved "
        "credential chain."
    )


def _resolve_agent_url(args: argparse.Namespace) -> str:
    client = build_service_client(args)
    return resolve_data_agent_url(client, args.workspace_id, args.artifact_name)


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--promptfoo-path", default="")
    parser.add_argument("--env-file", dest="data_agent_env_file", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    artifact_path = Path(args.artifact_path).resolve()
    output_path = Path(args.output_path).resolve()
    promptfoo_config = artifact_path / "promptfooconfig.yaml"
    with Timer() as timer:
        if not promptfoo_config.exists():
            _write_envelope(
                output_path,
                artifact_path=artifact_path,
                status="skipped",
                message="No promptfooconfig.yaml found in this .DataAgent artifact. Run `fab-test data-agent init`.",
                timer=timer,
            )
            return 0
        try:
            principal = resolve_service_principal(getattr(args, "data_agent_env_file", None))
        except IncompleteServicePrincipalError as exc:
            _write_envelope(
                output_path,
                artifact_path=artifact_path,
                status="error",
                message=f"{exc}. Run `fab-test auth status`.",
                timer=timer,
            )
            return 127
        if principal is None:
            _write_envelope(
                output_path,
                artifact_path=artifact_path,
                status="error",
                message=_service_principal_error(),
                timer=timer,
            )
            return 127
        try:
            promptfoo_path = _resolve_promptfoo_path(args.promptfoo_path)
            agent_url = _resolve_agent_url(args)
            config_path = generate_effective_config(
                artifact_path=artifact_path,
                output_path=output_path,
                provider_path=Path(__file__).with_name("fabric_data_agent_provider.py"),
                agent_url=agent_url,
            )
            native_output = _native_output(output_path)
            proc = run_promptfoo_eval(
                promptfoo_path,
                config_path,
                native_output,
                env=_provider_env(principal, getattr(args, "data_agent_env_file", None)),
            )
            if proc.returncode in (0, 1):
                findings, test_results, html_path = map_promptfoo_results(
                    native_output, suite_name=args.artifact_name
                )
                status, message = _status(test_results)
                _write_envelope(
                    output_path,
                    artifact_path=artifact_path,
                    status=status,
                    message=message,
                    timer=timer,
                    payload={
                        "native_output_path": native_output,
                        "native_html_output_path": html_path,
                        "findings": findings,
                        "test_results": test_results,
                    },
                )
                result = 1 if findings else 0
            else:
                message = (proc.stderr or proc.stdout or "promptfoo crashed").strip()
                _write_envelope(
                    output_path,
                    artifact_path=artifact_path,
                    status="error",
                    message=message,
                    timer=timer,
                    payload={
                        "native_output_path": native_output if native_output.exists() else None,
                    },
                )
                result = 1
        except Exception as exc:  # noqa: BLE001 - wrapper must produce an envelope on any failure
            _write_envelope(
                output_path,
                artifact_path=artifact_path,
                status="error",
                message=str(exc),
                timer=timer,
            )
            return 1
        else:
            return result


if __name__ == "__main__":
    sys.exit(main())
