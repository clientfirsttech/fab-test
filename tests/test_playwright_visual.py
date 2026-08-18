"""pytest-playwright spec for dynamic Power BI report visual validation.

Tests are parametrized from ``test-cases.csv`` produced by ``invoke_playwright.py``.
The spec loads each row, fetches an embed token and embed URL, injects the
Power BI JavaScript client from CDN, embeds the report, and races the
``rendered`` event against ``error`` events on ``document.body``.

This file is a pytest test module and is excluded from the default contract-tier
pytest run via the ``playwright`` marker. It is invoked by ``invoke_playwright.py``
with an explicit ``-m playwright`` selector.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.playwright


def _results_root() -> Path:
    """Return the analyzer-results root for this test run."""
    return Path(os.getenv("PLAYWRIGHT_RESULTS_ROOT", "analyzer-results/playwright"))


def _load_test_cases() -> list[dict[str, str]]:
    """Load test cases from the CSV path supplied by the wrapper."""
    path = os.getenv("PLAYWRIGHT_TEST_CASES")
    if not path:
        return []
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with open(csv_path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _test_case_id(case: dict[str, str]) -> str:
    """Return a pytest-friendly node id for a test case."""
    raw = case.get("test_case") or "unknown"
    return re.sub(r"[^\w\-]", "_", raw).strip("_")


def _case_result_dir(case: dict[str, str]) -> Path:
    """Return the per-case output directory for screenshots and logs."""
    return _results_root() / _test_case_id(case)


def _write_evidence(
    page: Any,
    result_dir: Path,
    console_logs: list[dict[str, Any]],
    failed_requests: list[dict[str, Any]],
) -> None:
    """Capture screenshot, console logs, and failed network requests."""
    result_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = result_dir / "screenshot.png"
    with contextlib.suppress(Exception):
        page.screenshot(path=str(screenshot_path), full_page=True)
    if console_logs:
        (result_dir / "console.json").write_text(
            json.dumps(console_logs, indent=2, default=str), encoding="utf-8"
        )
    if failed_requests:
        (result_dir / "network.json").write_text(
            json.dumps(failed_requests, indent=2, default=str), encoding="utf-8"
        )


TEST_CASES = _load_test_cases()


@pytest.mark.parametrize("case", TEST_CASES, ids=_test_case_id)
def test_report_visual_renders(page, case: dict[str, str]) -> None:
    """Embed a Power BI report and fail if an error event fires before rendered."""
    if not case:
        pytest.skip("Empty test case")

    report_type = case.get("report_type", "report")
    if report_type == "rdl":
        _test_paginated_report(page, case)
        return

    embed_config_json = os.getenv("PLAYWRIGHT_EMBED_CONFIG")
    if not embed_config_json:
        pytest.skip("PLAYWRIGHT_EMBED_CONFIG not set; run via invoke_playwright.py")

    base_config = json.loads(embed_config_json)
    config = dict(base_config)
    if case.get("page_id"):
        config["pageName"] = case["page_id"]
    else:
        config.pop("pageName", None)
    if case.get("bookmark_id"):
        config["bookmark"] = {"name": case["bookmark_id"]}
    else:
        config.pop("bookmark", None)

    result_dir = _case_result_dir(case)
    result_dir.mkdir(parents=True, exist_ok=True)

    timeout_ms = int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "60000"))
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"

    console_logs: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []

    page.on("console", lambda msg: console_logs.append({
        "type": msg.type,
        "text": msg.text,
        "location": msg.location,
    }))
    page.on("requestfailed", lambda req: failed_requests.append({
        "url": req.url,
        "failure": req.failure,
    }))

    page.goto("about:blank")
    page.add_script_tag(url="https://cdn.jsdelivr.net/npm/powerbi-client@2.23.1/dist/powerbi.min.js")

    # Wait briefly for the library to register itself on window.powerbi.
    page.wait_for_function("() => typeof window.powerbi !== 'undefined'", timeout=10000)

    # Inject the report container and embed configuration.
    page.set_content("<html><body style='margin:0;height:100vh;'></body></html>")
    try:
        page.evaluate(
            """([config]) => {
                window.__pbiRenderResult = null;
                window.__pbiEmbedError = null;
                try {
                    const report = window.powerbi.embed(document.body, config);
                    report.on('rendered', () => {
                        window.__pbiRenderResult = 'rendered';
                    });
                    report.on('error', (event) => {
                        window.__pbiRenderResult = 'error:' +
                            JSON.stringify(event.detail || event);
                    });
                } catch (err) {
                    function describeError(e) {
                        if (Array.isArray(e)) {
                            return e.map(describeError);
                        }
                        if (e && typeof e === 'object') {
                            const out = {};
                            Object.getOwnPropertyNames(e).forEach(function (key) {
                                try {
                                    out[key] = describeError(e[key]);
                                } catch (_) {
                                    out[key] = String(e[key]);
                                }
                            });
                            return out;
                        }
                        return e;
                    }
                    window.__pbiEmbedError = JSON.stringify(describeError(err));
                }
            }""",
            [config],
        )
    except Exception as exc:
        _write_evidence(page, result_dir, console_logs, failed_requests)
        pytest.fail(f"Failed to evaluate Power BI embed script: {exc}")

    embed_error = page.evaluate("() => window.__pbiEmbedError")
    if embed_error:
        _write_evidence(page, result_dir, console_logs, failed_requests)
        pytest.fail(f"Power BI embed failed: {embed_error}")

    # Race rendered vs error.
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    result: str | None = None
    while time.monotonic() < deadline:
        result = page.evaluate("() => window.__pbiRenderResult")
        if result:
            break
        time.sleep(0.5)

    # Capture evidence before asserting so failures always include artifacts.
    _write_evidence(page, result_dir, console_logs, failed_requests)

    if not headless:
        # Give a local user a moment to inspect the rendered report.
        time.sleep(2)

    if result is None:
        pytest.fail(f"Report did not render within {timeout_ms}ms")

    if isinstance(result, str) and result.startswith("error:"):
        pytest.fail(f"Power BI error event fired: {result[len('error:'):]}")


def _test_paginated_report(page: Any, case: dict[str, str]) -> None:
    """Embed a paginated (RDL) report and fail if an error modal is detected."""
    embed_config_json = os.getenv("PLAYWRIGHT_EMBED_CONFIG")
    if not embed_config_json:
        pytest.skip("PLAYWRIGHT_EMBED_CONFIG not set; run via invoke_playwright.py")

    base_config = json.loads(embed_config_json)
    config = dict(base_config)
    config["type"] = "report"

    result_dir = _case_result_dir(case)
    result_dir.mkdir(parents=True, exist_ok=True)

    rdl_wait_seconds = int(os.getenv("PLAYWRIGHT_RDL_WAIT_SECONDS", "10"))

    console_logs: list[dict[str, Any]] = []
    failed_requests: list[dict[str, Any]] = []

    page.on("console", lambda msg: console_logs.append({
        "type": msg.type,
        "text": msg.text,
        "location": msg.location,
    }))
    page.on("requestfailed", lambda req: failed_requests.append({
        "url": req.url,
        "failure": req.failure,
    }))

    page.goto("about:blank")
    page.add_script_tag(
        url="https://cdn.jsdelivr.net/npm/powerbi-client@2.23.1/dist/powerbi.min.js"
    )
    page.wait_for_function(
        "() => typeof window.powerbi !== 'undefined'", timeout=10000
    )
    page.set_content("<html><body style='margin:0;height:100vh;'></body></html>")

    try:
        page.evaluate(
            """([config]) => {
                window.__pbiRenderResult = null;
                try {
                    window.powerbi.embed(document.body, config);
                    window.__pbiRenderResult = 'embedded';
                } catch (err) {
                    window.__pbiRenderResult = 'error:' + String(err);
                }
            }""",
            [config],
        )
    except Exception as exc:
        _write_evidence(page, result_dir, console_logs, failed_requests)
        pytest.fail(f"Failed to evaluate RDL embed script: {exc}")

    page.wait_for_timeout(rdl_wait_seconds * 1000)

    error_selectors = [
        ".ms-Dialog-content",
        ".errorDialog",
        "[data-testid='error-message']",
    ]
    error_found = False
    for selector in error_selectors:
        if page.locator(selector).count() > 0:
            error_found = True
            break

    # Check inside iframes as well.
    if not error_found:
        for frame in page.frames:
            with contextlib.suppress(Exception):
                content = frame.content()
                if "ms-Dialog-content" in content:
                    error_found = True
                    break

    _write_evidence(page, result_dir, console_logs, failed_requests)

    if error_found:
        pytest.fail("RDL error modal detected")
