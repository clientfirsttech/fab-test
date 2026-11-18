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

NOT_PLAIN = "a selection that isn't a plain list of values (for example 'all except', or several columns)"
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
    decoded = decode_literal(literal)

    assert (type(decoded), decoded) == (type(value), value)  # 3 == 3.0 and True == 1, so pin the type too


@pytest.mark.pbir
def test_given_a_plain_selection_should_read_its_values(tmp_path):
    assert _current(tmp_path, where=[{"Condition": _in("'Bad'", "'Good'")}]) == {"selected": ["Bad", "Good"]}


@pytest.mark.pbir
@pytest.mark.parametrize("where", [[], None])
def test_given_no_selection_in_either_form_should_read_nothing_selected(tmp_path, where):
    assert _current(tmp_path, where=where) == {"selected": []}


INVERTED = {"isInvertedSelectionMode": {"expr": {"Literal": {"Value": "true"}}}}


@pytest.mark.pbir
@pytest.mark.parametrize("where", [None, [], [{"Condition": {"Not": {"Expression": _in()}}}]])
def test_given_select_all_with_nothing_unticked_should_read_all_not_nothing_selected(tmp_path, where):
    assert _current(tmp_path, where=where, data=INVERTED) == {"selected": "all"}


@pytest.mark.pbir
def test_given_the_select_all_flag_under_general_should_read_all(tmp_path):
    report = _report(tmp_path, where=None)
    [path] = report.glob("definition/pages/p1/visuals/v1/visual.json")
    visual = json.loads(path.read_text(encoding="utf-8"))
    visual["visual"]["objects"]["general"] = [{"properties": INVERTED}]
    path.write_text(json.dumps(visual), encoding="utf-8")

    [slicer] = read_slicers(report)

    assert slicer.current == {"selected": "all"}


@pytest.mark.pbir
def test_given_inverted_mode_switched_off_should_read_nothing_selected(tmp_path):
    off = {"isInvertedSelectionMode": {"expr": {"Literal": {"Value": "false"}}}}

    assert _current(tmp_path, where=None, data=off) == {"selected": []}


@pytest.mark.pbir
def test_given_select_all_then_one_value_unticked_should_call_it_unsupported(tmp_path):
    where = [{"Condition": {"Not": {"Expression": _in("'Bad'")}}}]

    assert _current(tmp_path, where=where, data=INVERTED) == {"unsupported": NOT_PLAIN}


@pytest.mark.pbir
def test_given_the_test_bed_should_hold_a_cleared_slicer_and_a_select_all_slicer():
    root = Path(__file__).resolve().parents[1] / "fabric-artifacts" / "SampleModel-DefaultState.Report"

    page = {(s.table, s.column): s.current for s in read_slicers(root) if s.page == "Empty and All"}

    assert page == {("AlignmentDim", "Alignment"): {"selected": []},
                    ("EyeColorDim", "Eye Color"): {"selected": "all"}}


@pytest.mark.pbir
@pytest.mark.parametrize("where, reason", [
    ([{"Condition": {"Not": {"Expression": _in("'Bad'")}}}], NOT_PLAIN),          # "all except Bad"
    ([{"Condition": {"Or": {"Left": _in("'Bad'"), "Right": _in("'Good'")}}}], NOT_PLAIN),
    ([{"Condition": {"In": {"Expressions": [COLUMN, COLUMN], "Values": [[{"Literal": {"Value": "'a'"}}] * 2]}}}],
     NOT_PLAIN),
    ([{"Condition": _in("'Bad'")}, {"Condition": _in("'Good'")}], NOT_PLAIN),
    ([{"Condition": _in("2.5M")}], "a value fab-test can't write back exactly (2.5M)"),
    ([{"Condition": _comparison(0, "datetime'2026-01-01T00:00:00'")}], "a date range other than from/to"),
])
def test_given_a_shape_the_rules_cant_check_should_say_why_its_unsupported(tmp_path, where, reason):
    assert _current(tmp_path, where=where) == {"unsupported": reason}


@pytest.mark.pbir
def test_given_a_hierarchy_slicer_should_call_it_unsupported(tmp_path):
    current = _current(tmp_path, where=[{"Condition": _in("'Bad'")}], projections=2)

    assert current == {"unsupported": "a hierarchy or several fields"}


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
