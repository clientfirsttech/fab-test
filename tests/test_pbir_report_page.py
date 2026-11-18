"""fab-test's own `--report` page for a PBIR run (PBIR Slicer Default State epic).

Every other analyzer's report is fab-test's page (bpa, pql_test, rdl): a
header, the run's meta line and one filterable table. PBIR's is the same page:
one table for both rule sets, a Source column naming where each row came
from, a line above it with where the contract lives, and PBIR Inspector's own
TestRun.html collapsed at the bottom, framed rather than restyled.
"""

from pathlib import Path

import pytest

from fab_test.scripts._pbir_report_page import render_pbir_report, rule_rows, write_pbir_report

_FOUND = "'Fiscal Calendar'[Half Year] opens with ['2025 H2']; the contract expects 2026 H2"
_SUMMARY = {
    "file": "Sales.Report.odcs.yaml",
    "rules": [
        {"id": "alignment-default", "page": "Standard Slicers", "field": "'AlignmentDim'[Alignment]",
         "check": "selected", "expected": ["Bad"], "severity": "error"},
        {"id": "half-year-current", "page": "Standard Slicers", "field": "'Fiscal Calendar'[Half Year]",
         "check": "selected", "expected": ["2026 H2"], "severity": "warning"},
    ],
    "navigators": [{"id": "page-1-navigator", "page": "Page 1", "expected": "Bookmark 2", "severity": "error"}],
}
_RESULTS = [  # envelope test_results, tagged with their source; one rule yields a row per page it ran on
    {"rule": "CONTRACT.alignment-default", "severity": "error", "object": "Standard Slicers", "message": "",
     "status": "pass", "source": "contract"},
    {"rule": "CONTRACT.half-year-current", "severity": "warning", "object": "Standard Slicers", "message": "",
     "status": "pass", "source": "contract"},
    {"rule": "CONTRACT.half-year-current", "severity": "warning", "object": "Page 2", "message": _FOUND,
     "status": "warning", "source": "contract"},
    {"rule": "CONTRACT.page-1-navigator", "severity": "error", "object": "Page 1", "message": "",
     "status": "pass", "source": "contract"},
    {"rule": "CONTRACT.page.Standard Slicers", "severity": "error", "object": "", "message": "",
     "status": "pass", "source": "contract"},
    {"rule": "SHOW_VISUAL_HEADER", "severity": "error", "object": "Page 1 > Table", "message": "header hidden",
     "status": "error", "source": "rules"},
    {"rule": "DISABLE_DROP_SHADOW", "severity": "warning", "object": "Page 1", "message": "",
     "status": "pass", "source": "rules"},
]
_PAIRED = ""
_NONE = "no *.odcs.yaml under --artifact-dir has fabTestReport abc; only the PBIR rules run"
_CONTRACT_SOURCE = "Slicer contract (Sales.Report.odcs.yaml)"


def _envelope(results=_RESULTS, contract=_SUMMARY) -> dict:
    envelope = {"analyzer": "pbir_inspector", "artifact_path": "fabric-artifacts/Sales.Report", "status": "failed",
                "message": "PBIR Inspector found 2 finding(s)", "rules_file": "rules/pbir.json",
                "findings": [r for r in results if r["status"] != "pass"], "test_results": results}
    if contract is not None:
        envelope["contract"] = contract
    return envelope


def _page(tmp_path: Path, envelope=None, note=_PAIRED, inspector="native.json/TestRun.html") -> str:
    return render_pbir_report(envelope or _envelope(), note, tmp_path / inspector if inspector else None,
                              base_dir=tmp_path)


def _between(page: str, start: str, end: str) -> str:
    return page[page.index(start):page.index(end, page.index(start))]


def _sources(page: str) -> str:
    return _between(page, 'id="results"', "</p>")


def _table(page: str) -> str:
    return _between(page, "<table>", "</table>")


def _row(page: str, rule: str, source: str = _CONTRACT_SOURCE) -> str:
    start = page.index(f"<td>{source}</td><td>{rule}</td>")
    return page[page.rindex("<tr", 0, start):page.index("</tr>", start)]


@pytest.mark.pbir
def test_given_a_run_should_be_the_page_every_other_analyzer_gets(tmp_path):
    page = _page(tmp_path)

    assert page.startswith("<!DOCTYPE html>")
    assert "<h1>fab-test pbir_inspector</h1>" in page
    assert "<code>fabric-artifacts/Sales.Report</code> — status: failed" in page
    assert page.count('class="filter-bar"') == 1 and page.count("<table>") == 1     # bpa's one filterable table


