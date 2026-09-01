"""Contract tests for Playwright test_results reporting (deep links, rows).

Split out of test_invoke_playwright.py (module budget ratchet) rather than
grown in place -- these three tests were added together for the paginated
report reporting requirements (Paginated Report Testing epic) and stand on
their own with no shared fixtures from the parent file.
"""

from __future__ import annotations

from pathlib import Path

from fab_test.scripts.invoke_playwright import (
    _report_deep_link,
    _test_results_rows,
)
from fab_test.scripts.playwright_validation.test_cases import TestCase


def test_report_deep_link_is_empty_for_a_paginated_case() -> None:
    """A paginated case never gets a Report Page link -- RDL reports use a
    different URL shape in the Fabric portal that this builder doesn't know."""
    case = TestCase(
        test_case="InvoiceRDL",
        report_name="Invoice RDL",
        report_id="rdl-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="",
        user_name="",
        role="",
        report_type="paginated",
    )

    assert _report_deep_link(case, cloud="public") == {}


def test_results_rows_keep_empty_page_and_bookmark_for_a_paginated_case(
    tmp_path: Path,
) -> None:
    """A paginated case's row keeps page_name/bookmark_name as empty strings
    (not dropped) and never gets a report_link -- the row shape other
    analyzers rely on stays intact for either report type."""
    case = TestCase(
        test_case="InvoiceRDL",
        report_name="Invoice RDL",
        report_id="rdl-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="",
        user_name="",
        role="",
        report_type="paginated",
    )

    rows = _test_results_rows([case], tmp_path, overall_success=True)

    assert len(rows) == 1
    assert rows[0]["page_name"] == ""
    assert rows[0]["bookmark_name"] == ""
    assert rows[0]["report_link"] == {}
    assert "page_name" in rows[0]
    assert "bookmark_name" in rows[0]


def test_results_rows_mix_interactive_and_paginated_cases_in_one_run(
    tmp_path: Path,
) -> None:
    """A run mixing an interactive and a paginated report produces a row
    for each, with no special-casing needed to include both."""
    interactive_case = TestCase(
        test_case="SalesReport_default-page_no-bookmark",
        report_name="SalesReport",
        report_id="rpt-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="ds-1",
        user_name="",
        role="",
    )
    paginated_case = TestCase(
        test_case="InvoiceRDL",
        report_name="Invoice RDL",
        report_id="rdl-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="",
        user_name="",
        role="",
        report_type="paginated",
    )

    rows = _test_results_rows(
        [interactive_case, paginated_case], tmp_path, overall_success=True
    )

    assert [row["test_name"] for row in rows] == [
        "SalesReport_default-page_no-bookmark",
        "InvoiceRDL",
    ]
    assert all(row["status"] == "pass" for row in rows)
