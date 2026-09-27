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
