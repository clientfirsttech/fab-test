"""pytest-playwright spec for dynamic Power BI report visual validation.

Tests are parametrized from ``test-cases.csv`` produced by ``invoke_playwright.py``.
The spec loads each row, fetches an embed token and embed URL, injects the
Power BI JavaScript client from CDN, embeds the report, and races the
``rendered`` event against ``error`` events on ``document.body``.

Ships inside the installed package rather than under ``tests/`` (Playwright
CI Guide epic, Render Spec Packaging task) -- a ``pip install cft-fab-test``
consumer has no checkout of this repository's ``tests/`` directory for
``invoke_playwright.py`` to point pytest at, so every real run failed
outright ("ERROR: usage: python -m pytest") the moment it was run from
outside this repository. Not collected by this repository's own test suite
(``testpaths = tests`` in pytest.ini); ``invoke_playwright.py`` invokes it
directly by its installed path with an explicit ``-m playwright`` selector.
Deliberately named without a ``test_`` prefix so nothing about the filename
suggests it belongs to a discovery pattern -- pytest collects an explicitly
given file path regardless of ``python_files``.

The embed/race/evidence mechanics live in ``render_helpers.py``, split out
so this function stays a short, readable sequence of steps rather than one
large one -- each helper ends the test itself (``pytest.fail``/``skip``) on
its own failure mode, so this function has nothing left to branch on.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from .render_helpers import (
    _case_result_dir,
    _embed_interactive_report,
    _finish_interactive_case,
    _load_test_cases,
    _resolve_case_config,
    _start_event_capture,
    _test_case_id,
    _test_paginated_report,
    _wait_for_render_result,
)

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

    config = _resolve_case_config(case)
    result_dir = _case_result_dir(case)
    result_dir.mkdir(parents=True, exist_ok=True)

    timeout_ms = int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "60000"))
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"
    console_logs, failed_requests = _start_event_capture(page)

    _embed_interactive_report(page, config, result_dir, console_logs, failed_requests)

    # Race rendered vs error, giving a delayed per-visual error a grace
    # window to overwrite an already-observed rendered (see
    # _wait_for_render_result).
    grace_ms = int(os.getenv("PLAYWRIGHT_VISUAL_ERROR_GRACE_MS", "5000"))
    result = _wait_for_render_result(
        lambda: page.evaluate("() => window.__pbiRenderResult"),
        timeout_seconds=timeout_ms / 1000.0,
        grace_seconds=grace_ms / 1000.0,
    )

    _finish_interactive_case(
        page,
        result,
        timeout_ms=timeout_ms,
        headless=headless,
        result_dir=result_dir,
        console_logs=console_logs,
        failed_requests=failed_requests,
    )
