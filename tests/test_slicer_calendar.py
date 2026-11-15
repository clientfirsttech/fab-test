"""Calendar Resolution (PBIR Slicer Default State epic).

A calendar-driven expectation is a format string over named fields, resolved
from an as-of date and the contract's own calendar. Nothing is evaluated.

    pytest tests/test_slicer_calendar.py
"""

import datetime
from pathlib import Path

import pytest

from fab_test.scripts._slicer_calendar import (
    FIELDS,
    CalendarError,
    calendar_fields,
    resolve_contract,
)
from fab_test.scripts._slicer_contract import SlicerContract, SlicerExpectation, load_contract

EXAMPLE = Path(__file__).resolve().parent.parent / "fabric-artifacts" / "SampleModel-DefaultState.Report.odcs.yaml"
JULY_END = {"fiscal_year_start_month": 7, "fiscal_year_named_by": "end"}


def _fiscal(day, calendar):
    f = calendar_fields(day, calendar)
    return f["fiscal_year"], f["fiscal_semester"], f["fiscal_quarter"], f["fiscal_month"]


def _contract(*selected, calendar=None, check="selected"):
    expectations = [SlicerExpectation(f"r{i}", "Overview", "Date", "Semester", check, [value], "error")
                    for i, value in enumerate(selected)]
    return SlicerContract(Path("x.odcs.yaml"), "id", calendar, expectations)


@pytest.mark.pbir
@pytest.mark.parametrize("day, expected", [
    (datetime.date(2026, 6, 30), (2026, 2, 4, 12)),   # last day of FY26
    (datetime.date(2026, 7, 1), (2027, 1, 1, 1)),     # first day of FY27
    (datetime.date(2026, 11, 14), (2027, 1, 2, 5)),
    (datetime.date(2027, 1, 1), (2027, 2, 3, 7)),     # calendar year turns, fiscal year doesn't
])
def test_given_a_july_fiscal_year_named_by_its_end_should_resolve_both_sides_of_each_boundary(day, expected):
    assert _fiscal(day, JULY_END) == expected


@pytest.mark.pbir
def test_given_a_fiscal_year_named_by_its_start_should_name_it_by_the_year_it_begins():
    calendar = {"fiscal_year_start_month": 7, "fiscal_year_named_by": "start"}

    assert _fiscal(datetime.date(2026, 7, 1), calendar)[0] == 2026
    assert _fiscal(datetime.date(2026, 6, 30), calendar)[0] == 2025


@pytest.mark.pbir
def test_given_no_calendar_should_make_the_fiscal_year_the_calendar_year():
    fields = calendar_fields(datetime.date(2026, 11, 14), None)

    assert (fields["fiscal_year"], fields["fiscal_quarter"], fields["fiscal_month"]) == (2026, 4, 11)
    assert (fields["year"], fields["half"], fields["quarter"], fields["month"]) == (2026, 2, 4, 11)


@pytest.mark.pbir
def test_given_a_year_ending_in_a_single_digit_should_keep_the_short_year_two_digits():
    fields = calendar_fields(datetime.date(2008, 8, 1), JULY_END)

    assert (fields["year_short"], fields["fiscal_year_short"]) == ("08", "09")


@pytest.mark.pbir
def test_given_the_test_bed_contract_should_resolve_its_calendar_rules_on_the_as_of_date():
    resolved = resolve_contract(load_contract(EXAMPLE), datetime.date(2026, 11, 14))

    by_id = {e.rule_id: e.expected for e in resolved}
    assert by_id["fiscal-semester-current"] == ["FY27-S1"]
    assert by_id["half-year-current"] == ["2026 H2"]
    assert by_id["year-default"] == [1940]


@pytest.mark.pbir
def test_given_a_format_spec_should_apply_it():
    [resolved] = resolve_contract(_contract("{year}-{month:02}"), datetime.date(2026, 3, 9))

    assert resolved.expected == ["2026-03"]


@pytest.mark.pbir
def test_given_input_slicer_text_should_resolve_it_like_a_selected_value():
    [resolved] = resolve_contract(_contract("Q{quarter}", check="contains"), datetime.date(2026, 3, 9))

    assert resolved.expected == ["Q1"]


@pytest.mark.pbir
def test_given_unknown_fields_should_name_every_rule_and_field_and_list_the_valid_ones():
    with pytest.raises(CalendarError) as caught:
        resolve_contract(_contract("FY{fy}", "{semester}"), datetime.date(2026, 11, 14))

    message = str(caught.value)
    assert "r0" in message and "'fy'" in message
    assert "r1" in message and "'semester'" in message
    assert all(name in message for name in FIELDS)


@pytest.mark.pbir
@pytest.mark.parametrize("text", ["{year.__class__}", "{year[0]}", "{year!r}", "{month:{year}}", "{}", "FY{year",
                                  "{year:999999999}"])
def test_given_anything_but_a_plain_field_should_refuse_to_evaluate_it(text):
    with pytest.raises(CalendarError):
        resolve_contract(_contract(text), datetime.date(2026, 11, 14))


@pytest.mark.pbir
@pytest.mark.parametrize("calendar, key", [
    ({"fiscal_year_start_month": 13}, "fiscal_year_start_month"),
    ({"fiscal_year_start_month": "7"}, "fiscal_year_start_month"),
    ({"fiscal_year_named_by": "middle"}, "fiscal_year_named_by"),
    ({"fiscal_start": 7}, "fiscal_start"),
])
def test_given_a_malformed_calendar_should_name_the_setting(calendar, key):
    with pytest.raises(CalendarError) as caught:
        resolve_contract(_contract("{year}", calendar=calendar), datetime.date(2026, 11, 14))

    assert f"fabTestCalendar.{key}" in str(caught.value)


@pytest.mark.pbir
def test_given_a_value_that_is_one_bare_field_should_keep_the_fields_type_for_numeric_columns():
    resolved = resolve_contract(_contract("{year}", "FY{year}", "{fiscal_year_short}"), datetime.date(2026, 11, 14))

    assert [e.expected[0] for e in resolved] == [2026, "FY2026", "26"]
