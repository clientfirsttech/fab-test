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
import time
from pathlib import Path
from typing import Any

import pytest

from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import sanitize_case_id

pytestmark = pytest.mark.playwright


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, Any]) -> dict[str, Any]:
    """Disable Chromium's same-origin policy for the embed sandbox.

    Without this, the Power BI JS SDK's own calls to
    api.powerbi.com/metadata/cluster/... and .../globalservice/... come
    back 403 from the about:blank origin this spec embeds into, and the
    SDK falls into its generic "Something went wrong" error page without
    ever firing `rendered` or `error` on the report object -- so the race
    in `test_report_visual_renders` hangs until the timeout instead of
    failing fast with a real reason. Confirmed against kerski's own
    working reference implementation (pbi-dataops-visual-error-testing),
    which launches Chromium the same way.
    """
    return {**browser_type_launch_args, "args": ["--disable-web-security"]}


def _results_root() -> Path:
    """Return the fab-test-results root for this test run."""
    return Path(os.getenv("PLAYWRIGHT_RESULTS_ROOT", "fab-test-results/playwright"))


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
    return sanitize_case_id(case.get("test_case"))


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


def _capture_embed_error_details(page: Any, result_dir: Path) -> str:
    """Best-effort extraction of Power BI's own "Something went wrong" panel.

    The embed SDK's `report.on('error', ...)` does not always fire when the
    failure happens before the report object finishes initializing (e.g. a
    permissions or CORS problem) -- the iframe just shows its own generic
    error page instead, and the render/error race times out with no
    indication of why. Any details text found here is written to
    ``embed_error_details.txt`` so a timeout's evidence names the real
    cause instead of only restating the timeout.
    """
    for frame in page.frames:
        text = ""
        with contextlib.suppress(Exception):
            details_link = frame.get_by_text("Show details", exact=False)
            if details_link.count() > 0:
                with contextlib.suppress(Exception):
                    details_link.first.click(timeout=2000)
                    frame.wait_for_timeout(500)
            text = frame.locator("body").inner_text(timeout=1000)
        if "Something went wrong" in text:
            with contextlib.suppress(Exception):
                (result_dir / "embed_error_details.txt").write_text(
                    text.strip(), encoding="utf-8"
                )
            return text.strip()
    return ""


def _write_result(result_dir: Path, status: str, error: str = "") -> None:
    """Record this case's actual outcome.

    The pytest process's own exit code only says whether *any* case
    failed, not which one -- with several report x page x bookmark
    combinations in one run, that is not enough for
    ``invoke_playwright.py`` to tell a real failure from a case that
    never ran. ``status`` uses the same pass/error vocabulary the BPA and
    PBIR wrappers already normalize their own test_results to.
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "result.json").write_text(
        json.dumps({"status": status, "error": error}), encoding="utf-8"
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

    # Size the existing body as the report container. Deliberately NOT
    # page.set_content(): that performs document.open()/write(), which removes
    # every window event listener -- including the WindowPostMessageProxy
    # listener the Power BI service uses to receive events from the embed
    # iframe. The iframe still renders (it is self-contained), but no `rendered`
    # or `error` ever reaches a handler, so the race below times out on a report
    # that is visibly fine. Measured A/B against a real workspace: with
    # set_content, 6 postMessages arrive and 0 SDK events fire; without it, the
    # same run reports `loaded` at 8.7s and `rendered` at 12.5s.
    page.evaluate(
        "() => { document.body.style.margin = '0'; document.body.style.height = '100vh'; }"
    )
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
        error = f"Failed to evaluate Power BI embed script: {exc}"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

    embed_error = page.evaluate("() => window.__pbiEmbedError")
    if embed_error:
        _write_evidence(page, result_dir, console_logs, failed_requests)
        error = f"Power BI embed failed: {embed_error}"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

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
        error = f"Report did not render within {timeout_ms}ms"
        details = _capture_embed_error_details(page, result_dir)
        if details:
            error += f"; embed error panel: {details}"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

    if isinstance(result, str) and result.startswith("error:"):
        error = f"Power BI error event fired: {result[len('error:'):]}"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

    _write_result(result_dir, "pass")


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
        error = f"Failed to evaluate RDL embed script: {exc}"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

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
        error = "RDL error modal detected"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

    _write_result(result_dir, "pass")
