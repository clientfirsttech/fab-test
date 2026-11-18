"""The slicer contract's results on PBIR Inspector's TestRun.html (PBIR Slicer Default State epic).

PBIR Inspector lists the packaged PBIR rules and the contract's `CONTRACT.*`
rules under one ruleset, "Rules". fab-test renames the contract's to "Slicer
contract", so the page's own Ruleset Name filter separates them. The
contract itself is shown on fab-test's report page, which frames this one
(see test_pbir_report_page.py). Like every fixup, a page without the marker
is left alone.
"""

import json
from pathlib import Path

import pytest

from fab_test.scripts._pbir_report_fixups import mark_contract_ruleset

_RESULTS = [
    {"RuleId": "SHOW_VISUAL_HEADER", "RuleSetName": "Rules", "Message": "x"},
    {"RuleId": "CONTRACT.half-year-current", "RuleSetName": "Rules",
     "Message": "opens with ['2025 H2']; the contract expects 2026 H2 </script><!--<script><b>"},
]
_PAGE = """<html><body>
    <main class="container">header and filters</main>
    <script>
        let testRunData = %s;
    </script>
</body></html>"""


def _page(tmp_path: Path, results=_RESULTS) -> Path:
    path = tmp_path / "TestRun.html"
    path.write_text(_PAGE % json.dumps({"Id": "1", "Results": results}), encoding="utf-8")
    return path


def _data(page: Path) -> dict:
    text = page.read_text(encoding="utf-8")
    start = text.index("let testRunData = ") + len("let testRunData = ")
    return json.JSONDecoder().raw_decode(text, start)[0]


@pytest.mark.pbir
def test_given_a_contract_should_put_its_results_in_their_own_ruleset(tmp_path):
    page = _page(tmp_path)

    mark_contract_ruleset(page)

    assert {r["RuleId"]: r["RuleSetName"] for r in _data(page)["Results"]} == {
        "SHOW_VISUAL_HEADER": "Rules", "CONTRACT.half-year-current": "Slicer contract"}


@pytest.mark.pbir
def test_given_markup_in_the_data_should_keep_every_angle_bracket_escaped_inside_the_script(tmp_path):
    page = _page(tmp_path)

    mark_contract_ruleset(page)

    text = page.read_text(encoding="utf-8")
    start = text.index("let testRunData = ")
    assert "<" not in text[start:text.index(";", text.rindex("}", 0, text.rindex("</script>")))]
    assert text.count("</script>") == 1                                     # only the page's own
    assert _data(page)["Results"][1]["Message"].endswith("</script><!--<script><b>")    # the same text in JS


@pytest.mark.pbir
def test_given_it_runs_twice_should_change_nothing_more(tmp_path):
    page = _page(tmp_path)
    mark_contract_ruleset(page)
    once = page.read_text(encoding="utf-8")

    mark_contract_ruleset(page)

    assert page.read_text(encoding="utf-8") == once


@pytest.mark.pbir
def test_given_no_contract_results_should_leave_the_page_byte_for_byte(tmp_path):
    page = _page(tmp_path, [_RESULTS[0]])
    before = page.read_text(encoding="utf-8")

    mark_contract_ruleset(page)

    assert page.read_text(encoding="utf-8") == before


@pytest.mark.pbir
@pytest.mark.parametrize("results", [None, ["not a result", 3], {"RuleId": "CONTRACT.x"}])
def test_given_results_of_an_unexpected_shape_should_leave_the_page_alone_not_raise(tmp_path, results):
    page = _page(tmp_path, results)
    before = page.read_text(encoding="utf-8")

    mark_contract_ruleset(page)

    assert page.read_text(encoding="utf-8") == before


@pytest.mark.pbir
@pytest.mark.parametrize("page", ["<html><body>no data, no layout</body></html>",
                                  "<main></main><script>let testRunData = {bad</script>"])
def test_given_a_page_without_the_markers_should_leave_it_alone(tmp_path, page):
    path = tmp_path / "TestRun.html"
    path.write_text(page, encoding="utf-8")

    mark_contract_ruleset(path)

    assert path.read_text(encoding="utf-8") == page
