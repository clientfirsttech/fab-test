"""Authoring nouns coexist with analyzer targets in the actual argparse tree."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts.fab_test_parser import build_parser

pytestmark = pytest.mark.pbir


def test_contract_verbs_are_discoverable_and_parse_after_global_options():
    parser = build_parser()
    analyzers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    pbir = analyzers.choices["pbir"]
    nouns = next(a for a in pbir._actions if isinstance(a, argparse._SubParsersAction))
    assert "contract" in nouns.choices
    args = parser.parse_args(["--config", "config.yml", "pbir", "contract", "init", "Sales", "--questions"])
    assert (args.authoring_noun, args.action, args.target) == ("contract", "init", "Sales")
    assert args.questions


@pytest.mark.parametrize("argv,target", [
    (["pbir"], None),
    (["pbir", "Sales", "--artifact-dir", "artifacts"], "Sales"),
    (["pbir", "--artifact-dir", "artifacts", "Sales"], "Sales"),
    (["pbir", "./contract", "--dry-run"], "./contract"),
    (["pbir", "--artifact", "Sales"], None),
])
def test_run_targets_and_flags_still_parse(argv, target):
    args = build_parser().parse_args(argv)
    assert args.target == target
    assert getattr(args, "authoring_noun", None) is None


def _near_miss(argv, monkeypatch, tmp_path):
    from fab_test.scripts._authoring_parser import near_miss

    monkeypatch.setenv("FAB_TEST_ENABLE_DATA_AGENT", "1")
    monkeypatch.chdir(tmp_path)
    args, _unknown = build_parser().parse_known_args(argv)
    return near_miss(args, argv)


@pytest.mark.parametrize("argv,meant", [
    (["pbir", "lint"], "pbir contract lint"),
    (["pbir", "init", "Sales"], "pbir contract init Sales"),
    (["pbir", "contracts", "init"], "pbir contract init"),
    (["pbir", "lint", "Sales", "--format", "json"], "pbir contract lint Sales --format json"),
    (["data-agent", "init", "Sales"], "data-agent tests init Sales"),
    (["agent", "lint", "--artifact-dir", "a b"], 'agent tests lint --artifact-dir "a b"'),
    (["data-agent", "test", "lint"], "data-agent tests lint"),
], ids=["pbir-lint", "pbir-init", "plural", "flags", "agent-init", "alias-spaces", "singular"])
def test_a_near_miss_names_the_exact_command_meant(argv, meant, monkeypatch, tmp_path):
    """Decision 15: a verb out of place or a misspelt noun exits 2 naming the command, never runs it."""
    assert _near_miss(argv, monkeypatch, tmp_path) == f"did you mean: fab-test {meant}"


@pytest.mark.parametrize("argv", [
    ["pbir"], ["pbir", "Sales"], ["pbir", "contract", "lint"], ["data-agent", "tests", "init", "Sales"],
    ["pql-test", "lint"],  # an analyzer with no authoring noun keeps its own grammar
])
def test_ordinary_commands_are_not_near_misses(argv, monkeypatch, tmp_path):
    assert _near_miss(argv, monkeypatch, tmp_path) is None


@pytest.mark.parametrize("argv,item", [
    (["pbir", "lint"], "lint.Report"),
    (["data-agent", "init"], "init.DataAgent"),
    (["pbir", "contracts"], "contracts.Report"),
])
def test_an_item_really_named_like_a_verb_is_a_target(argv, item, monkeypatch, tmp_path):
    (tmp_path / item).mkdir()
    assert _near_miss(argv, monkeypatch, tmp_path) is None


@pytest.mark.parametrize("argv,folder,meant", [
    (["pbir", "lint"], "lint", "pbir contract lint"),
    (["data-agent", "test", "lint"], "test", "data-agent tests lint"),
])
def test_a_plain_folder_named_like_a_verb_is_not_an_item(argv, folder, meant, monkeypatch, tmp_path):
    """Review 2: any `lint` folder in the working directory brought back `pbir lint` passing on nothing."""
    (tmp_path / folder).mkdir()
    assert _near_miss(argv, monkeypatch, tmp_path) == f"did you mean: fab-test {meant}"


def test_an_item_folder_typed_by_its_own_name_is_a_target(monkeypatch, tmp_path):
    (tmp_path / "lint").mkdir()
    (tmp_path / "lint" / ".platform").write_text("{}", encoding="utf-8")
    assert _near_miss(["pbir", "lint"], monkeypatch, tmp_path) is None


def test_installed_console_refuses_pbir_lint_instead_of_passing_on_nothing(tmp_path):
    cli = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")
    result = subprocess.run([str(cli), "pbir", "lint"], cwd=tmp_path, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60, check=False)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "did you mean: fab-test pbir contract lint" in result.stderr
    assert result.stdout == ""


def test_installed_console_dispatches_contract_after_global_config(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / "SampleModel-DefaultState.Report"
    shutil.copytree(root / "fabric-artifacts" / report.name, report)
    config = tmp_path / "fab-test.yml"
    config.write_text("{}\n", encoding="utf-8")
    cli = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")
    result = subprocess.run(
        [str(cli), "--config", str(config), "pbir", "contract", "init", str(report), "--questions", "--format", "json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["questions"]


def test_contract_authoring_honors_explicit_config_and_reports_missing_config(tmp_path):
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / "SampleModel-DefaultState.Report"
    shutil.copytree(root / "fabric-artifacts" / report.name, report)
    config = tmp_path / "settings.yml"
    config.write_text(f"artifact_dir: '{tmp_path.as_posix()}'\nformat: json\n", encoding="utf-8")
    cli = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")
    command = [str(cli), "--config", str(config), "pbir", "contract", "init", report.name, "--questions"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["questions"]
    command[2] = str(tmp_path / "missing.yml")
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 2
    assert "missing.yml" in result.stderr


# -- discoverability (Review 2 should-fix 10, Review 1 items 6-7) ---------------------------


def _console(*argv, env_extra=None, cwd=None):
    import os

    cli = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")
    env = {**os.environ, "FAB_TEST_ENABLE_DATA_AGENT": "1", **(env_extra or {})}
    return subprocess.run([str(cli), *argv], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, cwd=cwd, timeout=120, check=False)


@pytest.mark.parametrize("argv,usage", [
    (["data-agent", "tests", "--help"], "usage: fab-test data-agent tests "),
    (["pbir", "contract", "--help"], "usage: fab-test pbir contract "),
])
def test_the_noun_usage_shows_only_what_parses(argv, usage):
    """`data-agent [TARGET] tests` gave "unrecognized arguments": the noun is the first word."""
    result = _console(*argv)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(usage) and "[TARGET]" not in result.stdout.splitlines()[0]


def test_help_names_the_authoring_verbs():
    result = _console("help")
    flat = " ".join(result.stdout.split())
    assert "data-agent tests init|lint" in flat and "pbir contract init|lint" in flat


def test_list_names_each_analyzers_authoring_verbs(tmp_path):
    result = _console("list", "--format", "json", "--artifact-dir", str(tmp_path))
    rows = {row["analyzer"]: row for row in json.loads(result.stdout)["analyzers"]}
    assert rows["data-agent"]["authoring"] == ["fab-test data-agent tests init", "fab-test data-agent tests lint"]
    assert rows["pbir"]["authoring"] == ["fab-test pbir contract init", "fab-test pbir contract lint"]
    assert rows["bpa"]["authoring"] == []


def test_explain_names_the_verbs_and_no_empty_tool_flag(tmp_path):
    result = _console("explain", "data-agent", "--workspace", "00000000-0000-0000-0000-000000000000",
                      "--artifact-dir", str(tmp_path), "--format", "json",
                      env_extra={"PROMPTFOO_PATH": ""})
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["authoring"] == ["fab-test data-agent tests init", "fab-test data-agent tests lint"]
    command = payload["command"]
    assert "" not in command


def test_tests_help_reads_the_same_on_every_verb_and_the_run():
    parser = build_parser()
    analyzers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    run = analyzers.choices["data-agent"]
    noun = next(a for a in run._actions if isinstance(a, argparse._SubParsersAction)).choices["tests"]
    verbs = next(a for a in noun._actions if isinstance(a, argparse._SubParsersAction)).choices
    helps = {name: next(a.help for a in p._actions if "--tests" in a.option_strings)
             for name, p in {"run": run, **verbs}.items()}
    assert len(set(helps.values())) == 1, helps
    answers = next(a.help for a in verbs["init"]._actions if "--answers" in a.option_strings)
    assert "by question id" not in answers and "tests" in answers
