"""Credential-safe runtime preparation for optional browser execution YAML."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import os
import shutil
import sys
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit
from uuid import uuid4

from playwright.sync_api import BrowserType

from .._config import ConfigError, merged_file_config
from .config import _env_or_env_file, resolve_env_file
from .execution_config import (  # noqa: F401 - resolve_jobs/execution_summary re-exported
    ExecutionConfig,
    execution_summary,
    resolve_execution_config,
    resolve_jobs,
    resolve_workers,
)

EXECUTION_PATH = "FAB_TEST_PLAYWRIGHT_EXECUTION_CONFIG"
EXECUTION_RUN_ID = "FAB_TEST_PLAYWRIGHT_RUN_ID"
EXECUTION_REPORT_ROOT = "FAB_TEST_PLAYWRIGHT_REPORT_ROOT"
EXECUTION_LAUNCH = "FAB_TEST_PLAYWRIGHT_LAUNCH_OVERRIDES"
_PLUGIN = "fab_test.scripts.playwright_validation.execution_plugin"
_XDIST_MAX_WORKERS = 4
# Playwright renamed connect()'s first parameter from ws_endpoint to endpoint.
_ENDPOINT_KEYWORD = (
    "endpoint" if "endpoint" in inspect.signature(BrowserType.connect).parameters else "ws_endpoint"
)


def _validate_service_url(endpoint: str) -> None:
    try:
        parsed = urlsplit(endpoint)
        valid = (
            parsed.scheme == "wss" and bool(parsed.hostname)
            and not any((parsed.username, parsed.password, parsed.query, parsed.fragment))
        )
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError("PLAYWRIGHT_SERVICE_URL must be a credential-free wss endpoint without query or fragment")


def service_environment(config: ExecutionConfig, env_file: Path) -> dict[str, str]:
    """Read Azure credentials without mutating the caller's environment."""
    if config.backend != "azure":
        return {}
    values = {}
    for name in ("PLAYWRIGHT_SERVICE_URL", "PLAYWRIGHT_SERVICE_ACCESS_TOKEN"):
        value = _env_or_env_file(name, env_file)
        if not value:
            raise ValueError(f"Set {name} in the process environment or selected --env-file")
        values[name] = value
    _validate_service_url(values["PLAYWRIGHT_SERVICE_URL"])
    return values


def browser_connection_options(
    config: ExecutionConfig, environment: dict[str, str], run_id: str,
) -> dict[str, Any] | None:
    """Build the verified Azure service connection; local execution returns None."""
    if config.backend != "azure":
        return None
    endpoint = environment["PLAYWRIGHT_SERVICE_URL"]
    _validate_service_url(endpoint)
    query = urlencode({
        "runId": run_id, "os": config.connection.get("os", "linux"),
        "sourceType": "PlaywrightWorkspacesTestRun", "api-version": "2025-09-01",
    })
    return {
        _ENDPOINT_KEYWORD: f"{endpoint}?{query}",
        "headers": {"Authorization": f"Bearer {environment['PLAYWRIGHT_SERVICE_ACCESS_TOKEN']}"},
        "timeout": config.connection.get("timeout_ms", 30000),
        "expose_network": config.connection.get("expose_network", "<loopback>"),
    }


def _resolve_max_workers(explicit: int | None) -> int:
    """Preserve the default runner's worker-resolution entry point."""
    return resolve_workers(ExecutionConfig(), explicit)


def _resolve_xdist_workers(case_count: int, max_workers: int = 4) -> int | None:
    """Bound workers by case count and omit xdist for a single case."""
    return min(case_count, max_workers) if case_count > 1 else None


def launch_overrides(args: argparse.Namespace, config: ExecutionConfig) -> dict[str, Any]:
    """Collect --headed/--slow-mo; Azure-hosted browsers cannot show a local window."""
    overrides: dict[str, Any] = {}
    if getattr(args, "headed", False):
        overrides["headless"] = False
    slow_mo = getattr(args, "slow_mo", None)
    if slow_mo is not None:
        if slow_mo < 0:
            raise ConfigError("--slow-mo must be a nonnegative number of milliseconds")
        overrides["slow_mo"] = slow_mo
    if overrides and config.backend == "azure":
        print("::warning::--headed/--slow-mo are ignored: Azure-hosted browsers have no local window", file=sys.stderr)
        return {}
    return overrides


def headless_requested_false(environment: Any) -> bool:
    """True when PLAYWRIGHT_HEADLESS asks for a visible local browser."""
    return str(environment.get("PLAYWRIGHT_HEADLESS", "")).lower() == "false"


def warn_ignored_headless(config: ExecutionConfig, env_file: Path) -> None:
    """Azure-hosted browsers have no local window, so PLAYWRIGHT_HEADLESS=false cannot apply."""
    value = _env_or_env_file("PLAYWRIGHT_HEADLESS", env_file)
    if config.backend == "azure" and headless_requested_false({"PLAYWRIGHT_HEADLESS": value}):
        message = "PLAYWRIGHT_HEADLESS=false is ignored: Azure-hosted browsers have no local window"
        print(f"::warning::{message}", file=sys.stderr)


def prepare_wrapper_execution(args: argparse.Namespace) -> None:
    """Validate configuration and credentials before any Fabric API call."""
    root = Path.cwd()
    file_config, _ = merged_file_config(root, root / "pyproject.toml")
    args.execution_config = resolve_execution_config(getattr(args, "playwright_config", None), file_config, root)
    args.execution_launch = launch_overrides(args, args.execution_config)
    warn_ignored_headless(args.execution_config, resolve_env_file(args.env_file))
    if args.execution_config.path:
        args.workers = resolve_workers(args.execution_config, getattr(args, "workers", None))
    args.execution_environment = (
        {} if getattr(args, "plan_only", False)
        else service_environment(args.execution_config, resolve_env_file(args.env_file))
    )


