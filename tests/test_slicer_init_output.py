"""`contract init` under the output flags every fab-test command takes (PBIR Slicer Default State epic).

-q prints nothing on success (the exit code is the result), -v lists every
rule the contract holds, ANALYZER_VERBOSITY works as for the other commands,
and --report / --open-report say which command makes a report rather than
failing as unrecognised arguments. Errors and asked-for output always print.
"""

import json
import shutil
from pathlib import Path

import pytest

from fab_test.scripts._slicer_contract_init import contract_main

ROOT = Path(__file__).resolve().parents[1]
TEST_BED = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report"
FISCAL_YEAR = {"calendar.fiscal_year_start_month": 7, "calendar.fiscal_year_named_by": "end"}


def _bed(tmp_path: Path) -> Path:
    report = tmp_path / TEST_BED.name
    shutil.copytree(TEST_BED, report)
    return report


def _run(tmp_path: Path, capsys, *flags: str, answers: dict = FISCAL_YEAR):
    report = _bed(tmp_path)
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    code = contract_main(["init", str(report), "--as-of", "2026-11-14", "--answers", str(path), *flags])
    out, err = capsys.readouterr()
    return code, out, err, report.parent / f"{report.name}.odcs.yaml"


@pytest.mark.pbir
@pytest.mark.parametrize("quiet", [["-q"], ["--quiet"]])
def test_given_quiet_should_write_the_contract_and_print_nothing(tmp_path, capsys, quiet):
    code, out, err, contract = _run(tmp_path, capsys, *quiet)

    assert (code, out, err) == (0, "", "") and contract.exists()


@pytest.mark.pbir
def test_given_analyzer_verbosity_summary_should_be_quiet_too(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")

    assert _run(tmp_path, capsys)[:3] == (0, "", "")


@pytest.mark.pbir
def test_given_quiet_and_json_should_still_print_the_one_json_document(tmp_path, capsys):
    code, out, _err, _contract = _run(tmp_path, capsys, "-q", "--format", "json")

    assert code == 0 and json.loads(out)["written"] is True


@pytest.mark.pbir
def test_given_quiet_and_questions_should_still_print_the_questions_asked_for(tmp_path, capsys):
    code = contract_main(["init", str(_bed(tmp_path)), "--as-of", "2026-11-14", "--questions", "-q"])

    assert code == 0 and "standard-slicers-alignment" in capsys.readouterr().out


@pytest.mark.pbir
def test_given_quiet_should_still_print_an_error(tmp_path, capsys):
    code, out, err, contract = _run(tmp_path, capsys, "-q", answers={})              # no fiscal year

    assert code == 2 and out == "" and "calendar.fiscal_year_start_month: required" in err
    assert not contract.exists()


@pytest.mark.pbir
@pytest.mark.parametrize("verbose", [["-v"], ["--verbose"], ["-vv"]])
def test_given_verbose_should_list_every_rule_with_its_check_and_what_happened(tmp_path, capsys, verbose):
    code, out, _err, _contract = _run(tmp_path, capsys, *verbose)

    assert code == 0
    assert "standard-slicers-alignment  Standard Slicers  'AlignmentDim'[Alignment]  selected: ['Bad']  added" in out
    assert ("standard-slicers-fiscal-semester  Standard Slicers  'Fiscal Calendar'[Fiscal Semester]  "
            "selected: ['FY{fiscal_year_short}-S{fiscal_semester}']  added") in out
    assert "page-1-bookmark-navigator  Page 1  bookmark navigator  selected: Bookmark 2  added" in out


@pytest.mark.pbir
def test_given_the_default_should_not_list_each_rule(tmp_path, capsys):
    _code, out, _err, _contract = _run(tmp_path, capsys)

    assert "added:" in out and "selected: ['Bad']" not in out


@pytest.mark.pbir
@pytest.mark.parametrize("flag", ["--report", "--open-report", "--no-report"])
def test_given_a_report_flag_should_name_the_command_that_makes_one(tmp_path, capsys, flag):
    code, _out, err, contract = _run(tmp_path, capsys, flag)

    assert code == 2 and not contract.exists()
    assert ("contract init writes a contract, not a report; see it checked with "
            "fab-test pbir --artifact SampleModel-DefaultState --open-report") in err


@pytest.mark.pbir
def test_given_quiet_and_verbose_together_should_refuse_as_every_command_does(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        _run(tmp_path, capsys, "-q", "-v")

    assert caught.value.code == 2
