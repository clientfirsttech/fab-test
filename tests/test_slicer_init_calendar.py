"""Contract init's fiscal-year questions (PBIR Slicer Default State epic).

Fiscal years differ by company and nothing in a report says which one it uses,
so `init` asks only when an answer follows a fiscal field, offers no default
unless the contract already has one, and refuses an answer under which the
report doesn't open with today's period.
"""

import datetime
import json
import shutil
from pathlib import Path

import pytest
import yaml

from fab_test.scripts._slicer_contract import load_contract
from fab_test.scripts._slicer_contract_init import contract_main
from fab_test.scripts._slicer_init_calendar import naming_prompt, suggestion, uses_fiscal

ROOT = Path(__file__).resolve().parents[1]
TEST_BED = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report"
AS_OF = "2026-11-14"
SEMESTER, HALF_YEAR = "standard-slicers-fiscal-semester", "standard-slicers-half-year"
START, NAMED_BY = "calendar.fiscal_year_start_month", "calendar.fiscal_year_named_by"


def _bed(tmp_path: Path) -> Path:
    report = tmp_path / TEST_BED.name
    shutil.copytree(TEST_BED, report)
    return report


def _run(report: Path, capsys, *extra: str):
    code = contract_main(["init", str(report), "--as-of", AS_OF, *extra])
    out, err = capsys.readouterr()
    return code, out, err


def _questions(report: Path, capsys) -> dict:
    code, out, _err = _run(report, capsys, "--questions", "--format", "json")
    assert code == 0
    return {q["id"]: q for q in json.loads(out)["questions"]}


def _answer(tmp_path: Path, report: Path, capsys, answers: dict):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    return _run(report, capsys, "--answers", str(path))


def _contract(report: Path) -> Path:
    return report.parent / f"{report.name}.odcs.yaml"


def _set_value(report: Path, column: str, literal: str) -> None:
    """Re-save the Standard Slicers slicer on ``column`` with one value selected."""
    for path in report.glob("definition/pages/*/visuals/*/visual.json"):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        projections = data["visual"].get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
        if projections and projections[0]["field"].get("Column", {}).get("Property") == column:
            where = data["visual"]["objects"]["general"][0]["properties"]["filter"]["filter"]["Where"]
            where[0]["Condition"]["In"]["Values"] = [[{"Literal": {"Value": literal}}]]
            path.write_text(json.dumps(data), encoding="utf-8")
            return
    raise AssertionError(f"no slicer on {column}")


@pytest.mark.pbir
@pytest.mark.parametrize("text, fiscal", [("FY{fiscal_year_short}-S{fiscal_semester}", True), ("FY{fiscal_year}", True),
                                          ("{year} H{half}", False), ("{year}-{month:02}", False), ("{year}", False)])
def test_given_a_format_should_say_whether_it_follows_the_fiscal_year(text, fiscal):
    assert uses_fiscal(text) is fiscal


@pytest.mark.pbir
def test_given_a_fiscal_year_named_by_its_start_should_count_it_among_the_fits():
    text, fits = suggestion({"selected": ["FY26"]}, datetime.date(2026, 11, 17))

    assert text == "FY{fiscal_year_short}"
    assert (4, "start") in fits and (10, "end") not in fits  # Japan's FY26; an October FY is FY27 by now


@pytest.mark.pbir
def test_given_a_calendar_period_should_suggest_it_with_no_fiscal_fits():
    assert suggestion({"selected": ["2026 H2"]}, datetime.date(2026, 11, 14)) == ("{year} H{half}", None)


@pytest.mark.pbir
@pytest.mark.parametrize("start, prompt", [
    (10, "Is October 2026 to September 2027 called FY27 (the year it ends in) or FY26 (the year it starts in)?"),
    (7, "Is July 2026 to June 2027 called FY27 (the year it ends in) or FY26 (the year it starts in)?"),
    (12, "Is December 2025 to November 2026 called FY26 (the year it ends in) or FY25 (the year it starts in)?"),
])
def test_given_a_start_month_should_ask_the_naming_question_with_real_dates(start, prompt):
    assert naming_prompt(start, datetime.date(2026, 11, 17)) == prompt


@pytest.mark.pbir
def test_given_no_contract_yet_should_ask_the_fiscal_year_with_no_default_naming_what_needs_it(tmp_path, capsys):
    questions = _questions(_bed(tmp_path), capsys)

    start, named_by = questions[START], questions[NAMED_BY]
    assert (start["suggested"], named_by["suggested"]) == (None, None)
    assert start["applies_to"] == named_by["applies_to"] == [SEMESTER]
    assert 7 in start["reproduces"] and start["needs_human"] is True
    assert "Today's values fit " in start["prompt"]


