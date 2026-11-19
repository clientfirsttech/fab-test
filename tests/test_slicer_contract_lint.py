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


def _bed(tmp_path: Path, contract: str | None = None) -> Path:
    """The test bed's report, its model and its contract, side by side as Desktop saves them."""
    shutil.copytree(ARTIFACTS / REPORT, tmp_path / REPORT)
    shutil.copytree(ARTIFACTS / MODEL, tmp_path / MODEL)
    text = (ARTIFACTS / CONTRACT).read_text(encoding="utf-8")
    (tmp_path / CONTRACT).write_text(text if contract is None else contract, encoding="utf-8")
    return tmp_path / CONTRACT


def _lint(tmp_path: Path, capsys, *flags: str):
    code = contract_main(["lint", "SampleModel-DefaultState", "--artifact-dir", str(tmp_path),
                          "--as-of", "2026-11-14", *flags])
    out, err = capsys.readouterr()
    return code, out, err


def _broken(old: str, new: str) -> str:
    text = (ARTIFACTS / CONTRACT).read_text(encoding="utf-8")
    assert old in text
    return text.replace(old, new, 1)


@pytest.mark.pbir
def test_given_a_clean_contract_should_pass_and_name_the_run_as_the_next_step(tmp_path, capsys):
    contract = _bed(tmp_path)
    code, out, err = _lint(tmp_path, capsys)

    assert (code, err) == (0, "")
    assert f"✓ {contract}: valid ODCS v3.1.0" in out and f"names resolve in {MODEL}" in out
    assert "Next: fab-test pbir SampleModel-DefaultState" in out


@pytest.mark.pbir
def test_given_quiet_should_print_one_line_shaped_like_the_runs(tmp_path, capsys):
    contract = _bed(tmp_path)

    assert _lint(tmp_path, capsys, "-q") == (0, f"contract lint passed problems=0 {contract}\n", "")


@pytest.mark.pbir
def test_given_format_json_should_print_one_document_with_the_next_step(tmp_path, capsys):
    _bed(tmp_path)
    code, out, _err = _lint(tmp_path, capsys, "--format", "json")
    result = json.loads(out)

    assert code == 0 and result["ok"] is True and result["next"] == "fab-test pbir SampleModel-DefaultState"
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
    assert ("contract lint checks a contract, not a report; see it checked with "
            "fab-test pbir --artifact SampleModel-DefaultState --open-report") in err


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
    assert capsys.readouterr().out.rstrip().endswith("Next: fab-test pbir contract lint SampleModel-DefaultState")
    assert contract_main([*flags, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["next"] == "fab-test pbir contract lint SampleModel-DefaultState"


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

    assert code == 1 and result["ok"] is False and "next" not in result
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

    assert code == 0 and json.loads(out)["next"] == "fab-test pbir"
