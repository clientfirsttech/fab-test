"""`fab-test pbir contract lint`: check a report's contract without running it (Authoring Command Grammar epic).

Lint takes the report as `fab-test pbir` and `contract init` take it, finds the
contract that pairs with it, and runs two checks: fab-test reads it as the run
will, and pql-test (shipped with fab-test) validates it against ODCS and
resolves its names in the report's semantic model. A problem in the file is a
finding (exit 1); exit 2 means lint couldn't check at all.
"""

import json
import shutil
from pathlib import Path

import pytest

from fab_test.scripts import _slicer_contract_lint
from fab_test.scripts._slicer_contract_init import contract_main

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "fabric-artifacts"
REPORT = "SampleModel-DefaultState.Report"
MODEL = "SampleModel-PQLAssert.SemanticModel"
CONTRACT = f"{REPORT}.odcs.yaml"
EXAMPLE = ROOT / "fab-tests" / "pbir" / CONTRACT  # decision 22: test files live in fab-tests/


def _bed(tmp_path: Path, contract: str | None = None) -> Path:
    """The test bed's report, its model and its contract, side by side (a contract still pairs beside its report)."""
    shutil.copytree(ARTIFACTS / REPORT, tmp_path / REPORT)
    shutil.copytree(ARTIFACTS / MODEL, tmp_path / MODEL)
    text = EXAMPLE.read_text(encoding="utf-8")
    (tmp_path / CONTRACT).write_text(text if contract is None else contract, encoding="utf-8")
    return tmp_path / CONTRACT


def _lint(tmp_path: Path, capsys, *flags: str):
    code = contract_main(["lint", "SampleModel-DefaultState", "--artifact-dir", str(tmp_path),
                          "--as-of", "2026-11-14", *flags])
    out, err = capsys.readouterr()
    return code, out, err


def _broken(old: str, new: str) -> str:
    text = EXAMPLE.read_text(encoding="utf-8")
    assert old in text
    return text.replace(old, new, 1)


@pytest.mark.pbir
def test_given_a_clean_contract_should_pass_and_name_the_run_as_the_next_step(tmp_path, capsys):
    contract = _bed(tmp_path)
    code, out, err = _lint(tmp_path, capsys)

    assert (code, err) == (0, "")
    assert f"✓ {contract}: valid ODCS v3.1.0" in out and f"names resolve in {MODEL}" in out
    assert f"Next: fab-test pbir SampleModel-DefaultState --artifact-dir {tmp_path}" in out


@pytest.mark.pbir
def test_given_quiet_should_print_one_line_shaped_like_the_runs(tmp_path, capsys):
    contract = _bed(tmp_path)

    assert _lint(tmp_path, capsys, "-q") == (0, f"contract lint passed problems=0 {contract}\n", "")


@pytest.mark.pbir
def test_given_format_json_should_print_one_document_with_the_next_step(tmp_path, capsys):
    _bed(tmp_path)
    code, out, _err = _lint(tmp_path, capsys, "--format", "json")
    result = json.loads(out)

    assert code == 0 and result["ok"] is True
    assert result["next"] == f"fab-test pbir SampleModel-DefaultState --artifact-dir {tmp_path}"
    assert [c["problems"] for c in result["contracts"]] == [[]] and result["contracts"][0]["model"].endswith(MODEL)


@pytest.mark.pbir
def test_given_verbose_should_name_the_model_and_both_checks(tmp_path, capsys):
    _bed(tmp_path)
    code, out, _err = _lint(tmp_path, capsys, "-v")

    assert code == 0 and f"model: {tmp_path / MODEL}" in out
    assert "fab-test: reads as fab-test pbir reads it, as of 2026-11-14" in out and "pql-test " in out


@pytest.mark.pbir
def test_given_a_column_the_model_does_not_have_should_fail_naming_it(tmp_path, capsys):
    _bed(tmp_path, _broken("name: Alignment\n", "name: Alignmentt\n"))
    code, out, _err = _lint(tmp_path, capsys)

    assert code == 1
    assert "pql-test: AlignmentDim.Alignmentt: column 'Alignmentt' not found in model table 'AlignmentDim'" in out


@pytest.mark.pbir
def test_given_a_rule_fab_test_cannot_read_should_fail_naming_it(tmp_path, capsys):
    _bed(tmp_path, _broken("period: Calendar Months}", "period: Fortnights}"))
    code, out, _err = _lint(tmp_path, capsys, "--format", "json")
    problems = json.loads(out)["contracts"][0]["problems"]

    assert code == 1 and any(p["source"] == "fab-test" and "Fortnights" in p["message"] for p in problems)


