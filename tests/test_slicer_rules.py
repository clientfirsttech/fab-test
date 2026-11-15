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


@pytest.mark.pbir
def test_given_the_compiled_rules_should_name_no_visual_id():
    text = json.dumps(compile_rules([_expectation()]))

    assert "visuals/" not in text and "ce885ceced4291ade64c" not in text


@pytest.mark.pbir
@pytest.mark.parametrize("check, expected, tokens", [
    ("selected", ["Bad", 1940], ["'Bad'", "1940L"]),
    ("selected", [], []),
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