@pytest.mark.pbir
def test_given_a_contract_with_a_fiscal_calendar_should_default_to_it(tmp_path, capsys):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {START: 7, NAMED_BY: "end"})[0] == 0

    questions = _questions(report, capsys)

    assert (questions[START]["suggested"], questions[NAMED_BY]["suggested"]) == (7, "end")


@pytest.mark.pbir
def test_given_no_slicer_on_a_fiscal_period_should_leave_the_fiscal_questions_out(tmp_path, capsys):
    report = _bed(tmp_path)
    _set_value(report, "Fiscal Semester", "'FY20-S1'")               # no longer today's period

    questions = _questions(report, capsys)

    assert START not in questions and NAMED_BY not in questions


@pytest.mark.pbir
def test_given_only_calendar_periods_follow_today_should_write_no_fiscal_calendar(tmp_path, capsys):
    report = _bed(tmp_path)
    _set_value(report, "Half Year", "'2026 H2'")

    code, _out, err = _answer(tmp_path, report, capsys, {HALF_YEAR: "current", SEMESTER: "skip"})

    assert code == 0, err
    assert load_contract(_contract(report)).calendar is None
    document = yaml.safe_load(_contract(report).read_text(encoding="utf-8"))
    assert "fabTestCalendar" not in {p["property"] for p in document["customProperties"]}


@pytest.mark.pbir
def test_given_a_fiscal_period_but_no_fiscal_year_answer_should_exit_2_and_write_nothing(tmp_path, capsys):
    report = _bed(tmp_path)

    code, _out, err = _answer(tmp_path, report, capsys, {SEMESTER: "current"})

    assert code == 2 and not _contract(report).exists()
    assert f"{START}: required, because {SEMESTER} follows the fiscal year" in err


@pytest.mark.pbir
def test_given_a_fiscal_year_under_which_the_report_isnt_on_todays_period_should_say_so(tmp_path, capsys):
    report = _bed(tmp_path)

    code, _out, err = _answer(tmp_path, report, capsys, {SEMESTER: "current", START: 4, NAMED_BY: "end"})

    assert code == 2 and not _contract(report).exists()
    assert (f"{SEMESTER}: with a fiscal year starting in April, named by the year it ends in, today is FY27-S2, "
            "but 'Fiscal Calendar'[Fiscal Semester] opens with FY27-S1") in err
    assert "fix the slicer in Desktop and run init again, or answer keep" in err


@pytest.mark.pbir
def test_given_a_january_fiscal_year_should_not_need_the_naming_answer(tmp_path, capsys):
    report = _bed(tmp_path)
    _set_value(report, "Fiscal Semester", "'FY26-S2'")              # Jan-Dec fiscal year: Nov 2026 is FY26-S2

    code, _out, err = _answer(tmp_path, report, capsys, {SEMESTER: "current", START: 1})

    assert code == 0, err
    assert load_contract(_contract(report)).calendar == {"fiscal_year_start_month": 1, "fiscal_year_named_by": "end"}


@pytest.mark.pbir
def test_given_a_terminal_should_re_ask_for_a_fiscal_start_month_until_one_is_typed(tmp_path, capsys, monkeypatch):
    import io

    report = _bed(tmp_path)
    questions = len(_questions(report, capsys)) - 2                  # every slicer and navigator question
    monkeypatch.setattr("sys.stdin", io.StringIO("\n" * questions + "\n7\nend\n"))
    monkeypatch.setattr("fab_test.scripts._slicer_contract_init.can_ask", lambda: True)

    code, _out, err = _run(report, capsys)

    assert code == 0, err
    assert "a fiscal year start month is needed" in err               # the bare Enter was refused
    assert "Is July 2026 to June 2027 called FY27" in err
    assert load_contract(_contract(report)).calendar == {"fiscal_year_start_month": 7, "fiscal_year_named_by": "end"}