def apply_execution_environment(
    environment: dict[str, str], args: argparse.Namespace, result_dirs: list[Path] | None = None,
    *, report_root: Path | None = None,
) -> None:
    """Pass only the selected execution path, run identity, and service credentials."""
    config = getattr(args, "execution_config", ExecutionConfig())
    environment.pop(EXECUTION_PATH, None)
    environment.pop(EXECUTION_RUN_ID, None)
    environment.pop(EXECUTION_REPORT_ROOT, None)
    environment.pop(EXECUTION_LAUNCH, None)
    if getattr(args, "execution_launch", None):
        environment[EXECUTION_LAUNCH] = json.dumps(args.execution_launch)
    if report_root is not None:
        # Beside the envelope, so --output-dir governs pytest's own reports too.
        environment[EXECUTION_REPORT_ROOT] = str(report_root)
    if config.path:
        environment[EXECUTION_PATH] = str(config.path)
        environment[EXECUTION_RUN_ID] = str(uuid4())
        environment.update(args.execution_environment)
        environment.pop("DEBUG", None)
        for directory in result_dirs or []:
            if directory.exists():
                shutil.rmtree(directory)


def configure_pytest_execution(command: list[str], environment: dict[str, str]) -> None:
    """Point pytest's native reports beside the envelope and load the optional adapter."""
    selected = bool(environment.get(EXECUTION_PATH))
    if environment.get(EXECUTION_REPORT_ROOT) or selected:
        report_root = (
            Path(environment[EXECUTION_REPORT_ROOT]) if environment.get(EXECUTION_REPORT_ROOT)
            else Path(environment["PLAYWRIGHT_RESULTS_ROOT"]) / "report"
        )
        replacements = {"--html=": report_root / "index.html", "--junitxml=": report_root / "results.xml"}
        for index, argument in enumerate(command):
            for prefix, path in replacements.items():
                if argument.startswith(prefix):
                    command[index] = f"{prefix}{path}"
    if selected or environment.get(EXECUTION_LAUNCH) or headless_requested_false(environment):
        command += ["-p", _PLUGIN]


# Distribution name -> import name for what `_run_pytest` launches. None are
# base dependencies; the `playwright` extra installs all four.
_RUNNER_MODULES = {
    "pytest": "pytest",
    "pytest-playwright": "pytest_playwright",
    "pytest-html": "pytest_html",
    "pytest-xdist": "xdist",
}


def missing_runner_message() -> str | None:
    """Name the pytest packages a render run needs that this interpreter lacks.

    Checked before any embed token is minted, so a bare `pip install
    cft-fab-test` fails with an install command instead of a child
    process's `ModuleNotFoundError: No module named 'pytest'`.
    """
    missing = [name for name, module in _RUNNER_MODULES.items() if importlib.util.find_spec(module) is None]
    if not missing:
        return None
    return (
        f"Playwright runs need {', '.join(missing)}, which this environment does not have. "
        'Install them with: pip install "cft-fab-test[playwright]"'
    )


def execution_failure(returncode: int, result_dirs: list[Path]) -> str | None:
    """Distinguish unexecuted cases and pytest tool errors from visual findings."""
    if returncode not in (0, 1) or any(not (directory / "result.json").is_file() for directory in result_dirs):
        return (
            "Python Playwright/pytest did not execute every generated case; check browser connection, "
            "PLAYWRIGHT_SERVICE_URL, PLAYWRIGHT_SERVICE_ACCESS_TOKEN, and installed pytest plugins"
        )
    return None


def _embedded_token_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        tokens = [item for key, item in value.items() if key in ("accessToken", "embedToken") and isinstance(item, str)]
        return tokens + [token for item in value.values() for token in _embedded_token_values(item)]
    if isinstance(value, list):
        return [token for item in value for token in _embedded_token_values(item)]
    return []


def redact_execution_text(text: str, environment: dict[str, str] | None = None) -> str:
    """Remove known credentials from optional-run diagnostics before replay or persistence."""
    environment = environment if environment is not None else os.environ
    if not environment.get(EXECUTION_PATH):
        return text
    secrets = [environment.get(name, "") for name in (
        "PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "FABRIC_CLIENT_SECRET", "FABRIC_SERVICE_PRINCIPAL_SECRET",
    )]
    for name in ("PLAYWRIGHT_EMBED_CONFIG", "PLAYWRIGHT_EMBED_CONFIGS"):
        try:
            secrets.extend(_embedded_token_values(json.loads(environment.get(name, "{}"))))
        except json.JSONDecodeError:
            continue
    encoded = {
        representation for secret in secrets if secret
        for representation in (secret, json.dumps(secret)[1:-1], escape(secret), quote(secret, safe=""))
    }
    for secret in sorted(encoded, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def write_execution_text(path: Path, text: str) -> None:
    """Write browser evidence without credentials; preserve default-run formatting."""
    path.write_text(redact_execution_text(text), encoding="utf-8")


def execution_readiness(result: dict[str, Any], name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    """Extend existing readiness without connecting or exposing credentials."""
    if name != "playwright" or not result["ready"]:
        return result
    missing = missing_runner_message()
    if missing:
        return {**result, "ready": False, "reason": missing, "remediation": 'pip install "cft-fab-test[playwright]"'}
    config = getattr(args, "execution_config", ExecutionConfig())
    if config.backend != "azure":
        return result
    try:
        service_environment(config, resolve_env_file(getattr(args, "playwright_env_file", None)))
    except (ConfigError, ValueError) as error:
        return {**result, "ready": False, "reason": str(error), "remediation": str(error)}
    return result
