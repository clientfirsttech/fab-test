"""Contract To JSON Logic (PBIR Slicer Default State epic): compiling slicer rules.

Pure tests of the compiled rule shape; `test_slicer_rules_live.py` runs them
through PBIR Inspector against the SampleModel-DefaultState test bed.

    pytest tests/test_slicer_rules.py
"""

import datetime
import json

import pytest

from fab_test.scripts._slicer_contract import SlicerExpectation
from fab_test.scripts._slicer_rules import compile_rules, expected_tokens


def _expectation(check="selected", expected=None, page="Standard Slicers", severity="error"):
    return SlicerExpectation("r1", page, "AlignmentDim", "Alignment", check, expected or ["Bad"], severity)


@pytest.mark.pbir
def test_given_an_expectation_should_compile_a_page_scoped_rule_carrying_its_severity():
    rules = compile_rules([_expectation(severity="warning")])

    [rule] = [r for r in rules if r["id"] == "CONTRACT.r1"]
    assert (rule["part"], rule["logType"], rule["disabled"]) == ("Pages", "warning", False)
    assert "Standard Slicers" in rule["name"] and "'AlignmentDim'[Alignment]" in rule["name"]


@pytest.mark.pbir
def test_given_expectations_on_two_pages_should_add_one_page_existence_rule_per_page():
    rules = compile_rules([_expectation(page="A"), _expectation(page="A"), _expectation(page="B")])

    page_rules = sorted(r["id"] for r in rules if r["id"].startswith("CONTRACT.page."))
    assert page_rules == ["CONTRACT.page.A", "CONTRACT.page.B"]


def _comparisons(node):
    """Every {"==": [{"var": path}, value]} in a JSON Logic tree, as (path, value)."""
    if isinstance(node, dict):
        pair = node.get("==")
        if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], dict) and "var" in pair[0]:
            yield pair[0]["var"], pair[1]
        for child in node.values():
            yield from _comparisons(child)
    elif isinstance(node, list):
        for child in node:
            yield from _comparisons(child)


@pytest.mark.pbir
def test_given_a_rule_should_find_its_slicer_by_bound_column_never_by_visual_name():
    [rule] = [r for r in compile_rules([_expectation()]) if r["id"] == "CONTRACT.r1"]
    compared = dict(_comparisons(rule["test"]))

    field = "visual.query.queryState.Values.projections.0.field.Column"
    assert (compared[f"{field}.Expression.SourceRef.Entity"], compared[f"{field}.Property"]) == (
        "AlignmentDim", "Alignment")
    assert not [path for path in compared if path in ("name", "visual.name") or path.endswith(".name")]


@pytest.mark.pbir
@pytest.mark.parametrize("check, expected, tokens", [
    ("selected", ["Bad", 1940], ["'Bad'", "1940L"]),
    ("selected", [], []),
    ("selected", "all", []),
    ("contains", ["Wolverine"], ["'Wolverine'"]),
    ("range", {"from": datetime.date(1939, 10, 1), "to": datetime.date(1951, 8, 27)},
     ["2|datetime'1939-10-01T00:00:00'", "3|datetime'1951-08-28T00:00:00'"]),
    ("range", {"to": datetime.date(2026, 10, 28)}, ["3|datetime'2026-10-29T00:00:00'"]),
    ("relative", {"range": "Last", "duration": 20, "period": "Calendar Months"}, ["'Last'|20D|'Calendar Months'"]),
])
def test_given_each_check_should_expect_the_tokens_desktop_writes(check, expected, tokens):
    assert expected_tokens(SlicerExpectation("r", "P", "T", "C", check, expected, "error")) == tokens


@pytest.mark.pbir
def test_given_a_rule_file_should_be_plain_json():
    rules = compile_rules([_expectation(check="range", expected={"to": datetime.date(2026, 10, 28)})])

    assert json.loads(json.dumps(rules)) == rules


@pytest.mark.pbir
def test_given_an_inspector_message_with_escaped_quotes_should_show_the_quotes():
    from fab_test.scripts.invoke_pbir_inspector import _normalize_finding

    finding = {"RuleId": "CONTRACT.r1", "LogType": 0, "Pass": False,
               "Message": 'FAILED with result: ["\u0027T\u0027[C] opens with [\u0027Bad\u0027]"]'}

    assert _normalize_finding(finding)["message"] == "FAILED with result: [\"'T'[C] opens with ['Bad']\"]"


@pytest.mark.pbir
def test_given_select_all_and_nothing_selected_should_name_each_differently():
    [everything] = [r for r in compile_rules([_expectation(expected="all")]) if r["id"] == "CONTRACT.r1"]
    [nothing] = [r for r in compile_rules([SlicerExpectation("r1", "P", "T", "C", "selected", [], "error")])
                 if r["id"] == "CONTRACT.r1"]

    assert everything["name"].endswith("opens with Select all")
    assert nothing["name"].endswith("opens with no selection")
