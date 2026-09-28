"""Unit tests for the Playwright render spec's library code.

Scope
-----
Exercises `render_helpers.py` (embed-config-by-role, the render/error race,
result recording, and paginated-report parameter handling) with stubbed
Power BI clients -- no real Fabric workspace or embed token. The pytest
module that actually runs against a live workspace,
`fab_test.scripts.playwright_validation.render_spec`, ships inside the
installed package rather than under `tests/` (Playwright CI Guide epic,
Render Spec Packaging task) so a `pip install fab-test` consumer has
something for `invoke_playwright.py` to point pytest at.

    pytest -m playwright tests/test_playwright_visual.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fab_test.scripts.playwright_validation.render_helpers import (
    _case_result_dir,
    _embed_config_for_role,
    _NoEmbedConfigForRole,
    _test_paginated_report,
    _wait_for_render_result,
)

pytestmark = pytest.mark.playwright


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


def _stub_powerbi_embed_failing_on_parameters(page: Any) -> None:
    """Replace the real Power BI JS client with one that records the embed
    config it was given, and injects the error modal only when that config
    carries ``parameterValues`` -- a report that renders clean unfiltered and
    breaks once a real value is applied, like PaginatedExample-WithMultiFilter.
    """
    page.add_init_script(
        "window.powerbi = { embed: (el, config) => {"
        "window.__embedConfig = config;"
        "if (config.parameterValues && config.parameterValues.length) {"
        "document.body.insertAdjacentHTML('beforeend', "
        "\"<div class='ms-Dialog-content'>Something went wrong</div>\");"
        "}"
        "} };"
    )
    page.route(
        "https://cdn.jsdelivr.net/npm/powerbi-client@2.23.1/dist/powerbi.min.js",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
    )


def test_paginated_case_passes_its_parameter_set_at_embed_time(
    page, tmp_path: Path, monkeypatch
) -> None:
    """Given a parameterized case, should hand its values to the embed as
    ``parameterValues`` -- the render is its own case, not a second pass
    clicking the parameter pane -- and fail on the error that render shows."""
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))
    _stub_powerbi_embed_failing_on_parameters(page)
    parameter_set = [
        {"name": "ReportParameter1", "value": "2"},
        {"name": "ReportParameter1", "value": "4"},
    ]

    case = {
        "test_case": "WithMultiFilter_params",
        "report_type": "paginated",
        "render_wait_seconds": "1",
        "report_parameters": json.dumps(parameter_set),
    }

    with pytest.raises(pytest.fail.Exception, match="RDL error modal detected"):
        _test_paginated_report(page, case)

    assert page.evaluate("() => window.__embedConfig.parameterValues") == parameter_set


def test_paginated_baseline_case_embeds_with_no_parameter_values(
    page, tmp_path: Path, monkeypatch
) -> None:
    """Given a baseline case, should embed with no ``parameterValues`` at all,
    and pass on a clean render -- its parameterized sibling is what tests
    the values."""
    monkeypatch.setenv("PLAYWRIGHT_RESULTS_ROOT", str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_EMBED_CONFIG", json.dumps({"accessToken": "t"}))
    _stub_powerbi_embed_failing_on_parameters(page)

    case = {
        "test_case": "WithMultiFilter",
        "report_type": "paginated",
        "render_wait_seconds": "1",
        "report_parameters": "[]",
    }

    _test_paginated_report(page, case)

    assert page.evaluate("() => 'parameterValues' in window.__embedConfig") is False
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
