"""Authored test files live in fab-tests/, outside the Git-connected folder (Data Agent decision 22).

The user couldn't find two suites among dozens of Fabric item folders. Fabric's Commit to Git
deletes files inside an item folder, and a Git subfolder becomes a workspace folder, so test files
get one findable home beside, not inside, the connected folder. Pairing stays by logicalId.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from fab_test.scripts import _tests_dir as homes

pytestmark = pytest.mark.fab_test

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")


def _repository(tmp_path):
    (tmp_path / ".git").mkdir()
    artifacts = tmp_path / "fabric-artifacts"
    artifacts.mkdir()
    return artifacts


def _args(artifacts, **overrides):
    return argparse.Namespace(**{"artifact_dir": str(artifacts), "tests_dir": None, "file_config": {}, **overrides})


# -- the rule ------------------------------------------------------------------------


def test_fab_tests_sits_at_the_root_of_the_repository_holding_the_artifacts(tmp_path, monkeypatch):
    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    artifacts = _repository(tmp_path)
    nested = artifacts / "workspace" / "sub"
    nested.mkdir(parents=True)
    assert homes.tests_dir(_args(artifacts)) == tmp_path / "fab-tests"
    assert homes.tests_dir(_args(nested)) == tmp_path / "fab-tests"
    assert homes.flow_dir(_args(artifacts), "data-agent") == tmp_path / "fab-tests" / "data-agent"


def test_outside_a_repository_there_is_no_fab_tests(tmp_path, monkeypatch):
    """A scratch copy must never read the real repository's test files, which claim the same items."""
    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    assert homes.tests_dir(_args(tmp_path)) is None
    assert homes.search_roots(_args(tmp_path)) == [tmp_path.resolve()]


def test_outside_a_repository_a_fab_tests_folder_beside_the_artifacts_is_read(tmp_path, monkeypatch):
    """A build artifact, `git archive` export or Docker context has no `.git` (Review 2 blocking 2).

    Without this the run skipped every item and exited 0, having tested nothing.
    """
    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    artifacts = tmp_path / "fabric-artifacts"
    (tmp_path / "fab-tests").mkdir()
    artifacts.mkdir()
    assert homes.tests_dir(_args(artifacts)) == tmp_path / "fab-tests"
    assert homes.search_roots(_args(artifacts)) == [artifacts.resolve(), (tmp_path / "fab-tests").resolve()]


def test_the_data_agent_run_pairs_a_suite_in_fab_tests_without_a_repository(tmp_path, monkeypatch):
    from fab_test.scripts._data_agent_run import paired_suites

    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    artifacts = tmp_path / "fabric-artifacts"
    artifacts.mkdir()
    _agent(artifacts)
    suite = tmp_path / "fab-tests" / "data-agent" / "Sales.DataAgent.promptfoo.yaml"
    suite.parent.mkdir(parents=True)
    suite.write_text(yaml.safe_dump({"fabTestDataAgent": _logical_id(artifacts), "tests": []}), encoding="utf-8")
    paired = paired_suites(_args(artifacts, output_dir=str(tmp_path / "results")))
    assert list(paired.values()) == [suite.resolve()]


@pytest.mark.parametrize("source", ["flag", "env", "config"])
def test_the_folder_is_configurable_relative_to_the_repository(tmp_path, monkeypatch, source):
    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    artifacts = _repository(tmp_path)
    overrides = {"flag": {"tests_dir": "qa/tests"}, "config": {"file_config": {"tests_dir": "qa/tests"}}}
    if source == "env":
        monkeypatch.setenv("FAB_TEST_TESTS_DIR", "qa/tests")
    assert homes.tests_dir(_args(artifacts, **overrides.get(source, {}))) == tmp_path / "qa" / "tests"


def test_search_reads_fab_tests_once_and_only_when_it_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    artifacts = _repository(tmp_path)
    assert homes.search_roots(_args(artifacts)) == [artifacts.resolve()]
    (tmp_path / "fab-tests").mkdir()
    assert homes.search_roots(_args(artifacts)) == [artifacts.resolve(), (tmp_path / "fab-tests").resolve()]
    assert homes.search_roots(_args(tmp_path)) == [tmp_path.resolve()]  # already inside --artifact-dir


# -- Data Agent ----------------------------------------------------------------------