@pytest.mark.pbir
def test_given_a_file_that_is_not_yaml_should_fail_once_not_twice(tmp_path, capsys):
    _bed(tmp_path, "apiVersion: v3.1.0\nschema: [\n")
    code, out, _err = _lint(tmp_path, capsys, "--format", "json")
    problems = json.loads(out)["contracts"][0]["problems"]

    assert code == 1 and len(problems) == 1 and "not valid YAML" in problems[0]["message"]


@pytest.mark.pbir
def test_given_quiet_and_a_problem_should_print_the_line_and_the_problem_on_stderr(tmp_path, capsys):
    contract = _bed(tmp_path, _broken("name: Alignment\n", "name: Alignmentt\n"))
    code, out, err = _lint(tmp_path, capsys, "-q")

    assert code == 1 and out == f"contract lint failed problems=1 {contract}\n" and "Alignmentt" in err


@pytest.mark.pbir
def test_given_no_contract_pairs_should_exit_2_naming_init(tmp_path, capsys):
    _bed(tmp_path).unlink()
    code, out, err = _lint(tmp_path, capsys)

    assert (code, out) == (2, "") and "fab-test pbir contract init SampleModel-DefaultState" in err


@pytest.mark.pbir
def test_given_a_contract_named_otherwise_should_pair_by_the_reports_logical_id(tmp_path, capsys):
    _bed(tmp_path).rename(tmp_path / "opening-state.odcs.yaml")
    code, out, _err = _lint(tmp_path, capsys)

    assert code == 0 and "opening-state.odcs.yaml" in out


@pytest.mark.pbir
def test_given_two_contracts_for_one_report_should_exit_2_naming_both(tmp_path, capsys):
    contract = _bed(tmp_path)
    shutil.copy(contract, tmp_path / "copy.odcs.yaml")
    code, _out, err = _lint(tmp_path, capsys)

    assert code == 2 and CONTRACT in err and "copy.odcs.yaml" in err


@pytest.mark.pbir
def test_given_contract_flag_should_lint_that_file(tmp_path, capsys):
    contract = _bed(tmp_path)
    other = tmp_path / "elsewhere" / "mine.odcs.yaml"
    other.parent.mkdir()
    contract.rename(other)
    code, out, _err = _lint(tmp_path, capsys, "--contract", str(other))

    assert code == 0 and str(other) in out


@pytest.mark.pbir
def test_given_a_contract_for_another_report_should_fail(tmp_path, capsys):
    contract = _bed(tmp_path, _broken("value: b3cba6e7-ddfc-4bcd-b4b1-5f2a3d5297fc",
                                      "value: 00000000-0000-0000-0000-000000000000"))
    code, out, _err = _lint(tmp_path, capsys, "--contract", str(contract))

    assert code == 1 and "pairs with report 00000000-0000-0000-0000-000000000000" in out


@pytest.mark.pbir
def test_given_a_model_outside_the_folder_should_check_the_rest_and_say_names_were_not(tmp_path, capsys):
    _bed(tmp_path)
    shutil.rmtree(tmp_path / MODEL)
    code, out, _err = _lint(tmp_path, capsys)

    assert code == 0 and "names not checked: the report's semantic model isn't in this folder" in out


@pytest.mark.pbir
@pytest.mark.parametrize("flag", ["--report", "--open-report", "--no-report"])
def test_given_a_report_flag_should_name_the_command_that_makes_one(tmp_path, capsys, flag):
    _bed(tmp_path)
    code, out, err = _lint(tmp_path, capsys, flag)

    assert (code, out) == (2, "")
    assert ("contract lint checks a contract, not an HTML report; see it checked with "
            "fab-test pbir SampleModel-DefaultState --open-report") in err


@pytest.mark.pbir
def test_given_output_dir_should_say_lint_writes_nothing(tmp_path, capsys):
    _bed(tmp_path)
    code, _out, err = _lint(tmp_path, capsys, "--output-dir", "out")

    assert code == 2 and "contract lint writes nothing" in err


@pytest.mark.pbir
def test_given_pql_test_missing_should_exit_127_naming_the_fix(tmp_path, capsys, monkeypatch):
    _bed(tmp_path)
    monkeypatch.setattr(_slicer_contract_lint, "_PQL_TEST", "pql_test_not_installed")
    code, _out, err = _lint(tmp_path, capsys)

    assert code == 127 and "pip install cft-fab-test" in err


