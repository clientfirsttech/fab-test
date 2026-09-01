"""Contract tests for the full test-results table's search and sort (Search and Sort epic).

Scope
-----
The status filter (Human-Readable Reports §4) stays pure CSS. Search and
column sort are the one place the renderer emits an inline `<script>`; this
module covers two different things:

- The static contract: exactly where the script does and does not appear,
  and that it never references anything outside the page.
- The actual interactive behavior, exercised in a real browser via
  pytest-playwright rather than by re-implementing the script's logic in
  Python -- a mock of "does the click handler sort" would only prove the
  mock does what the mock does.

The browser tests use `page.set_content`, so they render the exact string
`render_report` produced and never touch the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fab_test.scripts._report_html import render_index, render_report
from tests.conftest import (
    _BPA_FAILED_RULE,
    _BPA_PASSED_RULE,
    _envelope,
    _envelope_with_test_results,
)

_BPA_WARNING_RULE = {
    "RuleName": "Consider hiding unused columns",
    "RuleID": "MAINT_07",
    "Severity": "warning",
    "Category": "Maintenance",
    "ObjectName": "Sales[InternalKey]",
    "status": "warning",
}


# --------------------------------------------------------------------------- #
# Static contract: where the script appears, and its no-external-reference rule
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_full_list_script_has_no_external_references():
    """Inline script for search/sort is permitted; external references are not."""
    html = render_report(
        _envelope_with_test_results([_BPA_PASSED_RULE, _BPA_FAILED_RULE])
    )

    assert "<script>" in html
    for forbidden in ("http://", "https://", "<script src", "<link ", "fetch("):
        assert forbidden not in html, f"external reference: {forbidden}"


@pytest.mark.fab_test
def test_legacy_findings_only_report_emits_no_script():
    """An analyzer with no test_results gets the original findings table, untouched."""
    html = render_report(_envelope([_BPA_FAILED_RULE]))

    assert "<script" not in html
    assert 'class="search-box"' not in html


@pytest.mark.fab_test
def test_run_index_stays_untouched_by_search_and_sort():
    """The run index links to reports; it renders no rows of its own to search or sort."""
    html = render_index(
        [{"analyzer": "bpa", "artifact": "Sales.SemanticModel"}], base_dir=Path(".")
    )

    assert "<script" not in html
    assert 'class="search-box"' not in html


# --------------------------------------------------------------------------- #
# Real-browser behavior (pytest-playwright's `page` fixture)
# --------------------------------------------------------------------------- #


def _three_row_html() -> str:
    return render_report(
        _envelope_with_test_results(
            [_BPA_PASSED_RULE, _BPA_FAILED_RULE, _BPA_WARNING_RULE]
        )
    )


def _rule_names(page) -> list[str]:
    """Rule names of currently *visible* rows -- a hidden row's own innerText
    is unreliable across browsers, so filter with the `:visible` pseudo-class
    rather than reading text off rows the reader can't actually see."""
    return page.locator("table tbody tr:visible td:nth-child(1)").all_inner_texts()


@pytest.mark.playwright
def test_clicking_a_column_header_sorts_then_reverses(page):
    page.set_content(_three_row_html())

    page.click("table thead th:nth-child(1)")
    ascending = _rule_names(page)
    assert ascending == sorted(ascending)

    page.click("table thead th:nth-child(1)")
    descending = _rule_names(page)
    assert descending == sorted(descending, reverse=True)


@pytest.mark.playwright
def test_search_box_hides_non_matching_rows_and_restores_on_clear(page):
    page.set_content(_three_row_html())

    page.fill(".search-box", "descriptions")
    assert _rule_names(page) == ["Add descriptions to measures"]

    page.fill(".search-box", "")
    assert sorted(_rule_names(page)) == sorted(
        [r["RuleName"] for r in (_BPA_PASSED_RULE, _BPA_FAILED_RULE, _BPA_WARNING_RULE)]
    )


@pytest.mark.playwright
def test_search_narrows_within_the_active_status_filter(page):
    page.set_content(_three_row_html())

    # The radio itself is visually hidden (CSS drives it via its label), so
    # the reader -- and this test -- interacts with the label, not the input.
    page.click('label[for="f-error"]')
    page.fill(".search-box", "hiding")  # matches the warning row's name, not the error row's
    assert _rule_names(page) == []


@pytest.mark.playwright
def test_search_and_filter_combining_to_zero_rows_shows_empty_message(page):
    page.set_content(_three_row_html())

    assert page.locator(".empty-msg").is_hidden()

    page.fill(".search-box", "does-not-exist-anywhere")
    assert page.locator(".empty-msg").is_visible()

    page.fill(".search-box", "")
    assert page.locator(".empty-msg").is_hidden()


@pytest.mark.playwright
def test_clicking_a_column_header_shows_and_toggles_the_sort_arrow(page):
    page.set_content(_three_row_html())
    header = page.locator("table thead th:nth-child(1)")

    header.click()
    assert "▲" in header.inner_text()

    header.click()
    assert "▼" in header.inner_text()


@pytest.mark.playwright
def test_sorting_a_different_column_clears_the_previous_arrow(page):
    page.set_content(_three_row_html())
    first = page.locator("table thead th:nth-child(1)")
    second = page.locator("table thead th:nth-child(2)")

    first.click()
    assert "▲" in first.inner_text()

    second.click()
    assert "▲" not in first.inner_text()
    assert "▼" not in first.inner_text()
    assert "▲" in second.inner_text()


@pytest.mark.playwright
def test_no_header_shows_an_arrow_before_any_sort(page):
    page.set_content(_three_row_html())

    headers = page.locator("table thead th").all_inner_texts()
    assert all("▲" not in h and "▼" not in h for h in headers)


@pytest.mark.playwright
def test_sorting_does_not_disturb_the_active_filter_or_search(page):
    page.set_content(_three_row_html())

    page.fill(".search-box", "e")  # matches all three rule names
    page.click("table thead th:nth-child(1)")

    assert sorted(_rule_names(page)) == sorted(
        [r["RuleName"] for r in (_BPA_PASSED_RULE, _BPA_FAILED_RULE, _BPA_WARNING_RULE)]
    )