@pytest.mark.pbir
def test_given_a_terminal_that_closes_before_the_fiscal_year_is_answered_should_exit_2(tmp_path, capsys, monkeypatch):
    import io

    report = _bed(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("fab_test.scripts._slicer_contract_init.can_ask", lambda: True)

    code, _out, err = _run(report, capsys)

    assert code == 2 and START in err and not _contract(report).exists()


@pytest.mark.pbir
@pytest.mark.parametrize("rule_id", ["date-between-date", "date-relative-date", "input-slicer-name",
                                     "empty-and-all-eye-color", "empty-and-all-alignment"])
def test_given_current_for_a_slicer_with_no_values_ticked_should_exit_2_and_write_nothing(tmp_path, capsys, rule_id):
    report = _bed(tmp_path)

    code, _out, err = _answer(tmp_path, report, capsys, {rule_id: {"current": "{year}"}, SEMESTER: "skip"})

    assert code == 2 and not _contract(report).exists()
    assert f"{rule_id}: only a slicer with values ticked can follow the current period" in err
    assert "Traceback" not in err


@pytest.mark.pbir
def test_given_force_replacing_the_fiscal_year_should_recheck_every_rule_that_follows_it(tmp_path, capsys):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {START: 7, NAMED_BY: "end"})[0] == 0

    code, _out, err = _run(report, capsys, "--force", "--answers",
                           str(_answers_file(tmp_path, {START: 4, NAMED_BY: "end"})))

    assert code == 2, err
    assert f"{SEMESTER}: with a fiscal year starting in April, named by the year it ends in, today is FY27-S2" in err
    assert load_contract(_contract(report)).calendar == {"fiscal_year_start_month": 7, "fiscal_year_named_by": "end"}


@pytest.mark.pbir
def test_given_a_new_fiscal_year_should_say_so_in_the_summary(tmp_path, capsys):
    code, out, err = _answer(tmp_path, _bed(tmp_path), capsys, {START: 7, NAMED_BY: "end"})

    assert code == 0, err
    assert "fabTestCalendar: added (a fiscal year starting in July, named by the year it ends in)" in out


@pytest.mark.pbir
def test_given_the_contracts_fiscal_year_was_kept_over_the_answer_should_say_so_when_refusing(tmp_path, capsys):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {START: 7, NAMED_BY: "end"})[0] == 0
    document = yaml.safe_load(_contract(report).read_text(encoding="utf-8"))   # a wrong fiscal year, set by hand
    next(p for p in document["customProperties"] if p["property"] == "fabTestCalendar")["value"] = {
        "fiscal_year_start_month": 4, "fiscal_year_named_by": "end"}
    for table in document["schema"]:
        for prop in table["properties"]:
            prop["quality"] = [r for r in prop["quality"] if r["id"] != SEMESTER]
    _contract(report).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    code, _out, err = _answer(tmp_path, report, capsys, {START: 7, NAMED_BY: "end"})

    assert code == 2
    assert "the contract's fabTestCalendar was kept over your answers; --force replaces it" in err


@pytest.mark.pbir
def test_given_a_custom_fiscal_format_and_a_contract_with_a_fiscal_year_should_use_it(tmp_path, capsys):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {START: 7, NAMED_BY: "end"})[0] == 0
    _set_value(report, "Fiscal Semester", "'FY2027 Sem 1'")          # no known format: no fiscal questions listed

    code, _out, err = _run(report, capsys, "--force", "--answers", str(_answers_file(
        tmp_path, {SEMESTER: {"current": "FY{fiscal_year} Sem {fiscal_semester}"}})))

    assert code == 0, err


@pytest.mark.pbir
def test_given_fiscal_answers_no_question_listed_should_accept_them(tmp_path, capsys):
    report = _bed(tmp_path)
    _set_value(report, "Fiscal Semester", "'FY2027 Sem 1'")
    assert START not in _questions(report, capsys)

    code, _out, err = _answer(tmp_path, report, capsys, {
        SEMESTER: {"current": "FY{fiscal_year} Sem {fiscal_semester}"}, START: 7, NAMED_BY: "end"})

    assert code == 0, err
    assert load_contract(_contract(report)).calendar == {"fiscal_year_start_month": 7, "fiscal_year_named_by": "end"}


@pytest.mark.pbir
def test_given_a_january_fiscal_year_on_a_terminal_should_not_ask_how_it_is_named(tmp_path, capsys, monkeypatch):
    import io

    report = _bed(tmp_path)
    _set_value(report, "Fiscal Semester", "'FY26-S2'")
    questions = len(_questions(report, capsys)) - 2
    monkeypatch.setattr("sys.stdin", io.StringIO("\n" * questions + "1\n"))   # no answer for the naming question
    monkeypatch.setattr("fab_test.scripts._slicer_contract_init.can_ask", lambda: True)

    code, _out, err = _run(report, capsys)

    assert code == 0, err
    assert "Is January" not in err


def _answers_file(tmp_path: Path, answers: dict) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    return path