@pytest.mark.pbir
def test_given_both_rule_sets_should_name_each_rows_source_in_one_table(tmp_path):
    table = _table(_page(tmp_path))

    assert ("<th>Source</th><th>Rule</th><th>Severity</th><th>Object</th><th>Message</th><th>Status</th>"
            in table)
    assert f"<td>{_CONTRACT_SOURCE}</td><td>CONTRACT.alignment-default</td>" in table
    assert "<td>PBIR rules</td><td>SHOW_VISUAL_HEADER</td>" in table
    assert "<td>PBIR rules</td><td>CONTRACT." not in table


@pytest.mark.pbir
def test_given_a_contract_should_say_where_it_lives_and_how_each_rule_set_did(tmp_path):
    sources = _sources(_page(tmp_path))

    assert ("Slicer contract: <code>Sales.Report.odcs.yaml</code> · 2 slicer checks, 1 bookmark navigator · "
            "1 failed") in sources
    assert "PBIR rules: 2 results · 1 failed" in sources


@pytest.mark.pbir
def test_given_every_check_passed_should_say_so(tmp_path):
    results = [r for r in _RESULTS if r["status"] == "pass"]

    sources = _sources(_page(tmp_path, _envelope(results)))

    assert "1 bookmark navigator · all passed" in sources and "PBIR rules: 1 result · all passed" in sources


@pytest.mark.pbir
def test_given_pbir_inspector_ran_nothing_should_not_say_all_passed(tmp_path):
    sources = _sources(_page(tmp_path, _envelope(results=[])))

    assert "1 bookmark navigator · nothing ran" in sources and "PBIR rules: 0 results · nothing ran" in sources
    assert "all passed" not in sources


@pytest.mark.pbir
def test_given_some_contract_checks_did_not_run_should_count_them(tmp_path):
    results = [r for r in _RESULTS if r["rule"] in ("CONTRACT.alignment-default", "DISABLE_DROP_SHADOW")]

    sources = _sources(_page(tmp_path, _envelope(results)))

    assert "1 bookmark navigator · 1 passed, 2 not run" in sources


@pytest.mark.pbir
def test_given_html_in_a_contract_file_name_should_escape_it(tmp_path):
    contract = {**_SUMMARY, "file": "Sales<img src=x>.Report.odcs.yaml"}

    page = _page(tmp_path, _envelope(contract=contract))

    assert "<img" not in page
    assert "<td>Slicer contract (Sales&lt;img src=x&gt;.Report.odcs.yaml)</td>" in page              # Source
    assert "<code>Sales&lt;img src=x&gt;.Report.odcs.yaml</code>" in page                           # its path


@pytest.mark.pbir
def test_given_a_contract_check_should_show_its_worst_result_and_what_it_found(tmp_path):
    failed = _row(_page(tmp_path), "CONTRACT.half-year-current")

    assert 'class="warning" data-status="warning"' in failed
    assert "<td>Standard Slicers</td>" in failed
    assert "opens with [&#x27;2025 H2&#x27;]; the contract expects 2026 H2" in failed
    assert "<td>WARNING</td>" in failed


@pytest.mark.pbir
def test_given_a_passing_contract_check_should_show_what_it_expects(tmp_path):
    page = _page(tmp_path)

    assert "&#x27;AlignmentDim&#x27;[Alignment] opens with Bad" in _row(page, "CONTRACT.alignment-default")
    assert 'data-status="pass"' in _row(page, "CONTRACT.alignment-default")
    assert "bookmark navigator opens with Bookmark 2" in _row(page, "CONTRACT.page-1-navigator")
    assert "the page exists" in _row(page, "CONTRACT.page.Standard Slicers")


@pytest.mark.pbir
@pytest.mark.parametrize("check, expected, shown", [
    ("selected", "all", "opens with Select all"), ("selected", [], "opens with nothing ticked"),
    ("contains", ["Wolverine"], "opens containing Wolverine"), ("contains", [], "opens with nothing typed"),
    ("range", {"from": "1939-10-01", "to": "1951-08-27"}, "opens from 1939-10-01 to 1951-08-27"),
    ("range", {"to": "2026-10-28"}, "opens up to 2026-10-28"),
    ("relative", {"range": "Last", "duration": 20, "period": "Calendar Months"}, "opens with Last 20 Calendar Months"),
])
def test_given_each_kind_of_check_should_say_what_it_expects_in_words(tmp_path, check, expected, shown):
    summary = {"file": "c.odcs.yaml", "navigators": [], "rules": [
        {"id": "r", "page": "P", "field": "'T'[C]", "check": check, "expected": expected, "severity": "error"}]}

    row = _row(_page(tmp_path, _envelope(results=[], contract=summary)), "CONTRACT.r", "Slicer contract (c.odcs.yaml)")

    assert f"&#x27;T&#x27;[C] {shown}" in row and 'data-status="skip"' in row      # not run: no page matched


