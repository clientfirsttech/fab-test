"""Invoke Playwright visual validation for Power BI reports.

Python-only wrapper that aligns with the project vision (§2.6). It reads a static
``.env`` configuration, generates one test case per ``report x page x bookmark``
combination, fetches an embed token and embed URL, and runs a pytest-playwright
spec that fails the pipeline if any visual-load error is detected.

Usage:
    python invoke_playwright.py \
        --env-file .env \
        --output-path ./analyzer-results/playwright/envelope.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ._analyzer_envelope import (
    Timer,
    build_envelope,
    envelope_path,
    write_envelope,
)
from ._report_html import attach_report
from .playwright_validation.config import PlaywrightValidationConfig, load_config
from .playwright_validation.embed_config import build_embed_config
from .playwright_validation.fabric_service_client import (
    build_fabric_service_client,
)
from .playwright_validation.power_bi_api import PowerBiApiError, get_embed_context
from .playwright_validation.resolver import (
    ResolvedReport,
    ServiceResolutionError,
    resolve_environment,
    resolve_report,
)
from .playwright_validation.test_cases import (
    TestCase,
    generate_test_cases,
    sanitize_case_id,
    write_test_cases,
)

# Evidence files the pytest spec writes per case (`_write_evidence`),
# labeled the way they should read as links in the report/JSON output.
_EVIDENCE_FILENAMES = {
    "screenshot": "screenshot.png",
    "console": "console.json",
    "network": "network.json",
}

# Relative path from repo root to the pytest spec.
_SPEC_PATH = Path("tests") / "test_playwright_visual.py"

# Default output location for test-case CSV/JSON artifacts.
_DEFAULT_TEST_CASES_DIR = Path("analyzer-results") / "playwright" / "test-cases"


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message."""
    print(message)


def log_error(message: str) -> None:
    """Print an error annotation to stderr.

    Every other analyzer wrapper already sends `::error::` to stderr; this
    one sent it to stdout, and the difference was not cosmetic. fab-test
    inherits a child's stdout under `--format text`, so an abort that wrote
    no envelope left `run.json` reporting `"status": "failed"` with
    `"detail": null` -- of vision's three callers, the agent was the one
    told that the run failed and not why. stderr is piped in every format,
    so the message reaches the manifest from here.
    """
    print(f"::error::{message}", file=sys.stderr)


def _repo_root() -> Path:
    """Return the repository root."""
    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    return Path.cwd().resolve()


def _write_findings(
    cases: list[TestCase],
    success: bool,
    message: str,
) -> list[dict[str, Any]]:
    """Build analyzer findings from the test-case list and overall result."""
    if success:
        return []

    return [
        {
            "rule": "visual_load_failed",
            "severity": "error",
            "object": case.test_case,
            "message": message,
        }
        for case in cases
    ]


def _case_result_dir(case: TestCase, test_cases_dir: Path) -> Path:
    """Return the directory the pytest spec wrote one case's evidence to.

    Must sanitize the id exactly the way ``tests/test_playwright_visual.py``
    does, via the same shared ``sanitize_case_id`` -- otherwise this looks
    in a directory the spec never wrote to.
    """
    return test_cases_dir / sanitize_case_id(case.test_case)


def _read_case_result(result_dir: Path) -> dict[str, str]:
    """Read one case's actual outcome, tolerating a run where it was never
    written (the pytest process crashed before reaching that case)."""
    result_path = result_dir / "result.json"
    if not result_path.is_file():
        return {}
    try:
        return json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _case_evidence(result_dir: Path) -> dict[str, str]:
    """Return ``{label: path}`` for whichever evidence files exist for this case."""
    return {
        label: str(result_dir / filename)
        for label, filename in _EVIDENCE_FILENAMES.items()
        if (result_dir / filename).is_file()
    }


def _test_results_rows(
    cases: list[TestCase],
    test_cases_dir: Path,
    *,
    overall_success: bool,
) -> list[dict[str, Any]]:
    """One row per generated case, using its own result.json when the spec wrote one.

    A case with no result.json (the pytest process never reached it, e.g.
    a crash on an earlier case) falls back to the run's overall outcome
    rather than reporting nothing -- the same "never silently drop a row"
    contract `test_results` already has for BPA and PBIR.
    """
    rows = []
    for case in cases:
        result_dir = _case_result_dir(case, test_cases_dir)
        result = _read_case_result(result_dir)
        status = result.get("status") or ("pass" if overall_success else "error")
        error = result.get("error", "")
        rows.append(
            {
                "suite_name": case.report_name,
                "test_name": case.test_case,
                "expected": "rendered",
                "actual": error or "rendered",
                "status": status,
                "evidence": _case_evidence(result_dir),
            }
        )
    return rows


