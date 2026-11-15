"""Contract Init Generator (PBIR Slicer Default State epic): `fab-test pbir contract init`.

In-process against a copy of the SampleModel-DefaultState test bed. The
generated contract is checked by reading it back with the contract reader,
so a generated file is always one `fab-test pbir` accepts.
"""

import datetime
import io
import json
import shutil
from pathlib import Path

import pytest
import yaml

from fab_test.scripts._slicer_calendar import resolve_contract
from fab_test.scripts._slicer_contract import load_contract
from fab_test.scripts._slicer_contract_init import contract_main

ROOT = Path(__file__).resolve().parents[1]
TEST_BED = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report"
AS_OF = "2026-11-14"
SEMESTER = "standard-slicers-fiscal-semester"


def _bed(tmp_path: Path) -> Path:
    report = tmp_path / TEST_BED.name
    shutil.copytree(TEST_BED, report)
    return report


def _run(report: Path, capsys, *extra: str, tty: bool = False, monkeypatch=None, typed: str = ""):
    if monkeypatch is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(typed))
        monkeypatch.setattr("sys.stdin.isatty", lambda: tty, raising=False)
    code = contract_main(["init", str(report), "--as-of", AS_OF, *extra])
    out, err = capsys.readouterr()
    return code, out, err


def _questions(report: Path, capsys) -> dict:
    code, out, _err = _run(report, capsys, "--questions", "--format", "json")
    assert code == 0
    return json.loads(out)


def _answers(tmp_path: Path, answers: dict) -> str:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    return str(path)


def _contract_path(report: Path) -> Path:
    return report.parent / f"{report.name}.odcs.yaml"


@pytest.mark.pbir
def test_given_questions_as_json_should_list_every_slicer_with_its_current_selection(tmp_path, capsys):
    report = _bed(tmp_path)

    questions = {q["id"]: q for q in _questions(report, capsys)["questions"]}

    assert questions["standard-slicers-alignment"]["current"] == {"selected": ["Bad"]}
    assert questions["standard-slicers-year"]["current"] == {"selected": [1940]}
    assert questions["standard-slicers-chart-measure"]["current"] == {"selected": ["Number of Characters"]}
    assert questions["date-between-date"]["current"] == {"range": {"to": "2026-10-28"}}
    assert questions["date-relative-date"]["current"] == {
        "relative": {"range": "Last", "duration": 20, "period": "Calendar Months"}}
    assert questions["date-picker-date"]["current"] == {"range": {"from": "1939-10-01", "to": "1951-08-27"}}
    assert questions["input-slicer-name"]["current"] == {"contains": ["Wolverine"]}
    assert all(q["choices"][0] == "keep" and q["suggested"] for q in questions.values() if "page" in q)


@pytest.mark.pbir
def test_given_a_current_calendar_value_should_suggest_a_format_and_a_calendar_that_reproduce_it(tmp_path, capsys):
    report = _bed(tmp_path)

    questions = {q["id"]: q for q in _questions(report, capsys)["questions"]}

    semester = questions[SEMESTER]
    assert semester["suggested"] == "calendar" and semester["needs_human"] is True
    assert semester["calendar_format"] == "FY{fiscal_year_short}-S{fiscal_semester}"
    start = questions["calendar.fiscal_year_start_month"]
    assert start["suggested"] == 7 and 7 in start["reproduces"] and start["needs_human"] is True
    assert "calendar_format" not in questions["standard-slicers-half-year"]  # 2025 H2 is stale today


@pytest.mark.pbir
def test_given_suggested_answers_should_write_a_contract_the_reader_accepts_and_that_matches_today(
        tmp_path, capsys):
    report = _bed(tmp_path)
    suggested = {q["id"]: q["suggested"] for q in _questions(report, capsys)["questions"]}

    code, _out, err = _run(report, capsys, "--answers", _answers(tmp_path, suggested))

    assert code == 0, err
    contract = load_contract(_contract_path(report))
    resolved = {e.rule_id: e for e in resolve_contract(contract, datetime.date(2026, 11, 14))}
    assert contract.report_logical_id == "b3cba6e7-ddfc-4bcd-b4b1-5f2a3d5297fc"
    assert contract.calendar == {"fiscal_year_start_month": 7, "fiscal_year_named_by": "end"}
    assert resolved[SEMESTER].expected == ["FY27-S1"]
    assert resolved["date-between-date"].expected == {"to": datetime.date(2026, 10, 28)}
    assert len(resolved) == 10


