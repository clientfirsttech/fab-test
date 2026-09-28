"""Contract tests for Playwright's accurate per-case results (Playwright Report Detail epic).

Scope
-----
Before this, a failing run tagged *every* generated case with the same
generic message, and a passing run recorded zero `test_results` -- a
report with 5 pages and 1 real failure said "5 finding(s)", all
identical. The pytest spec now writes a `result.json` per case
(`render_helpers.py::_write_result`); this module covers
the wrapper side that reads it back into an accurate, per-case
`test_results` list (mirroring BPA/PBIR's own `test_results`) and derives
`findings` from only the cases that actually failed.

Always passes on any machine: no browser or Power BI service is invoked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fab_test.scripts.invoke_playwright import main
from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig
from fab_test.scripts.playwright_validation.power_bi_api import EmbedContext

pytestmark = pytest.mark.playwright


def _config() -> PlaywrightValidationConfig:
    return PlaywrightValidationConfig(
        workspace_id="ws-1",
        report_id="rpt-1",
        report_name="SalesReport",
        dataset_id="ds-1",
        page_ids=["page1", "page2"],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=60,
        headless=True,
    )


def _write_case_result(
    test_cases_dir: Path, case_id: str, status: str, error: str = "", evidence: bool = False
) -> None:
    case_dir = test_cases_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "result.json").write_text(
        json.dumps({"status": status, "error": error}), encoding="utf-8"
    )
    if evidence:
        (case_dir / "screenshot.png").write_bytes(b"fake-png-bytes")
        (case_dir / "event_log.json").write_text("[]", encoding="utf-8")


def _run_main(tmp_path: Path, output_path: Path, test_cases_dir: Path):
    embed_context = EmbedContext(
        embed_url="https://app.powerbi.com/embed",
        embed_token="token",
        report_id="rpt-1",
        dataset_id="ds-1",
    )
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

    with (
        patch(
            "fab_test.scripts.invoke_playwright.load_config",
            return_value=_config(),
        ),
        patch(
            "fab_test.scripts.playwright_validation.discovery.get_embed_context",
            return_value=embed_context,
        ),
        patch(
            "fab_test.scripts.invoke_playwright._run_pytest",
            return_value=completed,
        ),
        patch(
            "fab_test.scripts.invoke_playwright._repo_root",
            return_value=tmp_path,
        ),
    ):
        code = main(
            [
                "--env-file",
                ".env",
                "--output-path",
                str(output_path),
                "--test-cases-dir",
                str(test_cases_dir),
            ]
        )
    return code, json.loads(output_path.read_text(encoding="utf-8"))


def test_only_the_case_that_actually_failed_is_reported_as_failed(tmp_path: Path):
    """Given one real failure among several cases, only that case should read as failed."""
    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    test_cases_dir.mkdir()
    _write_case_result(test_cases_dir, "SalesReport_page1_no-bookmark", "pass")
    _write_case_result(
        test_cases_dir,
        "SalesReport_page2_no-bookmark",
        "error",
        error="Power BI error event fired: {'level':'Error'}",
    )

    _code, data = _run_main(tmp_path, output_path, test_cases_dir)

    assert len(data["test_results"]) == 2, "one row per generated case"
    assert len(data["findings"]) == 1, "findings stays limited to the case that really failed"
    by_case = {r["test_name"]: r for r in data["test_results"]}
    assert by_case["SalesReport_page1_no-bookmark"]["status"] == "pass"
    assert by_case["SalesReport_page2_no-bookmark"]["status"] == "error"


def test_the_failed_findings_message_is_the_cases_real_error_not_a_generic_one(tmp_path: Path):
    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    test_cases_dir.mkdir()
    _write_case_result(test_cases_dir, "SalesReport_page1_no-bookmark", "pass")
    _write_case_result(
        test_cases_dir,
        "SalesReport_page2_no-bookmark",
        "error",
        error="Report did not render within 60000ms",
    )

    _code, data = _run_main(tmp_path, output_path, test_cases_dir)

    finding = data["findings"][0]
    assert finding["object"] == "SalesReport_page2_no-bookmark"
    assert finding["message"] == "Report did not render within 60000ms"


def test_a_case_with_no_result_json_falls_back_to_the_overall_outcome(tmp_path: Path):
    """A case the pytest process never reached still gets a row, not a silent drop."""
    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    test_cases_dir.mkdir()
    # Neither case writes a result.json -- overall run failed (returncode=1).

    _code, data = _run_main(tmp_path, output_path, test_cases_dir)

    assert len(data["test_results"]) == 2
    assert all(row["status"] == "error" for row in data["test_results"])


def test_test_results_carry_the_cases_evidence_paths(tmp_path: Path):
    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    test_cases_dir.mkdir()
    _write_case_result(test_cases_dir, "SalesReport_page1_no-bookmark", "pass")
    _write_case_result(
        test_cases_dir,
        "SalesReport_page2_no-bookmark",
        "error",
        error="timed out",
        evidence=True,
    )

    _code, data = _run_main(tmp_path, output_path, test_cases_dir)

    by_case = {r["test_name"]: r for r in data["test_results"]}
    assert by_case["SalesReport_page1_no-bookmark"]["evidence"] == {}
    failed_evidence = by_case["SalesReport_page2_no-bookmark"]["evidence"]
    assert "screenshot" in failed_evidence
    assert failed_evidence["screenshot"].endswith("screenshot.png")
    assert "event_log" in failed_evidence
    assert failed_evidence["event_log"].endswith("event_log.json")


def test_test_results_carry_a_deep_link_to_the_report_page(tmp_path: Path):
    """Each row should link straight back to the report page it validated."""
    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    test_cases_dir.mkdir()
    _write_case_result(test_cases_dir, "SalesReport_page1_no-bookmark", "pass")
    _write_case_result(test_cases_dir, "SalesReport_page2_no-bookmark", "pass")

    _code, data = _run_main(tmp_path, output_path, test_cases_dir)

    by_case = {r["test_name"]: r for r in data["test_results"]}
    link = by_case["SalesReport_page1_no-bookmark"]["report_link"]
    assert link["href"] == "https://app.powerbi.com/groups/ws-1/reports/rpt-1/page1"
    assert link["label"] == "page1"


def test_report_html_links_to_the_reports_own_page(tmp_path: Path, monkeypatch):
    """--report should produce a page whose Report Page column links to the live report."""
    monkeypatch.setenv("ANALYZER_REPORT", "1")
    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    test_cases_dir.mkdir()
    _write_case_result(test_cases_dir, "SalesReport_page1_no-bookmark", "pass")
    _write_case_result(test_cases_dir, "SalesReport_page2_no-bookmark", "pass")

    _code, data = _run_main(tmp_path, output_path, test_cases_dir)

    report_path = Path(data["native_html_output_path"])
    html = report_path.read_text(encoding="utf-8")
    assert "Report Page" in html
    assert 'href="https://app.powerbi.com/groups/ws-1/reports/rpt-1/page1"' in html


def test_report_html_links_to_a_failed_cases_evidence(tmp_path: Path, monkeypatch):
    """--report should produce a page whose evidence column links to the real file."""
    monkeypatch.setenv("ANALYZER_REPORT", "1")
    output_path = tmp_path / "envelope.json"
    test_cases_dir = tmp_path / "test-cases"
    test_cases_dir.mkdir()
    _write_case_result(test_cases_dir, "SalesReport_page1_no-bookmark", "pass")
    _write_case_result(
        test_cases_dir,
        "SalesReport_page2_no-bookmark",
        "error",
        error="timed out",
        evidence=True,
    )

    _code, data = _run_main(tmp_path, output_path, test_cases_dir)

    report_path = Path(data["native_html_output_path"])
    assert report_path.is_file()
    html = report_path.read_text(encoding="utf-8")
    assert "screenshot.png" in html
    assert '<a href="' in html


def _paginated_case(parameters: str = "[]"):
    from fab_test.scripts.playwright_validation.test_cases import TestCase

    return TestCase(
        test_case="Invoice_params-Region-East" if parameters != "[]" else "Invoice",
        report_name="Invoice",
        report_id="rpt-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="ds-1",
        user_name="",
        role="",
        report_type="paginated",
        report_parameters=parameters,
    )


def test_a_row_names_the_parameter_values_its_case_tested(tmp_path: Path) -> None:
    """Given a parameterized paginated case, should carry its values in a
    `parameters` field -- the only thing telling it apart from its baseline."""
    from fab_test.scripts.invoke_playwright import _test_results_rows

    parameterized = _paginated_case(json.dumps([{"name": "Region", "value": "East"}]))
    rows = _test_results_rows(
        [_paginated_case(), parameterized], tmp_path, overall_success=True
    )

    assert [row["parameters"] for row in rows] == [[], [{"name": "Region", "value": "East"}]]


def test_a_case_that_never_ran_records_why_not_rendered(tmp_path: Path) -> None:
    """Given a case with no result of its own because the run failed before it
    (an embed-token error), should record that failure as `actual` -- never
    `rendered` beside an `error` status."""
    from fab_test.scripts.invoke_playwright import _test_results_rows

    rows = _test_results_rows(
        [_paginated_case()],
        tmp_path,
        overall_success=False,
        fallback_error="Power BI API error: At least one dataset is required",
    )

    assert rows[0]["status"] == "error"
    assert rows[0]["actual"] == "Power BI API error: At least one dataset is required"