@pytest.mark.pbir
def test_given_init_should_name_lint_as_the_next_step(tmp_path, capsys):
    shutil.copytree(ARTIFACTS / REPORT, tmp_path / REPORT)
    (tmp_path / "a.json").write_text(json.dumps({"calendar.fiscal_year_start_month": 7,
                                                 "calendar.fiscal_year_named_by": "end"}), encoding="utf-8")
    flags = ["init", str(tmp_path / REPORT), "--as-of", "2026-11-14", "--answers", str(tmp_path / "a.json")]

    assert contract_main(flags) == 0
    assert capsys.readouterr().out.rstrip().endswith(f"Next: fab-test pbir contract lint {tmp_path / REPORT}")
    assert contract_main([*flags, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["next"] == f"fab-test pbir contract lint {tmp_path / REPORT}"


def _lint_all(tmp_path: Path, capsys, *flags: str):
    code = contract_main(["lint", "--artifact-dir", str(tmp_path), "--as-of", "2026-11-14", *flags])
    out, err = capsys.readouterr()
    return code, out, err


@pytest.mark.pbir
def test_given_no_target_should_lint_every_contract_under_artifact_dir_as_the_run_checks_every_report(
        tmp_path, capsys):
    contract = _bed(tmp_path)
    code, out, err = _lint_all(tmp_path, capsys, "-q")

    assert (code, out, err) == (0, f"contract lint passed problems=0 {contract}\n", "")


@pytest.mark.pbir
def test_given_no_target_and_one_bad_contract_should_fail_and_name_the_run_without_a_report(tmp_path, capsys):
    _bed(tmp_path)
    (tmp_path / "orphan.odcs.yaml").write_text(_broken("value: b3cba6e7-ddfc-4bcd-b4b1-5f2a3d5297fc",
                                                       "value: 00000000-0000-0000-0000-000000000000"),
                                               encoding="utf-8")
    code, out, _err = _lint_all(tmp_path, capsys, "--format", "json")
    result = json.loads(out)

    assert code == 1 and result["ok"] is False and result["next"] is None
    orphan = next(c for c in result["contracts"] if c["contract"].endswith("orphan.odcs.yaml"))
    assert "pairs with no report under" in orphan["problems"][0]["message"]


@pytest.mark.pbir
def test_given_no_target_and_no_contracts_should_exit_2_naming_init(tmp_path, capsys):
    _bed(tmp_path).unlink()
    code, out, err = _lint_all(tmp_path, capsys)

    assert (code, out) == (2, "") and "fab-test pbir contract init" in err


@pytest.mark.pbir
def test_given_no_target_and_all_clean_should_name_the_whole_run_next(tmp_path, capsys):
    _bed(tmp_path)
    code, out, _err = _lint_all(tmp_path, capsys, "--format", "json")

    assert code == 0 and json.loads(out)["next"] == f"fab-test pbir --artifact-dir {tmp_path}"


# --- AIDD review fixes (2026-11-19) ---------------------------------------------------------------------------


@pytest.mark.pbir
@pytest.mark.parametrize("verb", ["init", "lint"])
@pytest.mark.parametrize("flags", [["--telemetry"], ["--no-telemetry"], ["--timeout", "30"], ["--jobs", "2"]])
def test_given_a_flag_of_the_run_should_refuse_naming_the_run_never_unrecognized(tmp_path, capsys, verb, flags):
    _bed(tmp_path)
    code = contract_main([verb, "SampleModel-DefaultState", "--artifact-dir", str(tmp_path), *flags])
    out, err = capsys.readouterr()

    assert (code, out) == (2, "") and "unrecognized" not in err
    assert f"{flags[0]}: contract {verb} doesn't take it; it's a flag of the run: fab-test pbir " in err


@pytest.mark.pbir
def test_given_dry_run_on_lint_should_refuse_saying_lint_writes_nothing(tmp_path, capsys):
    _bed(tmp_path)
    code, out, err = _lint(tmp_path, capsys, "--dry-run")

    assert (code, out) == (2, "") and "contract lint doesn't take it" in err


@pytest.mark.pbir
def test_given_a_typo_should_still_be_an_argparse_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        contract_main(["lint", "SampleModel-DefaultState", "--frobnicate"])

    assert caught.value.code == 2 and "--frobnicate" in capsys.readouterr().err


@pytest.mark.pbir
def test_given_a_target_path_and_artifact_dir_should_carry_both_into_the_next_step(tmp_path, capsys):
    _bed(tmp_path)
    report = tmp_path / REPORT
    code = contract_main(["lint", str(report), "--artifact-dir", str(tmp_path), "--format", "json"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["next"] == f"fab-test pbir {report} --artifact-dir {tmp_path}"


@pytest.mark.pbir
def test_given_failing_json_should_keep_next_in_the_document_as_null(tmp_path, capsys):
    _bed(tmp_path, _broken("name: Alignment\n", "name: Alignmentt\n"))
    code, out, _err = _lint(tmp_path, capsys, "--format", "json")

    assert code == 1 and json.loads(out)["next"] is None


@pytest.mark.pbir
def test_given_two_reports_sharing_a_logical_id_should_pair_with_the_one_beside_the_contract(tmp_path, capsys):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    _bed(tmp_path / "x")
    shutil.copytree(ARTIFACTS / REPORT, tmp_path / "y" / REPORT)
    code, out, _err = _lint_all(tmp_path, capsys, "--format", "json")
    (result,) = json.loads(out)["contracts"]

    assert code == 0 and result["report"] == str(tmp_path / "x" / REPORT) and result["model"]


@pytest.mark.pbir
def test_given_two_reports_sharing_a_logical_id_and_neither_beside_should_name_both(tmp_path, capsys):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    _bed(tmp_path / "x").rename(tmp_path / "opening-state.odcs.yaml")
    shutil.copytree(ARTIFACTS / REPORT, tmp_path / "y" / REPORT)
    code, out, _err = _lint_all(tmp_path, capsys, "--format", "json")
    (result,) = json.loads(out)["contracts"]

    assert code == 1 and "2 reports share" in result["problems"][0]["message"]


@pytest.mark.pbir
def test_given_quiet_should_name_the_contract_on_each_problem(tmp_path, capsys):
    contract = _bed(tmp_path, _broken("name: Alignment\n", "name: Alignmentt\n"))
    code, _out, err = _lint(tmp_path, capsys, "-q")

    assert code == 1 and f"{contract}: pql-test: AlignmentDim.Alignmentt" in err


@pytest.mark.pbir
def test_given_ctrl_c_should_exit_130_without_a_traceback(tmp_path, capsys, monkeypatch):
    _bed(tmp_path)

    def interrupted(*_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(_slicer_contract_lint, "_lint", interrupted)
    code, out, err = _lint(tmp_path, capsys)

    assert (code, out) == (130, "") and "interrupted" in err and "Traceback" not in err


@pytest.mark.pbir
def test_given_unreadable_yaml_should_say_where_on_one_line(tmp_path, capsys):
    _bed(tmp_path, "apiVersion: v3.1.0\nschema: [\n")
    _code, out, _err = _lint(tmp_path, capsys, "--format", "json")
    (problem,) = json.loads(out)["contracts"][0]["problems"]

    assert problem["message"].startswith("not valid YAML: line ") and "\n" not in problem["message"]


@pytest.mark.pbir
def test_given_a_path_that_does_not_exist_should_say_so(tmp_path, capsys):
    code, _out, err = _lint_all(tmp_path, capsys, str(tmp_path / "does" / "not" / "exist.Report"))

    assert code == 2 and "no such folder" in err


@pytest.mark.pbir
def test_given_a_name_no_report_has_should_say_none_is_named_so(tmp_path, capsys):
    code, _out, err = _lint_all(tmp_path, capsys, "Nope")

    assert code == 2 and f"no report named Nope.Report under {tmp_path}" in err


@pytest.mark.pbir
def test_given_a_file_the_run_would_not_read_should_not_lint_it(tmp_path, capsys):
    _bed(tmp_path, "apiVersion: v3.1.0\nkind: DataContract\ncustomProperties:\n"
                   "- property: fabTestReport\n  value: b3cba6e7-ddfc-4bcd-b4b1-5f2a3d5297fc\n")
    code, _out, err = _lint_all(tmp_path, capsys)

    assert code == 2 and "no slicer contract under" in err


@pytest.mark.pbir
def test_given_no_contract_should_name_artifact_dir_as_a_way_out(tmp_path, capsys):
    _bed(tmp_path).unlink()
    _code, _out, err = _lint(tmp_path, capsys)

    assert "--artifact-dir" in err and "--contract FILE" in err


@pytest.mark.pbir
@pytest.mark.parametrize("verb", ["init", "lint"])
@pytest.mark.parametrize("flag", ["--artifact", "--artifact-dir", "--format"])
def test_given_a_shared_input_flag_should_read_exactly_as_the_runs_help(verb, flag):
    from fab_test.scripts._slicer_contract_init import _parser
    from fab_test.scripts.fab_test_parser import build_parser

    def action(parser, option):
        return next(a for a in parser._actions if option in a.option_strings)

    def subparser(parser, name):
        return next(a for a in parser._actions if a.dest in ("action", "analyzer")).choices[name]

    mine, run = action(subparser(_parser(), verb), flag), action(subparser(build_parser(), "pbir"), flag)
    assert (mine.help, mine.metavar, tuple(mine.choices or ())) == (run.help, run.metavar, tuple(run.choices or ()))


@pytest.mark.pbir
def test_given_lint_as_of_should_read_as_the_runs(tmp_path):
    from fab_test.scripts._slicer_contract_init import _parser
    from fab_test.scripts.fab_test_parser import build_parser

    def as_of(parser, name):
        sub = next(a for a in parser._actions if a.dest in ("action", "analyzer")).choices[name]
        return next(a for a in sub._actions if "--as-of" in a.option_strings).help

    assert as_of(_parser(), "lint") == as_of(build_parser(), "pbir")
