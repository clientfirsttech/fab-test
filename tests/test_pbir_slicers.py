"""Reading what a PBIR slicer opens with (PBIR Slicer Default State epic).

`read_slicers` must read exactly the shapes the compiled rules can check and
call everything else unsupported, so `contract init` never writes a rule that
would pass a selection it can't see.
"""

import datetime
import json
from pathlib import Path

import pytest

from fab_test.scripts._pbir_slicers import decode_literal, read_slicers

COLUMN = {"Column": {"Expression": {"SourceRef": {"Source": "a"}}, "Property": "Alignment"}}


def _in(*literals):
    return {"In": {"Expressions": [COLUMN], "Values": [[{"Literal": {"Value": v}}] for v in literals]}}


def _comparison(kind, literal):
    return {"Comparison": {"ComparisonKind": kind, "Left": COLUMN, "Right": {"Literal": {"Value": literal}}}}


def _report(tmp_path: Path, where=None, visual_type="slicer", mode="'Basic'", projections=1, data=None) -> Path:
    report = tmp_path / "Bed.Report"
    pages = report / "definition" / "pages"
    (pages / "p1" / "visuals" / "v1").mkdir(parents=True)
    (pages / "pages.json").write_text(json.dumps({"pageOrder": ["p1"]}), encoding="utf-8")
    (pages / "p1" / "page.json").write_text(json.dumps({"displayName": "Overview"}), encoding="utf-8")
    field = {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "AlignmentDim"}}, "Property": "Alignment"}}}
    objects = {"data": [{"properties": {"mode": {"expr": {"Literal": {"Value": mode}}}, **(data or {})}}]}
    if where is not None:
        objects["general"] = [{"properties": {"filter": {"filter": {"Version": 2, "Where": where}}}}]
    visual = {"visual": {"visualType": visual_type, "objects": objects,
                         "query": {"queryState": {"Values": {"projections": [field] * projections}}}}}
    (pages / "p1" / "visuals" / "v1" / "visual.json").write_text(json.dumps(visual), encoding="utf-8")
    return report


def _current(tmp_path, **kwargs):
    [slicer] = read_slicers(_report(tmp_path, **kwargs))
    return slicer.current


@pytest.mark.pbir
@pytest.mark.parametrize("literal, value", [
    ("'Bad'", "Bad"), ("'O''Neil'", "O'Neil"), ("1940L", 1940), ("-3L", -3), ("2.5D", 2.5), ("3D", 3.0),
    ("true", True), ("null", None), ("datetime'2026-10-28T00:00:00'", datetime.date(2026, 10, 28)),
    ("datetime'2026-10-28T13:45:00'", datetime.datetime.fromisoformat("2026-10-28T13:45:00")), ("2.5M", "2.5M"),
])
def test_given_a_dax_literal_should_decode_what_the_user_sees(literal, value):
    assert decode_literal(literal) == value


@pytest.mark.pbir
def test_given_a_plain_selection_should_read_its_values(tmp_path):
    assert _current(tmp_path, where=[{"Condition": _in("'Bad'", "'Good'")}]) == {"selected": ["Bad", "Good"]}


@pytest.mark.pbir
@pytest.mark.parametrize("where", [[], None])
def test_given_no_selection_in_either_form_should_read_nothing_selected(tmp_path, where):
    assert _current(tmp_path, where=where) == {"selected": []}


@pytest.mark.pbir
@pytest.mark.parametrize("where", [
    [{"Condition": {"Not": {"Expression": _in("'Bad'")}}}],                      # "all except Bad"
    [{"Condition": {"Or": {"Left": _in("'Bad'"), "Right": _in("'Good'")}}}],
    [{"Condition": {"In": {"Expressions": [COLUMN, COLUMN], "Values": [[{"Literal": {"Value": "'a'"}}] * 2]}}}],
    [{"Condition": _in("'Bad'")}, {"Condition": _in("'Good'")}],
    [{"Condition": _in("2.5M")}],                                                # a decimal that wouldn't round-trip
    [{"Condition": _comparison(0, "datetime'2026-01-01T00:00:00'")}],            # Equal, not a from/to bound
])
def test_given_a_shape_the_rules_cant_check_should_call_it_unsupported(tmp_path, where):
    assert "unsupported" in _current(tmp_path, where=where)


@pytest.mark.pbir
def test_given_a_hierarchy_slicer_should_call_it_unsupported(tmp_path):
    assert "unsupported" in _current(tmp_path, where=[{"Condition": _in("'Bad'")}], projections=2)


@pytest.mark.pbir
def test_given_a_between_range_should_read_inclusive_dates_and_an_open_bound(tmp_path):
    where = [{"Condition": _comparison(3, "datetime'2026-10-29T00:00:00'")}]

    assert _current(tmp_path, where=where, mode="'Between'") == {"range": {"to": datetime.date(2026, 10, 28)}}


@pytest.mark.pbir
def test_given_a_cleared_relative_slicer_should_read_nothing_selected_not_its_leftover_settings(tmp_path):
    leftovers = {"relativeRange": {"expr": {"Literal": {"Value": "'Last'"}}}}

    assert _current(tmp_path, where=[], mode="'Relative'", data=leftovers) == {"selected": []}


@pytest.mark.pbir
def test_given_an_input_slicer_with_nothing_typed_should_read_an_empty_contains(tmp_path):
    assert _current(tmp_path, where=[], visual_type="textSlicer") == {"contains": []}
