"""The slicer contract in PBIR Inspector's TestRun.html (PBIR Slicer Default State epic).

`--report` / `--open-report` open PBIR Inspector's own page, which lists the
packaged PBIR rules and the contract's `CONTRACT.*` rules under one ruleset,
"Rules", and says nothing about the contract. fab-test patches the page: a
collapsible section, styled as fab-test's own reports (the same table and
stylesheet, scoped to the section so the page keeps its look), with one row
per contract check; and the contract's results renamed to ruleset "Slicer
contract" so the page's own Ruleset Name filter separates them. Like every
fixup, a page without the markers is left alone.
"""

import json
from pathlib import Path

import pytest

from fab_test.scripts._pbir_report_fixups import mark_contract_rules
from fab_test.scripts._report_html import REPORT_STYLE

_RESULTS = [
    {"RuleId": "SHOW_VISUAL_HEADER", "RuleSetName": "Rules", "Message": "x"},
    {"RuleId": "CONTRACT.half-year-current", "RuleSetName": "Rules",
     "Message": "opens with ['2025 H2']; the contract expects 2026 H2 </script><b>"},
]
_PAGE = """<html><body>
    <main class="container">
        <div class="d-flex align-items-center p-3 my-3 rounded shadow-sm">logo</div>

        <div class="row g-3">header and filters</div>
    </main>
    <script>
        let testRunData = %s;
    </script>
</body></html>"""
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
_FOUND = "'Fiscal Calendar'[Half Year] opens with ['2025 H2']; the contract expects 2026 H2"
_ROWS = [  # envelope test_results, tagged with their source; one rule yields a row per page it ran on
    {"rule": "CONTRACT.alignment-default", "status": "pass", "message": "", "source": "contract"},
    {"rule": "CONTRACT.half-year-current", "status": "pass", "message": "", "source": "contract"},
    {"rule": "CONTRACT.half-year-current", "status": "warning", "message": _FOUND, "source": "contract"},
    {"rule": "CONTRACT.page-1-navigator", "status": "pass", "message": "", "source": "contract"},
    {"rule": "CONTRACT.page.Standard Slicers", "status": "pass", "message": "", "source": "contract"},
    {"rule": "SHOW_VISUAL_HEADER", "status": "error", "message": "x", "source": "rules"},
]
_PAIRED = "📜 Slicer contract: Sales.Report.odcs.yaml (2 slicer checks, 1 bookmark navigator)"
_NONE = "📜 Slicer contract: none (no *.odcs.yaml under --artifact-dir has fabTestReport abc; only the PBIR rules run)"


def _page(tmp_path: Path) -> Path:
    path = tmp_path / "TestRun.html"
    path.write_text(_PAGE % json.dumps({"Id": "1", "Results": _RESULTS}), encoding="utf-8")
    return path


def _data(page: Path) -> dict:
    text = page.read_text(encoding="utf-8")
    start = text.index("let testRunData = ") + len("let testRunData = ")
    return json.JSONDecoder().raw_decode(text, start)[0]


def _section(page: Path, summary=_SUMMARY, rows=_ROWS, contract=_PAIRED) -> str:
    mark_contract_rules(page, contract, summary, rows)
    text = page.read_text(encoding="utf-8")
    return text[text.index('id="fabTestContract"'):text.index('<div class="row g-3">')]


def _row(section: str, rule: str) -> str:
    start = section.index(f"<td>{rule}</td>")
    return section[section.rindex("<tr", 0, start):section.index("</tr>", start)]


@pytest.mark.pbir
def test_given_a_contract_should_add_a_collapsible_section_summarising_it(tmp_path):
    section = _section(_page(tmp_path))

    assert ("<summary>Slicer contract · Sales.Report.odcs.yaml · 2 slicer checks, 1 bookmark navigator · "
            "1 failed</summary>") in section                                # the terminal's words
    assert "<details open>" in section                                     # a failure opens it