@pytest.mark.pbir
def test_given_no_contract_should_say_why_and_still_list_the_pbir_rules(tmp_path):
    rules_only = [r for r in _RESULTS if r["source"] == "rules"]

    page = _page(tmp_path, _envelope(rules_only, contract=None), note=_NONE)

    assert ("Slicer contract: none paired: no *.odcs.yaml under --artifact-dir has fabTestReport abc; "
            "only the PBIR rules run") in _sources(page)
    assert "Slicer contract (" not in _table(page)
    assert "<td>PBIR rules</td><td>SHOW_VISUAL_HEADER</td>" in _table(page)


@pytest.mark.pbir
def test_given_both_rule_sets_should_list_failures_first_whichever_set_they_came_from():
    rows = rule_rows(_SUMMARY, _RESULTS)

    assert [row[5] for row in rows] == sorted((row[5] for row in rows), key=["ERROR", "WARNING", "PASS"].index)
    assert [row[1] for row in rows][:2] == ["SHOW_VISUAL_HEADER", "CONTRACT.half-year-current"]


@pytest.mark.pbir
def test_given_a_run_should_link_to_the_results_and_inspectors_page_from_the_top(tmp_path):
    page = _page(tmp_path)

    nav = _between(page, '<nav class="toc"', "</nav>")
    assert 'href="#results"' in nav and 'href="#inspector"' in nav
    assert page.index("</nav>") < page.index('id="results"') < page.index("<table>") < page.index('id="inspector"')


@pytest.mark.pbir
def test_given_inspectors_page_should_frame_it_collapsed_at_the_bottom(tmp_path):
    page = _page(tmp_path)

    inspector = page[page.index('<details id="inspector">'):]                 # closed until asked for
    assert inspector.index("</details>") > inspector.index("<iframe")
    assert page.rindex("</details>") > page.rindex("</table>")               # below fab-test's table
    assert '<iframe src="native.json/TestRun.html"' in inspector and 'loading="lazy"' in inspector
    assert '<a href="native.json/TestRun.html" target="_blank"' in inspector


@pytest.mark.pbir
def test_given_no_inspector_page_should_say_so_without_a_frame(tmp_path):
    page = _page(tmp_path, inspector=None)

    assert "PBIR Inspector wrote no page this run" in page[page.index('id="inspector"'):]
    assert "<iframe" not in page


@pytest.mark.pbir
def test_given_a_link_to_a_collapsed_section_should_open_it(tmp_path):
    page = _page(tmp_path)

    script = page[page.rindex("<script>"):]
    assert "nav.toc a" in script and ".open = true" in script


@pytest.mark.pbir
def test_given_a_path_should_write_the_page_and_return_it(tmp_path):
    target = tmp_path / "pbir" / "Sales" / "report.html"

    written = write_pbir_report(_envelope(), target, _PAIRED, None)

    assert written == target and "<h1>fab-test pbir_inspector</h1>" in target.read_text(encoding="utf-8")


@pytest.mark.pbir
def test_given_a_page_it_cannot_write_should_return_none_not_raise(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")

    assert write_pbir_report(_envelope(), blocker / "report.html", _PAIRED, None) is None


@pytest.mark.playwright
def test_given_a_click_on_the_inspector_link_should_open_its_section(page, tmp_path):
    page.set_content(_page(tmp_path))
    assert not page.eval_on_selector("#inspector", "d => d.open")

    page.click('nav.toc a[href="#inspector"]')

    assert page.eval_on_selector("#inspector", "d => d.open")


@pytest.mark.playwright
def test_given_a_search_for_the_contract_should_leave_only_its_rows(page, tmp_path):
    page.set_content(_page(tmp_path))

    page.fill(".search-box", "Sales.Report.odcs.yaml")

    assert page.is_visible("td:text-is('CONTRACT.alignment-default')")
    assert not page.is_visible("td:text-is('SHOW_VISUAL_HEADER')")


@pytest.mark.playwright
def test_given_the_errors_filter_should_apply_to_both_rule_sets(page, tmp_path):
    page.set_content(_page(tmp_path))

    page.click('label[for="f-error"]')

    assert page.is_visible("td:text-is('SHOW_VISUAL_HEADER')")
    assert not page.is_visible("td:text-is('DISABLE_DROP_SHADOW')")          # a passing PBIR rule
    assert not page.is_visible("td:text-is('CONTRACT.alignment-default')")   # a passing contract check