def _run(cwd, *argv):
    tool = cwd / "promptfoo.js"
    tool.write_text("console.log('Configuration is valid');\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if key != "FAB_TEST_TESTS_DIR"}
    env.update(CI="true", PROMPTFOO_PATH=str(tool), PATH=str(CLI.parent) + os.pathsep + os.environ["PATH"])
    return subprocess.run([str(CLI), *argv], cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, check=False)


def _agent(artifacts):
    shutil.copytree(ROOT / "fabric-artifacts" / "agent-sample-model.DataAgent",
                    artifacts / "agent-sample-model.DataAgent")
    answers = artifacts.parent / "answers.json"
    answers.write_text(json.dumps({"tests": [{"query": "How many characters?", "expect": "16,376"}]}),
                       encoding="utf-8")
    return answers


def _logical_id(artifacts):
    platform = artifacts / "agent-sample-model.DataAgent" / ".platform"
    return json.loads(platform.read_text(encoding="utf-8"))["config"]["logicalId"]


def test_data_agent_init_writes_to_fab_tests_and_lint_finds_it_there(tmp_path):
    artifacts = _repository(tmp_path)
    answers = _agent(artifacts)
    init = _run(tmp_path, "data-agent", "tests", "init", "agent-sample-model", "--artifact-dir", str(artifacts),
                "--answers", str(answers), "-q")
    assert init.returncode == 0, init.stderr
    suite = tmp_path / "fab-tests" / "data-agent" / "agent-sample-model.DataAgent.promptfoo.yaml"
    assert str(suite) in init.stdout
    assert yaml.safe_load(suite.read_text(encoding="utf-8"))["fabTestDataAgent"]
    assert not list(artifacts.glob("*.promptfoo.yaml"))  # nothing beside the item, in the connected folder
    lint = _run(tmp_path, "data-agent", "tests", "lint", "agent-sample-model", "--artifact-dir", str(artifacts),
                "--format", "json")
    assert lint.returncode == 0, lint.stderr
    assert [Path(row["suite"]) for row in json.loads(lint.stdout)["suites"]] == [suite]


def test_the_data_agent_run_pairs_a_suite_in_fab_tests(tmp_path, monkeypatch):
    from fab_test.scripts._data_agent_run import paired_suites

    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    artifacts = _repository(tmp_path)
    _agent(artifacts)
    suite = tmp_path / "fab-tests" / "data-agent" / "renamed.DataAgent.promptfoo.yaml"
    suite.parent.mkdir(parents=True)
    suite.write_text(yaml.safe_dump({"fabTestDataAgent": _logical_id(artifacts), "tests": []}), encoding="utf-8")
    paired = paired_suites(_args(artifacts, output_dir=str(tmp_path / "results")))
    assert list(paired.values()) == [suite.resolve()]


def test_a_suite_already_beside_its_item_is_extended_in_place(tmp_path):
    artifacts = _repository(tmp_path)
    answers = _agent(artifacts)
    beside = artifacts / "agent-sample-model.DataAgent.promptfoo.yaml"
    beside.write_text(yaml.safe_dump({"fabTestDataAgent": _logical_id(artifacts), "prompts": ["{{query}}"],
                                      "tests": []}), encoding="utf-8")
    init = _run(tmp_path, "data-agent", "tests", "init", "agent-sample-model", "--artifact-dir", str(artifacts),
                "--answers", str(answers), "-q")
    assert init.returncode == 0, init.stderr
    assert len(yaml.safe_load(beside.read_text(encoding="utf-8"))["tests"]) == 1
    assert not (tmp_path / "fab-tests").exists()


# -- pbir slicer contracts -------------------------------------------------------------


def _report(artifacts):
    report = artifacts / "SampleModel-DefaultState.Report"
    shutil.copytree(ROOT / "fabric-artifacts" / report.name, report)
    return report


def test_contract_init_writes_to_fab_tests_and_the_run_reads_it_there(tmp_path, monkeypatch):
    from fab_test.scripts._slicer_contract_run import _contract_files

    artifacts = _repository(tmp_path)
    _report(artifacts)
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"calendar.fiscal_year_start_month": 7, "calendar.fiscal_year_named_by": "end"}),
                       encoding="utf-8")  # the rest take their suggestion
    init = _run(tmp_path, "pbir", "contract", "init", "SampleModel-DefaultState", "--artifact-dir", str(artifacts),
                "--answers", str(answers), "--as-of", "2026-11-21", "-q")
    assert init.returncode == 0, init.stderr
    contract = tmp_path / "fab-tests" / "pbir" / "SampleModel-DefaultState.Report.odcs.yaml"
    assert contract.is_file(), init.stdout
    assert not list(artifacts.glob("*.odcs.yaml"))
    monkeypatch.delenv("FAB_TEST_TESTS_DIR", raising=False)
    assert _contract_files(_args(artifacts)) == [contract.resolve()]
