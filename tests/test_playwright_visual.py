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


def test_embed_config_for_role_raises_for_missing_role(monkeypatch) -> None:
    """A case whose role has no entry in PLAYWRIGHT_EMBED_CONFIGS fails
    loudly instead of silently reusing another role's token."""
    monkeypatch.setenv(
        "PLAYWRIGHT_EMBED_CONFIGS",
        json.dumps({"Manager": {"accessToken": "manager-token"}}),
    )
    monkeypatch.delenv("PLAYWRIGHT_EMBED_CONFIG", raising=False)

    with pytest.raises(_NoEmbedConfigForRole):
        _embed_config_for_role("Analyst")


def test_embed_config_for_role_returns_the_matching_entry(monkeypatch) -> None:
    """A case's own role picks its own embed config out of the role map."""
    monkeypatch.setenv(
        "PLAYWRIGHT_EMBED_CONFIGS",
        json.dumps({"Manager": {"accessToken": "manager-token"}}),
    )

    assert _embed_config_for_role("Manager") == {"accessToken": "manager-token"}


def test_embed_config_for_role_falls_back_to_single_role_env(monkeypatch) -> None:
    """A single-role run has no PLAYWRIGHT_EMBED_CONFIGS at all, and every
    case falls back to the one PLAYWRIGHT_EMBED_CONFIG regardless of role."""
    monkeypatch.delenv("PLAYWRIGHT_EMBED_CONFIGS", raising=False)
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))

    assert _embed_config_for_role("") == {"accessToken": "t"}


def _stub_powerbi_embed(page: Any, *, inject_error_modal: bool) -> None:
    """Replace the real Power BI JS client with a test double.

    Registered as an init script (before ``about:blank`` loads) so it wins
    over the real CDN library ``_test_paginated_report`` loads next --
    ``add_script_tag`` overwrites ``window.powerbi`` with the real bundle
    each time, so it must be neutered too. Avoids any real embed call: this
    is about proving the paginated code path waits the configured duration
    and then scans for the error-modal marker, not about a real Fabric
    backend.
    """
    modal_html = (
        "<div class='ms-Dialog-content'>Something went wrong</div>"
        if inject_error_modal
        else ""
    )
    page.add_init_script(
        "window.powerbi = { embed: () => {"
        f"document.body.insertAdjacentHTML('beforeend', {json.dumps(modal_html)});"
        "} };"
    )
    page.route(
        "https://cdn.jsdelivr.net/npm/powerbi-client@2.23.1/dist/powerbi.min.js",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
    )


def test_paginated_report_records_pass_when_no_error_modal_found(
    page, tmp_path: Path, monkeypatch
) -> None:
    """No error modal after the configured wait records a pass."""
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))
    _stub_powerbi_embed(page, inject_error_modal=False)

    case = {
        "test_case": "InvoiceRDL",
        "report_type": "paginated",
        "render_wait_seconds": "1",
    }

    _test_paginated_report(page, case)

    result = json.loads((_case_result_dir(case) / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "pass"


def _stub_powerbi_embed_with_parameter_panel(
    page: Any, *, param_name: str = "ReportParameter1", multi_value: bool = False
) -> None:
    """Replace the real Power BI JS client and, on embed, render a fake
    parameter panel that mimics the real Fluent UI structure found via live
    DOM recon against PaginatedExample-WithFilter/-WithMultiFilter: a
    combobox input (``#{name}-input``), its options
    (``[id^="{name}-list"]``, a multi-value combobox's first option titled
    "Select All"), and a submit button
    (``[data-testid="parameter-pane-submit-action"]``). Selecting the
    fake "2" option injects the error modal, simulating a filter value that
    only fails once actually applied -- the initial no-filter render stays
    clean.
    """
    options_html = (
        f"<div id='{param_name}-list0'>Select All</div>"
        f"<div id='{param_name}-list1'>2</div>"
        f"<div id='{param_name}-list2'>4</div>"
        if multi_value
        else f"<div id='{param_name}-list0'>2</div>"
        f"<div id='{param_name}-list1'>4</div>"
    )
    panel_html = (
        f"<input id='{param_name}-input' />"
        f"<div id='{param_name}-options' style='display:none'>{options_html}</div>"
        "<button data-testid='parameter-pane-submit-action'>View report</button>"
    )
    page.add_init_script(
        "window.powerbi = { embed: () => {"
        f"document.body.insertAdjacentHTML('beforeend', {json.dumps(panel_html)});"
        f"const opts = document.getElementById('{param_name}-options');"
        "document.getElementById("
        f"'{param_name}-input').addEventListener('click', () => {{"
        "opts.style.display = 'block';"
        "});"
        "opts.querySelectorAll('div').forEach((opt) => {"
        "opt.addEventListener('click', () => {"
        "if (opt.textContent === '2') {"
        "document.body.insertAdjacentHTML('beforeend', "
        "\"<div class='ms-Dialog-content'>Something went wrong</div>\");"
        "}"
        "});"
        "});"
        "} };"
    )
    page.route(
        "https://cdn.jsdelivr.net/npm/powerbi-client@2.23.1/dist/powerbi.min.js",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
    )


def test_paginated_report_applies_a_single_value_parameter_and_catches_a_filter_error(
    page, tmp_path: Path, monkeypatch
) -> None:
    """A report that renders clean with no filter, but declares a
    single-value parameter, gets that parameter applied and re-checked --
    catching an error that only the filtered render exposes."""
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))
    _stub_powerbi_embed_with_parameter_panel(page, multi_value=False)

    case = {
        "test_case": "WithFilter",
        "report_type": "paginated",
        "render_wait_seconds": "1",
        "report_parameters": json.dumps(
            [{"name": "ReportParameter1", "multi_value": False}]
        ),
    }

    with pytest.raises(pytest.fail.Exception, match="RDL error modal detected"):
        _test_paginated_report(page, case)

    result = json.loads((_case_result_dir(case) / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "error"


def test_paginated_report_applies_a_multi_value_parameter_skipping_select_all(
    page, tmp_path: Path, monkeypatch
) -> None:
    """A multi-value parameter's "Select All" option is skipped -- the first
    two real values are picked instead."""
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))
    _stub_powerbi_embed_with_parameter_panel(page, multi_value=True)

    case = {
        "test_case": "WithMultiFilter",
        "report_type": "paginated",
        "render_wait_seconds": "1",
        "report_parameters": json.dumps(
            [{"name": "ReportParameter1", "multi_value": True}]
        ),
    }

    with pytest.raises(pytest.fail.Exception, match="RDL error modal detected"):
        _test_paginated_report(page, case)


