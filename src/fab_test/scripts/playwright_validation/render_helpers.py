"""Library code behind the Playwright render spec.

Split out of the pytest module itself (Playwright CI Guide epic, Render Spec
Packaging task) so this repository's own unit tests
(``tests/test_playwright_visual.py``) can exercise these functions with
stubs, while the actual pytest module that runs against a live Fabric
workspace (``render_spec.py``) ships inside the installed package -- a
``pip install cft-fab-test`` consumer has no checkout of this repository's
``tests/`` directory for ``invoke_playwright.py`` to point pytest at.
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

from .test_cases import sanitize_case_id


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


def _start_event_capture(page: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Register console/failed-request listeners and return their (empty) sinks.

    Shared by the interactive and paginated embed paths -- both want the
    same console-error and failed-network evidence, and duplicating the
    listener wiring between them was how they used to drift.
    """
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
    return console_logs, failed_requests


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


class _NoEmbedConfigForRole(Exception):
    """Raised when a role-keyed matrix has no embed config for this case's role."""


def _embed_config_for_role(role: str) -> dict[str, Any] | None:
    """Return the embed config for a case's role.

    A matrix spanning more than one role gets ``PLAYWRIGHT_EMBED_CONFIGS``, a
    role-keyed map -- one embed token per role, since a token carries its RLS
    identity baked in and cannot cover two roles. A single-role run only ever
    sets ``PLAYWRIGHT_EMBED_CONFIG``, so that stays the fallback. A case whose
    role has no entry in ``PLAYWRIGHT_EMBED_CONFIGS`` raises rather than
    silently falling back to another role's token.
    """
    configs_json = os.getenv("PLAYWRIGHT_EMBED_CONFIGS")
    if configs_json:
        configs = json.loads(configs_json)
        if role not in configs:
            raise _NoEmbedConfigForRole(
                f"no embed config for role '{role or 'default'}'"
            )
        return configs[role]

    embed_config_json = os.getenv("PLAYWRIGHT_EMBED_CONFIG")
    if not embed_config_json:
        return None
    return json.loads(embed_config_json)


def _resolve_case_config(case: dict[str, str]) -> dict[str, Any]:
    """Resolve an interactive case's embed config, overlaid with its page/bookmark.

    Ends the test itself (``pytest.fail``/``pytest.skip``) on a missing role
    or an unconfigured embed token -- neither is a render outcome for this
    case, so there is nothing for the caller to branch on afterward.
    """
    try:
        base_config = _embed_config_for_role(case.get("role", ""))
    except _NoEmbedConfigForRole as exc:
        error = f"{exc} (case {case.get('test_case')})"
        _write_result(_case_result_dir(case), "error", error)
        pytest.fail(error)
    if base_config is None:
        pytest.skip("PLAYWRIGHT_EMBED_CONFIG not set; run via invoke_playwright.py")

    config = dict(base_config)
    if case.get("page_id"):
        config["pageName"] = case["page_id"]
    else:
        config.pop("pageName", None)
    if case.get("bookmark_id"):
        config["bookmark"] = {"name": case["bookmark_id"]}
    else:
        config.pop("bookmark", None)
    return config


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


