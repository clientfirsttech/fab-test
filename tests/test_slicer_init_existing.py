"""`contract init` and a contract that already exists (PBIR Slicer Default State epic).

Whatever would stop init from writing is found before the first question, so
nobody answers every slicer only to be refused: a comment rewriting would
drop, a file that isn't a contract, an id two rules share, or, with no
contract yet, a report with no logicalId to pair by. The ids the contract
already gives a slicer or navigator are reused, and the rest are avoided.
"""

import io
import json
import shutil
from pathlib import Path

import pytest
import yaml

from fab_test.scripts._slicer_contract import load_contract
from fab_test.scripts._slicer_contract_init import contract_main

ROOT = Path(__file__).resolve().parents[1]
TEST_BED = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report"
FISCAL_YEAR = {"calendar.fiscal_year_start_month": 7, "calendar.fiscal_year_named_by": "end"}
ALIGNMENT, YEAR = "standard-slicers-alignment", "standard-slicers-year"


def _bed(tmp_path: Path) -> Path:
    report = tmp_path / TEST_BED.name
    shutil.copytree(TEST_BED, report)
    return report


def _contract(report: Path) -> Path:
    return report.parent / f"{report.name}.odcs.yaml"


def _run(report: Path, capsys, *extra: str) -> tuple[int, str, str]:
    code = contract_main(["init", str(report), "--as-of", "2026-11-14", *extra])
    out, err = capsys.readouterr()
    return code, out, err


def _answer(tmp_path: Path, report: Path, capsys, answers: dict, *extra: str) -> tuple[int, str, str]:
    path = tmp_path / "answers.json"
    path.write_text(json.dumps({**FISCAL_YEAR, **answers}), encoding="utf-8")
    return _run(report, capsys, "--answers", str(path), *extra)


def _on_a_terminal(report: Path, capsys, monkeypatch) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("fab_test.scripts._slicer_contract_init.can_ask", lambda: True)
    return _run(report, capsys)


def _edit(report: Path, change) -> None:
    document = yaml.safe_load(_contract(report).read_text(encoding="utf-8"))
    change(document)
    _contract(report).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _rules(document: dict):
    return [(table["name"], prop["name"], rule) for table in document["schema"] for prop in table["properties"]
            for rule in prop.get("quality", [])]


def _ids(report: Path, capsys) -> list[str]:
    code, out, err = _run(report, capsys, "--questions", "--format", "json")
    assert code == 0, err
    return [q["id"] for q in json.loads(out)["questions"]]


@pytest.mark.pbir
def test_given_a_commented_contract_should_refuse_before_the_first_question(tmp_path, capsys, monkeypatch):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {})[0] == 0
    _contract(report).write_text("# agreed\n" + _contract(report).read_text(encoding="utf-8"), encoding="utf-8")

    code, _out, err = _on_a_terminal(report, capsys, monkeypatch)

    assert code == 2 and "contains '#'" in err and "--force" in err
    assert "Keep checking" not in err and "Keep " not in err                    # nothing was asked
    assert _run(report, capsys, "--questions")[0] == 2                        # nor listed for an agent to ask


@pytest.mark.pbir
def test_given_a_report_without_a_logical_id_should_refuse_before_the_first_question(tmp_path, capsys, monkeypatch):
    report = _bed(tmp_path)
    (report / ".platform").unlink()

    code, _out, err = _on_a_terminal(report, capsys, monkeypatch)

    assert code == 2 and "logicalId" in err and "Keep " not in err
    assert _run(report, capsys, "--questions")[0] == 2


@pytest.mark.pbir
def test_given_a_contract_whose_rules_share_an_id_should_refuse_before_the_first_question(tmp_path, capsys,
                                                                                           monkeypatch):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {})[0] == 0
    _edit(report, lambda d: next(r for t, c, r in _rules(d) if c == "Year").update(id=ALIGNMENT))

    code, _out, err = _on_a_terminal(report, capsys, monkeypatch)

    assert code == 2 and f"id '{ALIGNMENT}' is used by more than one rule" in err and "Keep " not in err


@pytest.mark.pbir
@pytest.mark.parametrize("text", ["schema: [unclosed\n", "- a list\n"])
def test_given_a_file_that_isnt_a_contract_should_exit_2_without_a_traceback(tmp_path, capsys, text):
    report = _bed(tmp_path)
    _contract(report).write_text(text, encoding="utf-8")

    code, _out, err = _run(report, capsys, "--questions")

    assert code == 2 and "Traceback" not in err and str(_contract(report).name) in err


@pytest.mark.pbir
def test_given_an_id_the_contract_gives_another_slicer_should_pick_another(tmp_path, capsys):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {YEAR: "skip"})[0] == 0
    _edit(report, lambda d: next(r for t, c, r in _rules(d) if r["id"] == ALIGNMENT).update(id=YEAR))

    code, _out, err = _answer(tmp_path, report, capsys, {})

    assert code == 0, err
    rules = {r["id"]: c for t, c, r in _rules(yaml.safe_load(_contract(report).read_text(encoding="utf-8")))}
    assert rules[YEAR] == "Alignment" and rules[f"{YEAR}-2"] == "Year"
    assert ALIGNMENT not in rules                                              # its rule kept the id it was given


@pytest.mark.pbir
def test_given_a_renamed_rule_should_reuse_its_id_rather_than_add_a_second_rule(tmp_path, capsys):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {})[0] == 0
    _edit(report, lambda d: next(r for t, c, r in _rules(d) if r["id"] == ALIGNMENT).update(id="alignment-default"))

    assert "alignment-default" in _ids(report, capsys) and ALIGNMENT not in _ids(report, capsys)
    code, out, err = _answer(tmp_path, report, capsys, {})

    assert code == 0, err
    assert "added" not in out
    assert [e.rule_id for e in load_contract(_contract(report)).expectations
                                    if (e.page, e.column) == ("Standard Slicers", "Alignment")] == [
        "alignment-default"]


@pytest.mark.pbir
def test_given_a_renamed_navigator_should_reuse_its_id(tmp_path, capsys):
    report = _bed(tmp_path)
    assert _answer(tmp_path, report, capsys, {})[0] == 0

    def rename(document: dict) -> None:
        navigators = next(p for p in document["customProperties"] if p["property"] == "fabTestBookmarkNavigators")
        next(n for n in navigators["value"] if n["page"] == "Page 1")["id"] = "home-navigator"

    _edit(report, rename)

    assert "home-navigator" in _ids(report, capsys) and "page-1-bookmark-navigator" not in _ids(report, capsys)
    code, _out, err = _answer(tmp_path, report, capsys, {})
    assert code == 0, err
    assert [n.rule_id for n in load_contract(_contract(report)).navigators if n.page == "Page 1"] == ["home-navigator"]