def test_paginated_report_with_no_declared_parameters_only_scans_once(
    page, tmp_path: Path, monkeypatch
) -> None:
    """No declared parameters -- behavior is unchanged: embed, wait, scan
    once. A clean render passes even though the stub's parameter panel
    (never opened) would have injected an error if clicked."""
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))
    _stub_powerbi_embed_with_parameter_panel(page, multi_value=False)

    case = {
        "test_case": "NoParameters",
        "report_type": "paginated",
        "render_wait_seconds": "1",
        "report_parameters": "",
    }

    _test_paginated_report(page, case)

    result = json.loads((_case_result_dir(case) / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "pass"


def test_paginated_report_records_error_when_modal_detected(
    page, tmp_path: Path, monkeypatch
) -> None:
    """An error modal found after the configured wait records an error."""
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))
    _stub_powerbi_embed(page, inject_error_modal=True)

    case = {
        "test_case": "InvoiceRDLBroken",
        "report_type": "paginated",
        "render_wait_seconds": "1",
    }

    with pytest.raises(pytest.fail.Exception, match="RDL error modal detected"):
        _test_paginated_report(page, case)

    result = json.loads((_case_result_dir(case) / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "error"


class _FakeClock:
    """Deterministic stand-in for time.monotonic()/time.sleep() in tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_wait_for_render_result_lets_a_delayed_error_overwrite_rendered() -> None:
    """`rendered` and a per-visual `error` are not guaranteed to arrive in a
    fixed order. A `rendered` read must not return immediately -- it has to
    give a later `error` overwrite a chance to win during the grace window."""
    clock = _FakeClock()
    reads = iter(["rendered", "rendered", 'error:{"message":"Missing_References"}'])

    result = _wait_for_render_result(
        lambda: next(reads),
        timeout_seconds=60,
        grace_seconds=2,
        poll_interval=1,
        now=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == 'error:{"message":"Missing_References"}'


def test_wait_for_render_result_returns_error_immediately_without_waiting_for_grace() -> None:
    """An error is terminal the moment it is seen -- no need to keep polling."""
    clock = _FakeClock()
    reads = iter(['error:{"message":"boom"}'])

    result = _wait_for_render_result(
        lambda: next(reads),
        timeout_seconds=60,
        grace_seconds=5,
        poll_interval=1,
        now=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == 'error:{"message":"boom"}'
    assert clock.now == 0.0


def test_wait_for_render_result_returns_rendered_once_grace_period_is_clean() -> None:
    """No error arrives during the grace window -- `rendered` is a genuine pass."""
    clock = _FakeClock()
    reads = iter(["rendered"] * 10)

    result = _wait_for_render_result(
        lambda: next(reads),
        timeout_seconds=60,
        grace_seconds=2,
        poll_interval=1,
        now=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result == "rendered"


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


TEST_CASES = _load_test_cases()


@pytest.mark.parametrize("case", TEST_CASES, ids=_test_case_id)
def test_report_visual_renders(page, case: dict[str, str]) -> None:
    """Embed a Power BI report and fail if an error event fires before rendered."""
    if not case:
        pytest.skip("Empty test case")

    report_type = case.get("report_type", "report")
    if report_type == "paginated":
        _test_paginated_report(page, case)
        return

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

    # Race rendered vs error, giving a delayed per-visual error a grace
    # window to overwrite an already-observed rendered (see
    # _wait_for_render_result).
    grace_ms = int(os.getenv("PLAYWRIGHT_VISUAL_ERROR_GRACE_MS", "5000"))
    result = _wait_for_render_result(
        lambda: page.evaluate("() => window.__pbiRenderResult"),
        timeout_seconds=timeout_ms / 1000.0,
        grace_seconds=grace_ms / 1000.0,
    )

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


def _apply_report_parameters(page: Any, parameters: list[dict[str, Any]]) -> bool:
    """Select real values for each declared report parameter and submit the
    panel, driving the report's own rendered parameter combobox the way a
    person would -- selectors confirmed via live DOM recon against
    PaginatedExample-WithFilter/-WithMultiFilter: a combobox input
    (``#{name}-input``), its options (``[id^="{name}-list"]``, with a
    multi-value combobox's first option titled "Select All"), and a submit
    button (``[data-testid="parameter-pane-submit-action"]``).

    A report renders clean with no parameter applied -- the error this
    exists to catch (e.g. a FilterExpression type mismatch) only appears
    once a real value is actually selected, which nothing before this
    function ever did. Returns True if any parameter's control was found
    and interacted with, so the caller knows whether a second render check
    is warranted at all.
    """
    applied = False
    for parameter in parameters:
        name = parameter.get("name", "")
        if not name:
            continue
        take = 2 if parameter.get("multi_value") else 1
        for frame in page.frames:
            combo_input = frame.locator(f"#{name}-input")
            if combo_input.count() == 0:
                continue
            with contextlib.suppress(Exception):
                combo_input.first.click(timeout=3000)
                frame.wait_for_timeout(500)
                options = frame.locator(f"[id^='{name}-list']").filter(
                    has_not_text="Select All"
                )
                for i in range(min(options.count(), take)):
                    options.nth(i).click(timeout=3000)
                page.keyboard.press("Escape")
                submit = frame.locator(
                    "[data-testid='parameter-pane-submit-action']"
                )
                if submit.count() > 0:
                    submit.first.click(timeout=3000)
                applied = True
            break
    return applied


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

    result_dir = _case_result_dir(case)
    result_dir.mkdir(parents=True, exist_ok=True)

    rdl_wait_seconds = int(
        case.get("render_wait_seconds")
        or os.getenv("PLAYWRIGHT_RENDER_WAIT_SECONDS", "20")
    )

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

    # Give any in-flight network activity (the RDL data/parameter calls the
    # fixed wait above may have just missed) a bounded chance to settle
    # before scanning -- matches the validated reference implementation's
    # waitForLoadState('networkidle') between its own wait and its DOM scan.
    # Best-effort: background telemetry connections can keep the page from
    # ever going fully idle, so this must never turn into a hard failure.
    with contextlib.suppress(Exception):
        page.wait_for_load_state("networkidle", timeout=5000)

    error_found = _scan_for_error_modal(page)

    # A clean no-filter render says nothing about a parameter's own
    # FilterExpression -- that only breaks once a real value is selected,
    # which the embed above never did. Applying the report's own declared
    # parameters and re-checking is what catches it (Paginated Report
    # Parameter Testing epic).
    if not error_found:
        try:
            parameters = json.loads(case.get("report_parameters") or "[]")
        except json.JSONDecodeError:
            parameters = []
        if parameters and _apply_report_parameters(page, parameters):
            page.wait_for_timeout(rdl_wait_seconds * 1000)
            with contextlib.suppress(Exception):
                page.wait_for_load_state("networkidle", timeout=5000)
            error_found = _scan_for_error_modal(page)

    _write_evidence(page, result_dir, console_logs, failed_requests)

    if error_found:
        error = "RDL error modal detected"
        _write_result(result_dir, "error", error)
        pytest.fail(error)

    _write_result(result_dir, "pass")