@pytest.mark.pbir
def test_given_every_check_passed_should_start_collapsed(tmp_path):
    rows = [r for r in _ROWS if r["status"] == "pass"]

    section = _section(_page(tmp_path), rows=rows)

    assert "<details>" in section and ", 1 bookmark navigator · all passed</summary>" in section


@pytest.mark.pbir
def test_given_a_contract_should_use_fab_tests_report_table_and_style_scoped_to_the_section(tmp_path):
    section = _section(_page(tmp_path))

    assert '<template shadowrootmode="open">' in section                   # the page's own styles stay its own
    assert REPORT_STYLE in section
    assert "<th>Rule</th><th>Severity</th><th>Page</th><th>Expects</th><th>Found</th><th>Status</th>" in section


@pytest.mark.pbir
def test_given_a_check_should_show_what_it_expects_and_its_worst_result(tmp_path):
    section = _section(_page(tmp_path))

    failed = _row(section, "CONTRACT.half-year-current")
    assert 'class="warning" data-status="warning"' in failed
    assert "&#x27;Fiscal Calendar&#x27;[Half Year] opens with 2026 H2" in failed
    assert "opens with [&#x27;2025 H2&#x27;]; the contract expects 2026 H2" in failed
    assert 'data-status="pass"' in _row(section, "CONTRACT.alignment-default")
    assert "bookmark navigator opens with Bookmark 2" in _row(section, "CONTRACT.page-1-navigator")
    assert "the page exists" in _row(section, "CONTRACT.page.Standard Slicers")


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

    section = _section(_page(tmp_path), summary=summary, rows=[])

    assert f"&#x27;T&#x27;[C] {shown}" in _row(section, "CONTRACT.r")


@pytest.mark.pbir
def test_given_a_contract_should_say_how_to_filter_the_results_to_it(tmp_path):
    section = _section(_page(tmp_path))

    assert "Type <kbd>contract</kbd> in the Ruleset Name filter to see only the contract&#x27;s results." in section


@pytest.mark.pbir
def test_given_a_contract_should_put_its_results_in_their_own_ruleset(tmp_path):
    page = _page(tmp_path)
    _section(page)

    assert {r["RuleId"]: r["RuleSetName"] for r in _data(page)["Results"]} == {
        "SHOW_VISUAL_HEADER": "Rules", "CONTRACT.half-year-current": "Slicer contract"}


@pytest.mark.pbir
def test_given_a_message_holding_a_closing_script_tag_should_keep_the_data_inside_its_script(tmp_path):
    page = _page(tmp_path)
    _section(page)

    assert page.read_text(encoding="utf-8").count("</script>") == 1         # only the page's own
    assert _data(page)["Results"][1]["Message"].endswith("</script><b>")


@pytest.mark.pbir
def test_given_no_contract_should_say_why_in_a_collapsed_section_with_no_table(tmp_path):
    section = _section(_page(tmp_path), summary=None, rows=[], contract=_NONE)

    assert "<details><summary>Slicer contract · none paired</summary>" in section
    assert "none (no *.odcs.yaml under --artifact-dir has fabTestReport abc; only the PBIR rules run)" in section
    assert "<table" not in section and "Ruleset Name" not in section


@pytest.mark.pbir
def test_given_it_runs_twice_should_add_one_section(tmp_path):
    page = _page(tmp_path)
    _section(page)
    mark_contract_rules(page, _PAIRED, _SUMMARY, _ROWS)

    assert page.read_text(encoding="utf-8").count('id="fabTestContract"') == 1


@pytest.mark.pbir
@pytest.mark.parametrize("page", ["<html><body>no data, no layout</body></html>",
                                  '<main><div class="row g-3"></div></main><script>let testRunData = {bad</script>'])
def test_given_a_page_without_the_markers_should_leave_it_alone(tmp_path, page):
    path = tmp_path / "TestRun.html"
    path.write_text(page, encoding="utf-8")

    mark_contract_rules(path, _PAIRED, _SUMMARY, _ROWS)

    assert path.read_text(encoding="utf-8") == page