def _findings_from_test_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the cases that actually failed, each with its own real error --
    replaces the old blanket "every case failed identically" findings."""
    return [
        {
            "rule": "visual_load_failed",
            "severity": "error",
            "object": row["test_name"],
            "message": row["actual"],
        }
        for row in rows
        if row["status"] != "pass"
    ]


def _write_playwright_envelope(output_path: Path, env: dict[str, Any]) -> None:
    """Attach a report (no-op unless `--report`) and write the envelope.

    The single funnel both `_run_single_report` and
    `_write_embed_error_envelope` write through, so neither call site can
    forget the report the way a direct `write_envelope` call would let it.
    """
    attach_report(env, output_path)
    write_envelope(output_path, env)


def _build_env_for_pytest(
    config: PlaywrightValidationConfig,
    cases: list[TestCase],
    embed_config: dict[str, Any],
    output_dir: Path,
) -> dict[str, str]:
    """Build environment variables consumed by the pytest spec."""
    env = os.environ.copy()
    csv_path, _ = write_test_cases(cases, output_dir)

    env["PLAYWRIGHT_TEST_CASES"] = str(csv_path.resolve())
    env["PLAYWRIGHT_EMBED_CONFIG"] = json.dumps(embed_config)
    env["PLAYWRIGHT_TIMEOUT_MS"] = str(config.timeout_seconds * 1000)
    env["PLAYWRIGHT_HEADLESS"] = "false" if not config.headless else "true"
    env["PLAYWRIGHT_RESULTS_ROOT"] = str(output_dir.resolve())
    return env


def _run_pytest(
    env: dict[str, str],
    *,
    verbosity: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run the Playwright pytest spec with the prepared environment."""
    repo_root = _repo_root()
    spec_path = repo_root / _SPEC_PATH

    command = [
        sys.executable,
        "-m",
        "pytest",
        str(spec_path),
        "-m",
        "playwright",
        "-v",
        "--html=analyzer-results/playwright/report/index.html",
        "--self-contained-html",
        "--junitxml=analyzer-results/playwright/report/results.xml",
    ]

    if verbosity >= 2:
        command.append("-vv")
    elif verbosity >= 1:
        command.append("-v")

    return subprocess.run(
        command,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _require_service_principal(config: PlaywrightValidationConfig) -> None:
    """Refuse before any client or network call when the service principal
    is incomplete.

    Embed-token generation always calls MSAL with a client secret --
    unlike `pql-test`, which can authenticate interactively -- so this
    check runs unconditionally, before discovery decides whether
    `--artifact` even needs a service client. Naming every missing
    variable and every place to set it is what turns a msal `ValueError`
    two API calls deep into a refusal on line one.
    """
    missing = [
        name
        for name, value in {
            "FABRIC_TENANT_ID": config.tenant_id,
            "FABRIC_CLIENT_ID (or FABRIC_SERVICE_PRINCIPAL_ID)": config.client_id,
            "FABRIC_CLIENT_SECRET (or FABRIC_SERVICE_PRINCIPAL_SECRET)": (
                config.client_secret
            ),
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(
            "Playwright needs a full service principal to generate an "
            f"embed token; missing: {', '.join(missing)}. Set them in the "
            "environment, in a .env file, or pass --env-file."
        )


def _build_config_from_args(
    args: argparse.Namespace,
) -> PlaywrightValidationConfig:
    """Load base config and overlay service-resolved report identity."""
    service_resolved = bool(args.artifact or args.impact_manifest)
    config = load_config(args.env_file, required=not service_resolved)
    _require_service_principal(config)

    if not args.artifact and not args.impact_manifest:
        return config

    if args.impact_manifest:
        return config

    # Checked before the client is built: authenticating only to discover
    # there is no environment to resolve against wastes a round trip, and
    # reports a credential problem when the real problem is a missing flag.
    if not args.environment:
        raise ServiceResolutionError(
            "No environment given, so there is nothing to resolve "
            f"'{args.artifact}' against. Pass --env, set FABRIC_ENVIRONMENT, "
            "or set `environment:` in fab-test.yml."
        )

    client = build_fabric_service_client(
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
        cloud=config.cloud,
        env_file=args.env_file,
    )

    resolved_env = resolve_environment(
        args.environment,
        workspace_id_override=args.workspace_id or config.workspace_id,
    )
    report = resolve_report(args.artifact, resolved_env, client)

    return PlaywrightValidationConfig(
        workspace_id=report.workspace_id,
        report_id=report.report_id,
        report_name=report.report_name,
        dataset_id=args.dataset_id or report.semantic_model_id,
        page_ids=args.page_ids or config.page_ids,
        bookmark_ids=args.bookmark_ids or config.bookmark_ids,
        user_name=config.user_name,
        role=config.role,
        use_rls=config.use_rls,
        cloud=config.cloud,
        client_id=config.client_id,
        client_secret=config.client_secret,
        tenant_id=config.tenant_id,
        timeout_seconds=config.timeout_seconds,
        headless=config.headless,
    )


def _load_impact_manifest(path: Path) -> list[ResolvedReport]:
    """Load reports from an impact manifest JSON."""
    import json

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [
        ResolvedReport(
            workspace_id=report["workspace_id"],
            report_id=report["report_id"],
            report_name=report["report_name"],
            semantic_model_id=report["semantic_model_id"],
            environment=report.get("environment", ""),
        )
        for report in data.get("reports", [])
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Playwright visual validation against a Power BI report."
    )
    parser.add_argument(
        "--env-file",
        help="Path to the .env file containing report and credential settings.",
    )
    parser.add_argument(
        "--output-path",
        help="Path for the standardized analyzer envelope JSON.",
    )
    parser.add_argument(
        "--test-cases-dir",
        help="Directory to write test-cases.csv and test-cases.json.",
    )
    parser.add_argument(
        "--artifact",
        help="Artifact name to resolve from the target environment.",
    )
    parser.add_argument(
        "--env",
        dest="environment",
        help="Target environment label (e.g. dev, test, prod).",
    )
    parser.add_argument(
        "--workspace-id",
        help="Explicit workspace ID (advanced override).",
    )
    parser.add_argument(
        "--dataset-id",
        help="Explicit dataset/semantic-model ID (advanced override).",
    )
    parser.add_argument(
        "--page-ids",
        help="Comma-separated page IDs (advanced override).",
    )
    parser.add_argument(
        "--bookmark-ids",
        help="Comma-separated bookmark IDs (advanced override).",
    )
    parser.add_argument(
        "--impact-manifest",
        help="Path to an impacted-report manifest JSON.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase pytest verbosity.",
    )
    return parser.parse_args(argv)


def _split_comma(value: str | None) -> list[str]:
    """Split a comma-separated string, returning an empty list for empty input."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _write_embed_error_envelope(
    output_path: Path,
    report_name: str,
    cases: list[TestCase],
    message: str,
    test_cases_dir: Path | None = None,
) -> int:
    """Write an error envelope for an embed-context failure and return 1.

    The shared tail of both branches in `_run_single_report`'s embed-context
    try block: a `PowerBiApiError` and any other exception both end here so
    an agent caller always finds a reason in `run.json`, never a null
    ``detail`` from an exception that ran clean off the top of `main()`.
    No case has run yet at this point, so every row falls back to
    "error" -- `test_cases_dir` is omitted entirely when config resolution
    failed before cases even existed.
    """
    findings = _write_findings(cases, success=False, message=message)
    test_results = (
        _test_results_rows(cases, test_cases_dir, overall_success=False)
        if test_cases_dir is not None
        else []
    )
    env = build_envelope(
        analyzer="playwright",
        artifact_path=str(report_name),
        status="error",
        message=message,
        findings=findings,
        duration_ms=0,
    )
    env["test_results"] = test_results
    _write_playwright_envelope(output_path, env)
    log_error(message)
    return 1


def _run_single_report(
    config: PlaywrightValidationConfig,
    args: argparse.Namespace,
    *,
    report_name_override: str = "",
) -> int:
    """Run Playwright validation for a single resolved report."""
    cases = generate_test_cases(config)
    if not cases:
        log("::notice::No Playwright test cases generated; skipping validation.")
        return 0

    test_cases_dir = Path(args.test_cases_dir or _DEFAULT_TEST_CASES_DIR).resolve()
    write_test_cases(cases, test_cases_dir)

    report_name = report_name_override or config.report_name
    output_path = Path(args.output_path).resolve() if args.output_path else envelope_path("playwright", report_name)

    level = args.verbose
    if level >= 1:
        log("================================")
        log(f"playwright -> {report_name}")
        log("================================")
        log(f"📋 Cases:   {len(cases)}")
        log(f"📊 Envelope: {output_path}")
        log("")

    try:
        embed_context = get_embed_context(config)
    except PowerBiApiError as exc:
        message = f"Power BI API error: {exc}"
        if exc.status_code:
            message += f" (HTTP {exc.status_code})"
        return _write_embed_error_envelope(
            output_path, report_name, cases, message, test_cases_dir=test_cases_dir
        )
    except Exception as exc:  # noqa: BLE001 - process boundary: never a bare traceback
        message = f"Failed to acquire embed context: {exc}"
        return _write_embed_error_envelope(
            output_path, report_name, cases, message, test_cases_dir=test_cases_dir
        )

    base_embed_config = build_embed_config(
        report_id=embed_context.report_id,
        embed_url=embed_context.embed_url,
        embed_token=embed_context.embed_token,
    ).to_dict()

    env = _build_env_for_pytest(config, cases, base_embed_config, test_cases_dir)

    with Timer() as timer:
        proc = _run_pytest(env, verbosity=level)

    success = proc.returncode == 0
    message = (
        f"Playwright visual validation passed: {len(cases)} cases"
        if success
        else f"Playwright visual validation failed: {len(cases)} cases"
    )

    # Parse pytest summary for additional context.
    summary = _parse_pytest_summary(proc.stdout or "")
    if summary:
        message += f" ({summary})"

    test_results = _test_results_rows(cases, test_cases_dir, overall_success=success)
    findings = _findings_from_test_results(test_results)

    env_out = build_envelope(
        analyzer="playwright",
        artifact_path=str(report_name),
        status="passed" if success else "failed",
        message=message,
        findings=findings,
        duration_ms=timer.elapsed_ms,
    )
    env_out["test_results"] = test_results
    _write_playwright_envelope(output_path, env_out)

    if level >= 1:
        log(proc.stdout or "")
    if not success and proc.stderr:
        log(proc.stderr)

    log(message)
    return 0 if success else 1


def _config_from_impact_report(
    base_config: PlaywrightValidationConfig,
    report: ResolvedReport,
    args: argparse.Namespace,
) -> PlaywrightValidationConfig:
    """Build a per-report config from an impact manifest entry."""
    return PlaywrightValidationConfig(
        workspace_id=report.workspace_id,
        report_id=report.report_id,
        report_name=report.report_name,
        dataset_id=report.semantic_model_id,
        page_ids=_split_comma(args.page_ids) or base_config.page_ids,
        bookmark_ids=_split_comma(args.bookmark_ids) or base_config.bookmark_ids,
        user_name=base_config.user_name,
        role=base_config.role,
        use_rls=base_config.use_rls,
        cloud=base_config.cloud,
        client_id=base_config.client_id,
        client_secret=base_config.client_secret,
        tenant_id=base_config.tenant_id,
        timeout_seconds=base_config.timeout_seconds,
        headless=base_config.headless,
    )


def run_playwright_validation(args: argparse.Namespace) -> int:
    """Orchestrate the Playwright validation and write the result envelope."""
    try:
        base_config = _build_config_from_args(args)
    except ValueError as exc:
        # A missing prerequisite (readiness-probe contract), not a run
        # failure -- `_require_service_principal` and `load_config`'s
        # required-field check are the only raisers.
        log_error(str(exc))
        return 127
    except (ServiceResolutionError, PowerBiApiError) as exc:
        log_error(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - process boundary: resolving
        # config or the discovery service client must never reach the
        # console as a traceback either -- the wrapper's "no traceback"
        # goal does not stop at the embed-token step `_run_single_report`
        # already guards.
        message = f"Failed to resolve Playwright configuration: {exc}"
        report_name = args.artifact or "playwright"
        output_path = (
            Path(args.output_path).resolve()
            if args.output_path
            else envelope_path("playwright", report_name)
        )
        return _write_embed_error_envelope(output_path, report_name, [], message)

    if args.impact_manifest:
        reports = _load_impact_manifest(Path(args.impact_manifest).resolve())
        if not reports:
            log("::notice::Impact manifest is empty; skipping Playwright validation.")
            return 0

        overall = 0
        for report in reports:
            config = _config_from_impact_report(base_config, report, args)
            code = _run_single_report(
                config, args, report_name_override=report.report_name
            )
            if code != 0:
                overall = 1
        return overall

    return _run_single_report(base_config, args)


def _parse_pytest_summary(stdout: str) -> str:
    """Extract the pytest short summary line if present.

    Matches final summary lines such as ``1 passed in 1.23s`` or
    ``1 failed, 2 passed in 0.50s``.
    """
    for line in stdout.splitlines():
        stripped = line.strip()
        if "passed in " in stripped or "failed in " in stripped:
            return stripped
    return ""


def main(argv: list[str] | None = None) -> int:
    """Entry point for the invoke_playwright wrapper."""
    args = parse_args(argv)
    return run_playwright_validation(args)


if __name__ == "__main__":
    sys.exit(main())
