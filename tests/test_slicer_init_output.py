"""`contract init` under the output flags every fab-test command takes (PBIR Slicer Default State epic).

-q prints one result line, shaped like the run's (`contract written added=N
replaced=N kept=N PATH`, as `fab-test pbir -q` prints `pbir passed e=0 w=0
PATH`), -v lists every rule the contract holds, ANALYZER_VERBOSITY works as for the other commands,
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
def test_given_quiet_should_write_the_contract_and_print_one_result_line(tmp_path, capsys, quiet):
    code, out, err, contract = _run(tmp_path, capsys, *quiet)

    assert (code, err) == (0, "") and contract.exists()
    assert out == f"contract written added=15 replaced=0 kept=0 unchanged=0 {contract}\n"


def _quiet_line(out: str) -> bool:
    return out.startswith("contract written added=") and out.count("\n") == 1


@pytest.mark.pbir
def test_given_analyzer_verbosity_summary_should_be_quiet_too(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
    code, out, err, _contract = _run(tmp_path, capsys)

    assert (code, err) == (0, "") and _quiet_line(out)


@pytest.mark.pbir
def test_given_fab_test_yml_verbosity_summary_should_be_quiet_too(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANALYZER_VERBOSITY", raising=False)
    (tmp_path / "fab-test.yml").write_text("verbosity: summary\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, out, err, _contract = _run(tmp_path, capsys)

    assert (code, err) == (0, "") and _quiet_line(out)


@pytest.mark.pbir
@pytest.mark.parametrize("flag", [["--contract", "c.odcs.yaml"], ["--output-dir", "out"]])
def test_given_a_flag_of_fab_test_pbir_should_name_that_command(tmp_path, capsys, flag):
    code, _out, err, contract = _run(tmp_path, capsys, *flag)

    assert code == 2 and not contract.exists()
    assert f"{flag[0]}: contract init writes <Report>.Report.odcs.yaml to fab-tests/pbir/" in err
    assert f"fab-test pbir SampleModel-DefaultState {flag[0]} ..." in err


@pytest.mark.pbir
def test_given_ctrl_c_while_asking_should_exit_130_without_a_traceback(tmp_path, capsys, monkeypatch):
    def interrupted(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr("fab_test.scripts._slicer_contract_init._answers", interrupted)

    code, _out, err, contract = _run(tmp_path, capsys)

    assert code == 130 and "Traceback" not in err and not contract.exists()


@pytest.mark.pbir
def test_given_quiet_and_dry_run_should_print_only_the_contract(tmp_path, capsys):
    code, out, _err, contract = _run(tmp_path, capsys, "-q", "--dry-run")

    assert code == 0 and not contract.exists()
    assert out.startswith("apiVersion: v3.1.0") and "contract written" not in out


@pytest.mark.pbir
def test_given_format_json_in_fab_test_yml_should_print_json_without_the_flag(tmp_path, capsys, monkeypatch):
    (tmp_path / "fab-test.yml").write_text("format: json\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, out, _err, _contract = _run(tmp_path, capsys)

    assert code == 0 and json.loads(out)["written"] is True


@pytest.mark.pbir
def test_given_the_format_flag_should_win_over_fab_test_yml(tmp_path, capsys, monkeypatch):
    (tmp_path / "fab-test.yml").write_text("format: json\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, out, _err, _contract = _run(tmp_path, capsys, "--format", "text")

    assert code == 0 and out.lstrip().startswith("✓")


@pytest.mark.pbir
def test_given_artifact_dir_in_fab_test_yml_should_find_the_report_by_name(tmp_path, capsys, monkeypatch):
    (tmp_path / "reports").mkdir()
    shutil.copytree(TEST_BED, tmp_path / "reports" / TEST_BED.name)
    (tmp_path / "fab-test.yml").write_text("artifact_dir: reports\n", encoding="utf-8")
    (tmp_path / "answers.json").write_text(json.dumps(FISCAL_YEAR), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code = contract_main(["init", "SampleModel-DefaultState", "--as-of", "2026-11-14", "--answers", "answers.json"])

    assert code == 0 and (tmp_path / "reports" / f"{TEST_BED.name}.odcs.yaml").exists()


@pytest.mark.pbir
@pytest.mark.parametrize("target", ["SampleModel-DefaultState", "SampleModel-DefaultState.Report"])
def test_given_a_report_name_as_target_should_find_it_under_artifact_dir(tmp_path, capsys, target):
    _bed(tmp_path)
    (tmp_path / "answers.json").write_text(json.dumps(FISCAL_YEAR), encoding="utf-8")

    code = contract_main(["init", target, "--artifact-dir", str(tmp_path), "--as-of", "2026-11-14",
                          "--answers", str(tmp_path / "answers.json"), "-q"])

    assert code == 0 and (tmp_path / f"{TEST_BED.name}.odcs.yaml").exists()


@pytest.mark.pbir
def test_given_quiet_and_nothing_changed_should_say_unchanged(tmp_path, capsys):
    code, _out, _err, contract = _run(tmp_path, capsys, "-q")
    path = tmp_path / "answers.json"
    rerun = contract_main(["init", str(contract.parent / TEST_BED.name), "--as-of", "2026-11-14",
                           "--answers", str(path), "-q"])

    assert (code, rerun) == (0, 0)
    assert capsys.readouterr().out.startswith("contract unchanged added=0 replaced=0 kept=0 unchanged=15 ")


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
    assert "standard-slicers-alignment  Standard Slicers  'AlignmentDim'[Alignment] opens with Bad  added" in out
    assert ("standard-slicers-fiscal-semester  Standard Slicers  'Fiscal Calendar'[Fiscal Semester] "
            "opens with FY{fiscal_year_short}-S{fiscal_semester}  added") in out
    assert "opens up to 2026-10-28  added" in out and "datetime.date" not in out          # words, not reprs
    assert "page-1-bookmark-navigator  Page 1  bookmark navigator opens with Bookmark 2  added" in out


@pytest.mark.pbir
def test_given_the_default_should_not_list_each_rule(tmp_path, capsys):
    _code, out, _err, _contract = _run(tmp_path, capsys)

    assert "added:" in out and "opens with Bad" not in out


@pytest.mark.pbir
@pytest.mark.parametrize("flag", ["--report", "--open-report", "--no-report"])
def test_given_a_report_flag_should_name_the_command_that_makes_one(tmp_path, capsys, flag):
    code, _out, err, contract = _run(tmp_path, capsys, flag)

    assert code == 2 and not contract.exists()
    assert ("contract init writes a contract, not an HTML report; see it checked with "
            "fab-test pbir SampleModel-DefaultState --open-report") in err


@pytest.mark.pbir
def test_given_quiet_and_verbose_together_should_refuse_as_every_command_does(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        _run(tmp_path, capsys, "-q", "-v")

    assert caught.value.code == 2


class _Stream:
    """A stream that says whether it is a terminal, as `sys.stdin` / `sys.stderr` do."""

    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.mark.pbir
def test_given_answers_typed_but_prompts_not_shown_should_not_ask(monkeypatch):
    from fab_test.scripts import _slicer_init_output as output

    monkeypatch.setattr("sys.stdin", _Stream(tty=True))
    monkeypatch.setattr("sys.stderr", _Stream(tty=False))

    assert not output.can_ask()                                             # nobody would see the questions


@pytest.mark.pbir
def test_given_the_null_device_should_not_ask(monkeypatch):
    import os

    from fab_test.scripts import _slicer_init_output as output

    with open(os.devnull, encoding="utf-8") as null_in, open(os.devnull, "w", encoding="utf-8") as null_out:
        monkeypatch.setattr("sys.stdin", null_in)
        monkeypatch.setattr("sys.stderr", null_out)

        assert not output.can_ask()                                         # Windows reports NUL as a tty


@pytest.mark.pbir
def test_given_a_terminal_on_both_should_ask(monkeypatch):
    from fab_test.scripts import _slicer_init_output as output

    monkeypatch.setattr("sys.stdin", _Stream(tty=True))
    monkeypatch.setattr("sys.stderr", _Stream(tty=True))
    monkeypatch.setattr(output, "_console", lambda stream: True)            # a real Windows console

    assert output.can_ask()


@pytest.mark.pbir
def test_given_a_tty_that_is_not_a_windows_console_should_not_ask(monkeypatch):
    from fab_test.scripts import _slicer_init_output as output

    monkeypatch.setattr("sys.stdin", _Stream(tty=True))
    monkeypatch.setattr("sys.stderr", _Stream(tty=True))
    monkeypatch.setattr(output.os, "name", "nt")

    assert not output.can_ask()                                             # no handle: no console mode


@pytest.mark.pbir
def test_given_stdin_on_the_null_device_should_exit_2_and_write_nothing(tmp_path):
    import os
    import subprocess
    import sys

    report = _bed(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "pbir", "contract", "init", str(report)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "no terminal to ask on" in result.stderr and "--answers FILE" in result.stderr
    assert "✓" not in result.stdout
    assert not list(tmp_path.glob("*.odcs.yaml"))


@pytest.mark.pbir
def test_given_stdin_and_stderr_on_the_null_device_should_not_answer_for_anyone(tmp_path):
    """The pilot's run (C1): a report with no fiscal question, so taking every default would write a contract."""
    import os
    import subprocess
    import sys

    report = tmp_path / "SampleModel-PQLAssert.Report"
    shutil.copytree(ROOT / "fabric-artifacts" / report.name, report)

    result = subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "pbir", "contract", "init", str(report)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        check=False, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert result.returncode == 2 and "✓" not in result.stdout
    assert not list(tmp_path.glob("*.odcs.yaml"))
