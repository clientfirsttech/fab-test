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
    write_test_cases,
)

# Relative path from repo root to the pytest spec.
_SPEC_PATH = Path("tests") / "test_playwright_visual.py"

# Default output location for test-case CSV/JSON artifacts.
_DEFAULT_TEST_CASES_DIR = Path("analyzer-results") / "playwright" / "test-cases"


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message."""
    print(message)


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


def _build_config_from_args(
    args: argparse.Namespace,
) -> PlaywrightValidationConfig:
    """Load base config and overlay service-resolved report identity."""
    service_resolved = bool(args.artifact or args.impact_manifest)
    config = load_config(args.env_file, required=not service_resolved)

    if not args.artifact and not args.impact_manifest:
        return config

    if args.impact_manifest:
        return config

    client = build_fabric_service_client(
        tenant_id=config.tenant_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
        cloud=config.cloud,
        env_file=args.env_file,
    )

    resolved_env = resolve_environment(
        args.environment or config.environment or "dev",
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
    if args.output_path:
        output_path = Path(args.output_path).resolve()
    else:
        output_path = envelope_path("playwright", report_name)

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
        findings = _write_findings(cases, success=False, message=message)
        env = build_envelope(
            analyzer="playwright",
            artifact_path=str(report_name),
            status="error",
            message=message,
            findings=findings,
            duration_ms=0,
        )
        write_envelope(output_path, env)
        log(f"::error::{message}")
        return 1

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

    findings = _write_findings(
        cases,
        success=success,
        message="Visual load error detected" if not success else "",
    )

    env_out = build_envelope(
        analyzer="playwright",
        artifact_path=str(report_name),
        status="passed" if success else "failed",
        message=message,
        findings=findings,
        duration_ms=timer.elapsed_ms,
    )
    write_envelope(output_path, env_out)

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
    except (ValueError, ServiceResolutionError, PowerBiApiError) as exc:
        log(f"::error::{exc}")
        return 1

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
