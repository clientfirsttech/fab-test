"""Run promptfoo against deployed Data Agents and persist redacted, standard results."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ._analyzer_envelope import EnvelopeIdentity, Timer, build_envelope, envelope_path, write_envelope
from ._credentials import (
    IncompleteServicePrincipalError,
    ServicePrincipal,
    redact_secrets,
    resolve_service_principal,
)
from ._data_agent_progress import Progress, show_verdicts, terminal
from ._data_agent_suite import effective_config, load_suite
from ._report_html import attach_report
from ._results_stem import results_stem
from .fabric_data_agent_provider import PROGRESS_VAR

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_KEYS = frozenset({"access_token", "client_secret", "clientsecret", "authorization", "password"})
# Every service-principal spelling fab-test reads, plus the Azure SDK's secret variables.
_WORKER_HIDDEN_VARS = frozenset({
    "FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
    "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET",
    "AZURE_CLIENT_SECRET", "AZURE_CLIENT_CERTIFICATE_PASSWORD", "AZURE_PASSWORD",
})
CREDENTIAL_REMEDIATION = (
    "Data Agent tests need a full service principal. Set FABRIC_TENANT_ID, FABRIC_CLIENT_ID "
    "(or FABRIC_SERVICE_PRINCIPAL_ID), and FABRIC_CLIENT_SECRET (or FABRIC_SERVICE_PRINCIPAL_SECRET), "
    "or pass --env-file. Run `fab-test auth status` to see what is set."
)


class ResultError(ValueError):
    """promptfoo did not produce a valid evaluation result."""


def credential_principal(env_file: str | None) -> ServicePrincipal:
    """Require a service principal without acquiring a token."""
    principal = resolve_service_principal(env_file)
    if principal is None:
        raise IncompleteServicePrincipalError(CREDENTIAL_REMEDIATION)
    return principal


def credential_secret(env_file: str | None) -> str:
    """The preflight: a complete service principal is configured. Returns its secret for redaction."""
    return credential_principal(env_file).client_secret


def _promptfoo_env(principal: ServicePrincipal, private_dir: Path) -> dict[str, str]:
    """promptfoo's environment, with the service principal moved into a private file (decision 19).

    A suite can template ``{{ env.* }}`` and run JavaScript assertions, so the secret stays out of
    the environment those see. The provider reads the principal the preflight resolved from the
    file, which lives in the run's private temporary directory and is deleted with it. This is
    defense in depth, not a sandbox: a hostile suite can still read the file. Suites are code.
    """
    credentials = private_dir / "service-principal.env"
    credentials.write_text(
        f"FABRIC_TENANT_ID={principal.tenant_id}\nFABRIC_CLIENT_ID={principal.client_id}\n"
        f"FABRIC_CLIENT_SECRET={principal.client_secret}\n",
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if key.upper() not in _WORKER_HIDDEN_VARS}
    return {**env, "PROMPTFOO_PYTHON": sys.executable, "PROMPTFOO_DISABLE_TELEMETRY": "1",
            "PROMPTFOO_CONFIG_DIR": str(private_dir), "PLAYWRIGHT_ENV_FILE": str(credentials),
            PROGRESS_VAR: str(private_dir / "progress.jsonl")}


def _terminal():  # a text stream or None; the seam tests replace
    return terminal()


def redact(value: Any, secret: str = "") -> Any:
    """Redact credential values and bearer tokens recursively before writing or printing."""
    if isinstance(value, dict):
        return {key: "<redacted>" if str(key).lower() in _SECRET_KEYS else redact(item, secret)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secret) for item in value]
    if isinstance(value, str):
        text = redact_secrets(value)
        if secret:
            text = text.replace(secret, "<redacted>")
        return _BEARER.sub("Bearer <redacted>", text)
    return value


def promptfoo_command(path: Path) -> list[str]:
    """Invoke the resolved npm entry point with Node, without a Windows shell shim."""
    node = shutil.which("node")
    if node is None:
        raise FileNotFoundError("promptfoo needs Node.js >=22.22.0. Install Node.js, then run `fab-test doctor`.")
    if not path.is_file():
        raise FileNotFoundError(
            f"promptfoo entry point not found: {path}. Set PROMPTFOO_PATH or run `fab-test doctor`."
        )
    return [node, str(path.resolve())]


def map_results(document: dict[str, Any], suite: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map promptfoo verdicts to error findings and the full suite/test result list."""
    if not isinstance(document, dict):
        raise ResultError("promptfoo output must be a JSON object containing test results.")
    container = document.get("results")
    rows = container.get("results") if isinstance(container, dict) else container
    if not isinstance(rows, list) or not rows:
        raise ResultError("promptfoo produced no test results; check the suite and promptfoo diagnostics.")
    findings, results = [], []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not isinstance(row.get("success", row.get("pass")), bool):
            raise ResultError("promptfoo produced a result without a boolean success/pass verdict.")
        case = row.get("testCase") or {}
        grading = row.get("gradingResult") or {}
        response = row.get("response") or {}
        if not all(isinstance(field, dict) for field in (case, grading, response)):
            raise ResultError("promptfoo testCase, gradingResult and response must be objects.")
        if row.get("failureReason") == 2 or response.get("error"):
            error = row.get("error") or response.get("error") or "unknown error"
            raise ResultError(f"promptfoo provider error: {error}")
        components = grading.get("componentResults") or []
        if not isinstance(components, list) or any(
            not isinstance(c, dict) or (c.get("assertion") is not None and not isinstance(c["assertion"], dict))
            for c in components
        ):
            raise ResultError("promptfoo componentResults must be assertion result objects.")
        failed_components = [c for c in components if c.get("pass") is False]
        passed = row.get("success", row.get("pass")) and not failed_components
        name = str(case.get("description") or row.get("description") or f"Test {index}")
        actual = response.get("output", response.get("error", ""))
        expected = json.dumps(case.get("assert", []), ensure_ascii=True)
        results.append({"suite_name": suite, "test_name": name, "passed": passed,
                        "expected": expected, "actual": str(actual)})
        if not passed:
            failures = failed_components or [{"reason": row.get("error") or grading.get("reason")
                                              or "Agent answer failed the authored assertion; check this test."}]
            findings.extend({
                "rule": str((c.get("assertion") or {}).get("type") or "data_agent_assertion"),
                "severity": "error", "object": name, "message": str(c.get("reason") or "Assertion failed"),
            } for c in failures)
    return findings, results