def _embed_interactive_report(
    page: Any,
    config: dict[str, Any],
    result_dir: Path,
    console_logs: list[dict[str, Any]],
    failed_requests: list[dict[str, Any]],
) -> None:
    """Load the report and start the render/error race; fail the case on an embed-time error.

    Ends the test itself on any failure here -- a JS-evaluate exception or an
    immediate ``__pbiEmbedError`` -- since neither is a render outcome for
    ``_wait_for_render_result`` to race; the caller only reaches the race at
    all once this returns normally.
    """
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
                window.__pbiEventLog = [];
                try {
                    const logEvent = (name) => (event) => {
                        window.__pbiEventLog.push({
                            name,
                            t: performance.now(),
                            detail: (() => {
                                try {
                                    return JSON.stringify(event.detail || null);
                                } catch (_) {
                                    return String(event.detail);
                                }
                            })(),
                        });
                    };
                    // Record every SDK event seen on document.body, in
                    // order, as evidence (event_log.json below) -- this is
                    // how the 'error'-then-'rendered' clobbering race was
                    // actually found, and it is the diagnostic to reach for
                    // the next time these events surprise us.
                    ["rendered", "error", "loaded", "rendering",
                     "visualRendered", "commandTriggered"].forEach((name) => {
                        document.body.addEventListener(name, logEvent(name));
                    });
                    // 'error' and 'rendered' can both fire (e.g. a broken
                    // visual's error a few dozen ms before the report shell's
                    // own rendered) -- whichever handler runs LAST must not
                    // blindly overwrite the other's result, or an error that
                    // arrived first gets clobbered back to 'rendered'.
                    document.body.addEventListener('rendered', () => {
                        const already = window.__pbiRenderResult;
                        if (!(typeof already === 'string' && already.startsWith('error:'))) {
                            window.__pbiRenderResult = 'rendered';
                        }
                    }, { once: true });
                    document.body.addEventListener('error', (event) => {
                        window.__pbiRenderResult = 'error:' +
                            JSON.stringify(event.detail || event);
                    }, { once: true });
                    window.powerbi.embed(document.body, config);
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
    except Exception as exc:  # noqa: BLE001 - the embed script's own failure is the evidence
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


def _finish_interactive_case(
    page: Any,
    result: str | None,
    *,
    timeout_ms: int,
    headless: bool,
    result_dir: Path,
    console_logs: list[dict[str, Any]],
    failed_requests: list[dict[str, Any]],
) -> None:
    """Write evidence, then turn the raced render outcome into a pass/fail.

    ``result`` is whatever `_wait_for_render_result` returned: ``None`` (timed
    out with no terminal event), an ``'error:...'`` reading, or ``'rendered'``.
    """
    # Capture evidence before asserting so failures always include artifacts.
    _write_evidence(page, result_dir, console_logs, failed_requests)

    # Evidence: every SDK event actually observed on document.body, in
    # order, regardless of pass/fail -- see event_log.json.
    with contextlib.suppress(Exception):
        event_log = page.evaluate("() => window.__pbiEventLog")
        if event_log:
            (result_dir / "event_log.json").write_text(
                json.dumps(event_log, indent=2), encoding="utf-8"
            )

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


def _wait_for_render_result(
    read_result,
    *,
    timeout_seconds: float,
    grace_seconds: float,
    poll_interval: float = 0.5,
    now=time.monotonic,
    sleep=time.sleep,
) -> str | None:
    """Poll ``read_result`` for a terminal render outcome.

    An `'error:...'` reading is terminal immediately. A `'rendered'`
    reading is not: Power BI's report-level `rendered` event and a broken
    visual's own `error` event are not guaranteed to arrive in a fixed
    order, so `'rendered'` only starts a grace window during which a later
    `error` overwrite still wins -- otherwise whichever event the poll
    happens to observe first decides the case, and a real visual failure
    can be missed purely by timing.
    """
    deadline = now() + timeout_seconds
    rendered_at: float | None = None
    result: str | None = None
    while now() < deadline:
        result = read_result()
        if isinstance(result, str) and result.startswith("error:"):
            return result
        if result == "rendered":
            if rendered_at is None:
                rendered_at = now()
            elif now() - rendered_at >= grace_seconds:
                return result
        sleep(poll_interval)
    return result


_ERROR_MODAL_SELECTORS = [
    ".ms-Dialog-content",
    ".errorDialog",
    "[data-testid='error-message']",
]


def _scan_for_error_modal(page: Any) -> bool:
    """Return True if Power BI's error modal is present anywhere on the
    page or inside any of its iframes."""
    for selector in _ERROR_MODAL_SELECTORS:
        if page.locator(selector).count() > 0:
            return True
    for frame in page.frames:
        with contextlib.suppress(Exception):
            if "ms-Dialog-content" in frame.content():
                return True
    return False


def _test_paginated_report(page: Any, case: dict[str, str]) -> None:
    """Embed a paginated (RDL) report and fail if an error modal is detected."""
    try:
        base_config = _embed_config_for_role(case.get("role", ""))
    except _NoEmbedConfigForRole as exc:
        error = f"{exc} (case {case.get('test_case')})"
        _write_result(_case_result_dir(case), "error", error)
        pytest.fail(error)
    if base_config is None:
        pytest.skip("PLAYWRIGHT_EMBED_CONFIG not set; run via invoke_playwright.py")

    config = dict(base_config)
    config["type"] = "report"
    # A parameterized case renders with its values applied at embed time --
    # the embed SDK's own parameterValues, a multi-value parameter repeated
    # once per value -- so it is an independent render, not a second pass
    # over the baseline's parameter pane.
    try:
        parameter_values = json.loads(case.get("report_parameters") or "[]")
    except json.JSONDecodeError:
        parameter_values = []
    if parameter_values:
        config["parameterValues"] = parameter_values

    result_dir = _case_result_dir(case)
    result_dir.mkdir(parents=True, exist_ok=True)

    rdl_wait_seconds = int(
        case.get("render_wait_seconds")
        or os.getenv("PLAYWRIGHT_RENDER_WAIT_SECONDS", "20")
    )

    console_logs, failed_requests = _start_event_capture(page)

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
    except Exception as exc:  # noqa: BLE001 - the embed script's own failure is the evidence
        _write_evidence(page, result_dir, console_logs, failed_requests)
        error = f"Failed to evaluate RDL embed script: {exc}"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

    page.wait_for_timeout(rdl_wait_seconds * 1000)

    # Give any in-flight network activity (the RDL data/parameter calls the
    # fixed wait above may have just missed) a bounded chance to settle
    # before scanning -- matches the validated reference implementation's
    # waitForLoadState('networkidle') between its own wait and its DOM scan.
    # Best-effort: background telemetry connections can keep the page from
    # ever going fully idle, so this must never turn into a hard failure.
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=5000)

    error_found = _scan_for_error_modal(page)

    _write_evidence(page, result_dir, console_logs, failed_requests)

    if error_found:
        error = "RDL error modal detected"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

    _write_result(result_dir, "pass")
