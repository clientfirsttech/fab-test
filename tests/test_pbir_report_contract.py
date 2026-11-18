"""The slicer contract in PBIR Inspector's TestRun.html (PBIR Slicer Default State epic).

`--report` / `--open-report` open PBIR Inspector's own page, which lists the
packaged PBIR rules and the contract's `CONTRACT.*` rules under one ruleset,
"Rules", and says nothing about the contract. fab-test patches the page: a
panel naming the contract (or why none paired) with its failures, and the
contract's results renamed to ruleset "Slicer contract" so the page's own
Ruleset Name filter separates them. Like every fixup, a page without the
markers is left alone.
"""

import json
from pathlib import Path

import pytest

from fab_test.scripts._pbir_report_fixups import mark_contract_rules

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
_FAILED = [{"rule": "CONTRACT.half-year-current", "object": "Standard Slicers",
            "message": "'Fiscal Calendar'[Half Year] opens with ['2025 H2']; the contract expects 2026 H2"}]


def _page(tmp_path: Path, results=_RESULTS) -> Path:
    path = tmp_path / "TestRun.html"
    path.write_text(_PAGE % json.dumps({"Id": "1", "Results": results}), encoding="utf-8")
    return path


def _data(page: Path) -> dict:
    text = page.read_text(encoding="utf-8")
    start = text.index("let testRunData = ") + len("let testRunData = ")
    return json.JSONDecoder().raw_decode(text, start)[0]


def _mark(page: Path, paired=True, failed=_FAILED) -> str:
    contract = ("📜 Slicer contract: Sales.Report.odcs.yaml (12 slicer checks)" if paired
                else "📜 Slicer contract: none (no *.odcs.yaml under --artifact-dir has fabTestReport abc; …)")
    mark_contract_rules(page, contract, "0 from the PBIR rules, 1 from the slicer contract", failed, paired)
    return page.read_text(encoding="utf-8")


@pytest.mark.pbir
def test_given_a_paired_contract_should_name_it_and_its_failures_above_the_results(tmp_path):
    text = _mark(_page(tmp_path))

    panel = text[text.index('id="fabTestContract"'):text.index('<div class="row g-3">')]
    assert "Slicer contract: Sales.Report.odcs.yaml (12 slicer checks)" in panel
    assert "📜" not in panel
    assert "0 from the PBIR rules, 1 from the slicer contract" in panel
    assert "<code>CONTRACT.half-year-current</code>" in panel and "Standard Slicers" in panel
    assert "&#x27;Fiscal Calendar&#x27;[Half Year] opens with [&#x27;2025 H2&#x27;]" in panel  # escaped
    assert "Ruleset Name" in panel                                      # how to see only the contract


@pytest.mark.pbir
def test_given_a_paired_contract_should_put_its_results_in_their_own_ruleset(tmp_path):
    page = _page(tmp_path)
    _mark(page)

    assert {r["RuleId"]: r["RuleSetName"] for r in _data(page)["Results"]} == {
        "SHOW_VISUAL_HEADER": "Rules", "CONTRACT.half-year-current": "Slicer contract"}


@pytest.mark.pbir
def test_given_a_message_holding_a_closing_script_tag_should_keep_the_data_inside_its_script(tmp_path):
    text = _mark(_page(tmp_path))

    assert text.count("</script>") == 1                                  # only the page's own
    assert _data(tmp_path / "TestRun.html")["Results"][1]["Message"].endswith("</script><b>")


@pytest.mark.pbir
def test_given_no_contract_should_say_none_paired_without_the_filter_tip(tmp_path):
    text = _mark(_page(tmp_path), paired=False, failed=[])

    panel = text[text.index('id="fabTestContract"'):text.index('<div class="row g-3">')]
    assert "Slicer contract: none (no *.odcs.yaml under --artifact-dir has fabTestReport abc" in panel
    assert "Ruleset Name" not in panel and "<ul" not in panel


@pytest.mark.pbir
def test_given_it_runs_twice_should_add_one_panel(tmp_path):
    page = _page(tmp_path)
    _mark(page)

    assert _mark(page).count('id="fabTestContract"') == 1


@pytest.mark.pbir
@pytest.mark.parametrize("page", ["<html><body>no data, no layout</body></html>",
                                  '<main><div class="row g-3"></div></main><script>let testRunData = {bad</script>'])
def test_given_a_page_without_the_markers_should_leave_it_alone(tmp_path, page):
    path = tmp_path / "TestRun.html"
    path.write_text(page, encoding="utf-8")

    _mark(path)

    assert path.read_text(encoding="utf-8") == page