def _absolute_references(value: Any, root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _absolute_references(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_absolute_references(item, root) for item in value]
    if isinstance(value, str) and value.startswith("file://"):
        path = Path(value.removeprefix("file://"))
        if not path.is_absolute():
            return f"file://{(root / path).resolve().as_posix()}"
    return value


def _evaluate(args: argparse.Namespace, folder: Path, principal: ServicePrincipal, out=None) -> dict[str, Any]:
    secret = principal.client_secret
    suite = Path(args.tests).resolve()
    config = _absolute_references(effective_config(load_suite(suite), args.base_url), suite.parent)
    effective = folder / "effective.promptfoo.yaml"
    effective.write_text(yaml.safe_dump(redact(config, secret), sort_keys=False), encoding="utf-8")
    # promptfoo's raw output may contain answers that echo credentials; it is never a published artifact.
    # mkdtemp: owner-only on POSIX, the user's profile on Windows; deleted with everything in it.
    with tempfile.TemporaryDirectory(prefix="fab-test-data-agent-") as temporary:
        env = _promptfoo_env(principal, Path(temporary))
        native = Path(temporary) / "results.json"
        command = [*promptfoo_command(Path(args.promptfoo_path)), "eval",
                   "--config", str(effective), "--output", str(native), "--no-cache", "--no-write", "--no-share"]
        item = Path(args.artifact_path).name.removesuffix(".DataAgent")
        with Progress(out, Path(env[PROGRESS_VAR]), len(config.get("tests") or []), item):
            proc = subprocess.run(command, cwd=suite.parent, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=args.timeout, check=False)
        if proc.returncode not in (0, 100):
            raise RuntimeError(f"promptfoo eval exited {proc.returncode}: {proc.stderr or proc.stdout}")
        if not native.is_file():
            raise RuntimeError("promptfoo eval produced no results.json; check the suite and promptfoo installation.")
        data = redact(json.loads(native.read_text(encoding="utf-8-sig")), secret)
        (folder / "native.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def run_data_agent(args: argparse.Namespace) -> int:
    """Evaluate one paired suite, writing an envelope even for prerequisite or tool failures."""
    artifact = Path(args.artifact_path)
    output = (Path(args.output_path).resolve() if args.output_path
              else envelope_path("data_agent", results_stem(artifact)))
    output.parent.mkdir(parents=True, exist_ok=True)
    native = output.parent / "native.json"
    native.unlink(missing_ok=True)
    status, message, findings, results, code, secret = "passed", "Data Agent tests passed", [], None, 0, ""
    out = _terminal()
    with Timer() as timer, contextlib.closing(out) if out is not None else contextlib.nullcontext():
        try:
            if not args.tests:
                status = "skipped"
                message = f"No paired suite. Run `fab-test data-agent tests init {artifact}`."
            else:
                principal = credential_principal(args.env_file)
                secret = principal.client_secret
                data = _evaluate(args, output.parent, principal, out)
                findings, results = map_results(data, Path(args.tests).name)
                show_verdicts(out, redact(results, secret), redact(findings, secret))
                if findings:
                    status, message, code = "failed", f"Data Agent tests found {len(findings)} failed assertion(s)", 1
        except IncompleteServicePrincipalError as exc:
            detail = str(exc) if CREDENTIAL_REMEDIATION in str(exc) else f"{exc} {CREDENTIAL_REMEDIATION}"
            status, message, code = "error", detail, 127
        except FileNotFoundError as exc:
            status, message, code = "error", str(exc), 127
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            status, message, code = "error", str(exc), 1
    envelope = build_envelope(
        EnvelopeIdentity("data_agent", str(artifact)), status=status, message=redact(message, secret),
        findings=redact(findings, secret), duration_ms=timer.elapsed_ms, started_at=timer.started_at,
        native_output_path_str=str(native) if native.is_file() else "",
    )
    if results is not None:
        envelope["test_results"] = redact(results, secret)
    attach_report(envelope, output)
    write_envelope(output, envelope)
    if code:
        print(envelope["message"], file=sys.stderr)
    elif os.getenv("ANALYZER_VERBOSITY", "default") != "summary":
        stream = sys.stderr if os.getenv("ANALYZER_OUTPUT_MODE") == "json" else sys.stdout
        print(f"{message}\nEnvelope: {output}", file=stream)
    return code


def main() -> int:
    """The per-artifact wrapper entry point used by fab-test's command builder."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--tests", default=None)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--promptfoo-path", default=os.getenv("PROMPTFOO_PATH", ""))
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--output-path", default="")
    parser.add_argument("--timeout", type=float, default=300)
    return run_data_agent(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