@pytest.mark.pbir
def test_given_skip_should_leave_that_slicer_out(tmp_path, capsys):
    report = _bed(tmp_path)

    _run(report, capsys, "--answers", _answers(tmp_path, {"standard-slicers-alignment": "skip"}))

    ids = {e.rule_id for e in load_contract(_contract_path(report)).expectations}
    assert "standard-slicers-alignment" not in ids and "standard-slicers-eye-color" in ids


@pytest.mark.pbir
def test_given_no_terminal_and_no_answers_should_exit_2_naming_both_flags(tmp_path, capsys, monkeypatch):
    report = _bed(tmp_path)

    code, _out, err = _run(report, capsys, monkeypatch=monkeypatch, tty=False)

    assert code == 2 and "--questions" in err and "--answers" in err
    assert not _contract_path(report).exists()


@pytest.mark.pbir
def test_given_a_terminal_should_ask_and_take_the_suggestion_on_enter(tmp_path, capsys, monkeypatch):
    report = _bed(tmp_path)

    code, out, _err = _run(report, capsys, monkeypatch=monkeypatch, tty=True, typed="skip\n" + "\n" * 40)

    assert code == 0
    ids = {e.rule_id for e in load_contract(_contract_path(report)).expectations}
    assert len(ids) == 9  # the first slicer asked was skipped
    assert "keep" in out and "calendar" in out


@pytest.mark.pbir
def test_given_an_existing_contract_should_append_new_slicers_and_keep_edited_rules(tmp_path, capsys):
    report = _bed(tmp_path)
    _run(report, capsys, "--answers", _answers(tmp_path, {"standard-slicers-eye-color": "skip"}))
    document = yaml.safe_load(_contract_path(report).read_text(encoding="utf-8"))
    for table in document["schema"]:
        for column in table["properties"]:
            for rule in column["quality"]:
                if rule["id"] == "standard-slicers-alignment":
                    rule["implementation"]["selected"] = ["Good"]  # a hand edit
    _contract_path(report).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    code, out, _err = _run(report, capsys, "--answers", _answers(tmp_path, {}), "--format", "json")

    summary = json.loads(out)
    by_id = {e.rule_id: e.expected for e in load_contract(_contract_path(report)).expectations}
    assert code == 0
    assert summary["added"] == ["standard-slicers-eye-color"]
    assert "standard-slicers-alignment" in summary["kept"]
    assert by_id["standard-slicers-alignment"] == ["Good"]


@pytest.mark.pbir
def test_given_force_should_replace_an_edited_rule(tmp_path, capsys):
    report = _bed(tmp_path)
    _run(report, capsys, "--answers", _answers(tmp_path, {}))
    text = _contract_path(report).read_text(encoding="utf-8").replace("- Bad", "- Good")
    _contract_path(report).write_text(text, encoding="utf-8")

    _run(report, capsys, "--answers", _answers(tmp_path, {}), "--force")

    by_id = {e.rule_id: e.expected for e in load_contract(_contract_path(report)).expectations}
    assert by_id["standard-slicers-alignment"] == ["Bad"]


@pytest.mark.pbir
def test_given_a_contract_with_comments_should_refuse_to_rewrite_it_without_force(tmp_path, capsys):
    report = _bed(tmp_path)
    _run(report, capsys, "--answers", _answers(tmp_path, {"standard-slicers-eye-color": "skip"}))
    original = "# agreed with the customer\n" + _contract_path(report).read_text(encoding="utf-8")
    _contract_path(report).write_text(original, encoding="utf-8")

    code, _out, err = _run(report, capsys, "--answers", _answers(tmp_path, {}))

    assert code == 2 and "comment" in err and "--force" in err
    assert _contract_path(report).read_text(encoding="utf-8") == original


@pytest.mark.pbir
def test_given_dry_run_should_print_the_contract_and_write_nothing(tmp_path, capsys):
    report = _bed(tmp_path)

    code, out, _err = _run(report, capsys, "--answers", _answers(tmp_path, {}), "--dry-run")

    assert code == 0 and "engine: fab-test" in out
    assert not _contract_path(report).exists()


@pytest.mark.pbir
def test_given_an_unknown_answer_should_exit_2_naming_it(tmp_path, capsys):
    report = _bed(tmp_path)

    code, _out, err = _run(report, capsys, "--answers", _answers(tmp_path, {"standard-slicers-alignment": "maybe"}))

    assert code == 2 and "standard-slicers-alignment" in err and "maybe" in err
