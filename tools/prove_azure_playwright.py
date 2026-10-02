"""Opt-in Azure compatibility proof; not the shipped execution adapter.

Run with python -m tools.prove_azure_playwright followed by invoke_playwright
arguments. Loads service credentials from the selected local env file and
executes the wrapper's generated report tests through remote Python browsers.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Browser, Error

from fab_test.scripts import invoke_playwright
from fab_test.scripts.playwright_validation.config import resolve_env_file


def connection_options(run_id: str) -> dict[str, Any]:
    """Construct token-authenticated service options without logging secrets."""
    endpoint = os.environ.get("PLAYWRIGHT_SERVICE_URL", "")
    token = os.environ.get("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", "")
    for name, value in (("PLAYWRIGHT_SERVICE_URL", endpoint), ("PLAYWRIGHT_SERVICE_ACCESS_TOKEN", token)):
        if not value:
            raise ValueError(f"Set {name} in the environment or selected env file")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "wss" or not parsed.hostname
        or any((parsed.username, parsed.password, parsed.query, parsed.fragment))
    ):
        raise ValueError("PLAYWRIGHT_SERVICE_URL must be a credential-free wss endpoint without query or fragment")
    query = urlencode({
        "runId": run_id,
        "os": "linux",
        "sourceType": "PlaywrightWorkspacesTestRun",
        "api-version": "2025-09-01",
    })
    return {
        "endpoint": f"{endpoint}?{query}",
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": 30000,
        "expose_network": "<loopback>",
    }


@pytest.fixture(scope="session")
def connect_options() -> dict[str, Any]:
    """Connect the packaged render spec to the service for this proof only."""
    return connection_options(os.environ["PLAYWRIGHT_PROOF_RUN_ID"])


@pytest.fixture(scope="session")
def launch_browser(launch_browser: Callable[..., Browser]) -> Callable[..., Browser]:
    """Keep raw Playwright connection diagnostics out of pytest tracebacks."""
    def launch(**kwargs: Any) -> Browser:
        try:
            return launch_browser(**kwargs)
        except Error as error:
            status = re.search(r"(?:response|status)(?: code)?:?\s*(\d{3})", str(error), re.IGNORECASE)
            detail = f"HTTP {status.group(1)}" if status else type(error).__name__
            pytest.fail(f"Azure browser connection failed ({detail}); raw diagnostics withheld", pytrace=False)

    return launch


def _proof_pytest(
    env: dict[str, str],
    *,
    verbosity: int = 0,
    case_count: int = 1,
    max_workers: int | None = None,
) -> subprocess.CompletedProcess[str]:
    output = Path(env["PLAYWRIGHT_RESULTS_ROOT"])
    command = [
        sys.executable, "-m", "pytest", str(invoke_playwright._spec_path()),
        "-p", "tools.prove_azure_playwright", "-m", "playwright", "-v",
        f"--html={output / 'report.html'}", "--self-contained-html",
        f"--junitxml={output / 'results.xml'}",
    ]
    workers = invoke_playwright._resolve_xdist_workers(
        case_count, invoke_playwright._resolve_max_workers(max_workers)
    )
    if workers is not None:
        command.extend(["-n", str(workers)])
    return invoke_playwright._stream_subprocess(
        command, cwd=invoke_playwright._repo_root(), env=env, verbose=verbosity >= 1
    )


def main(argv: list[str] | None = None) -> int:
    """Run only the compatibility proof, leaving production wiring unchanged."""
    args = invoke_playwright.parse_args(argv)
    load_dotenv(resolve_env_file(args.env_file), override=False)
    os.environ.pop("DEBUG", None)
    os.environ["PLAYWRIGHT_PROOF_RUN_ID"] = str(uuid4())
    try:
        connection_options(os.environ["PLAYWRIGHT_PROOF_RUN_ID"])
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 127
    invoke_playwright._run_pytest = _proof_pytest
    return invoke_playwright.run_playwright_validation(args)


if __name__ == "__main__":
    sys.exit(main())
