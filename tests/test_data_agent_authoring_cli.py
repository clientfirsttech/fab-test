"""Data Agent authoring commands through the installed console script."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.data_agent


@pytest.fixture
def authoring(tmp_path):
    item = tmp_path / "Sales.DataAgent"
    item.mkdir()
    (item / ".platform").write_text(json.dumps({
        "config": {"logicalId": "stable-id"}, "metadata": {"displayName": "Sales"},
    }), encoding="utf-8")
    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    suite.write_text(yaml.safe_dump({
        "fabTestDataAgent": "stable-id", "prompts": ["{{query}}"],
        "tests": [{"metadata": {"id": "count"}, "vars": {"query": "How many?"},
                   "assert": [{"type": "contains", "value": "42"}]}],
    }), encoding="utf-8")
    tool = tmp_path / "promptfoo.js"
    tool.write_text("console.log('Configuration is valid');\n", encoding="utf-8")
    return item, suite, tool


def _run(tmp_path, tool, *args):
    env = {**os.environ, "FAB_TEST_ENABLE_DATA_AGENT": "1", "PROMPTFOO_PATH": str(tool),
           "CI": "true", "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    cli = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")
    return subprocess.run(
        [str(cli), "data-agent", "tests", *args, "--artifact-dir", str(tmp_path)],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False,
    )


def test_lint_uses_pairing_and_produces_one_json_document(authoring, tmp_path):
    item, suite, tool = authoring
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    result = _run(tmp_path, tool, "lint", item.name, "--format", "json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["ok"]
    assert len(data["suites"]) == 1
    assert Path(data["suites"][0]["suite"]) == suite
    assert "data-agent" in data["next"]
    assert {p.relative_to(tmp_path) for p in tmp_path.rglob("*")} == before


def test_lint_finds_all_suites_without_target(authoring, tmp_path):
    _item, _suite, tool = authoring
    result = _run(tmp_path, tool, "lint", "--format", "json")
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["suites"]) == 1


def test_lint_reports_bad_yaml_as_a_finding(authoring, tmp_path):
    item, suite, tool = authoring
    suite.write_text("tests: [", encoding="utf-8")
    result = _run(tmp_path, tool, "lint", item.name, "--format", "json")
    assert result.returncode == 1, result.stderr
    data = json.loads(result.stdout)
    assert not data["ok"] and data["next"] is None
    assert data["suites"][0]["problems"]


def test_lint_refuses_a_run_only_flag(authoring, tmp_path):
    item, _suite, tool = authoring
    result = _run(tmp_path, tool, "lint", item.name, "--report")
    assert result.returncode == 2
    assert "--report" in result.stderr and "fab-test data-agent" in result.stderr


def _definition(item):
    draft = item / "Files" / "Config" / "draft"
    source = draft / "model"
    source.mkdir(parents=True)
    (draft / "stage_config.json").write_text(json.dumps({"aiInstructions": "Use the sales model."}), encoding="utf-8")
    (source / "datasource.json").write_text(json.dumps({
        "artifactId": "source-1", "displayName": "Sales Model", "elements": [
            {"id": "table-1", "type": "semantic_model.table", "display_name": "Orders", "is_selected": True},
            {"id": "table-2", "type": "semantic_model.table", "display_name": "Hidden", "is_selected": False},
        ],
    }), encoding="utf-8")


_CHAIN = {"tests": [
    {"query": "How many orders are there?", "expect": "1,204", "match": "n",
     "follow_ups": [{"query": "Is that more than 1,000?", "expect": "yes", "match": "s"}]},
    {"query": "What is my bank balance?", "match": "r"},
]}


def _answers(tmp_path, document=_CHAIN):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_init_needs_your_questions_and_writes_them_with_follow_ups(authoring, tmp_path):
    item, suite, tool = authoring
    suite.unlink()
    _definition(item)
    unattended = _run(tmp_path, tool, "init", item.name)  # CI: nobody to ask
    assert unattended.returncode == 2
    assert "--questions" in unattended.stderr and "--answers" in unattended.stderr
    assert not suite.exists()
    questions = _run(tmp_path, tool, "init", item.name, "--questions", "--format", "json")
    assert questions.returncode == 0, questions.stderr
    payload = json.loads(questions.stdout)
    assert "How many rows are in the Orders table?" in payload["suggestions"]
    assert payload["matches"]["n"] == "number" and payload["answers_example"]["tests"]
    assert not suite.exists()
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path)), "--format", "json")
    assert result.returncode == 0, result.stderr
    document = yaml.safe_load(suite.read_text(encoding="utf-8"))
    assert document["fabTestDataAgent"] == "stable-id"
    assert [test["metadata"]["id"] for test in document["tests"]] == [
        "how-many-orders-are-there", "how-many-orders-are-there-follow-up-1", "what-is-my-bank-balance"]
    assert document["tests"][1]["vars"]["conversation"] == "how-many-orders-are-there"
    assert document["tests"][0]["assert"][0]["type"] == "regex"
    assert "tests lint" in json.loads(result.stdout)["next"]


def test_init_dry_run_and_existing_tests_are_safe(authoring, tmp_path):
    item, suite, tool = authoring
    _definition(item)
    original = suite.read_bytes()
    preview = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path)), "--dry-run",
                   "--format", "json")
    assert preview.returncode == 0, preview.stderr
    assert suite.read_bytes() == original
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path)))
    assert result.returncode == 0, result.stderr
    document = yaml.safe_load(suite.read_text(encoding="utf-8"))
    assert next(test for test in document["tests"] if test["metadata"]["id"] == "count")["assert"][0]["value"] == "42"
    assert len(document["tests"]) == 4


@pytest.mark.parametrize(("document", "message"), [
    ({"count": "42"}, "tests"),
    ({"tests": [{"query": "Q?", "expect": "x", "match": "q"}]}, "n number"),
], ids=["old-shape", "bad-key"])
def test_init_names_what_to_fix_in_an_answers_file(authoring, tmp_path, document, message):
    item, suite, tool = authoring
    _definition(item)
    original = suite.read_bytes()
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path, document)))
    assert result.returncode == 2
    assert message in result.stderr
    assert suite.read_bytes() == original


def test_init_with_no_questions_writes_no_file(authoring, tmp_path):
    item, suite, tool = authoring
    suite.unlink()
    _definition(item)
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path, {"tests": []})), "-q")
    assert result.returncode == 0, result.stderr
    assert not suite.exists()


def _init_json(tmp_path, tool, item, tests):
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path, {"tests": tests})),
                  "--format", "json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_new_question_never_takes_an_id_the_suite_already_has(authoring, tmp_path):
    """Review 2 blocking 1: a slug clash read as "the same test", so the new question was dropped."""
    item, suite, tool = authoring
    _definition(item)
    clash = _init_json(tmp_path, tool, item, [{"query": "Count?", "expect": "7"}])  # slug "count" is taken
    assert clash["added"] == ["count-2"] and clash["kept"] == []
    stem = "How many rows are in the MarvelFact table for the year"
    first = _init_json(tmp_path, tool, item, [{"query": f"{stem} 2020?", "expect": "100",
                                               "follow_ups": [{"query": "And 2019?", "expect": "90"}]}])
    second = _init_json(tmp_path, tool, item, [{"query": f"{stem} 2021?", "expect": "120"}])
    assert len(first["added"]) == 2 and len(second["added"]) == 1 and second["kept"] == []
    queries = [test["vars"]["query"] for test in yaml.safe_load(suite.read_text(encoding="utf-8"))["tests"]]
    assert f"{stem} 2020?" in queries and f"{stem} 2021?" in queries and "Count?" in queries


def test_the_same_question_typed_again_still_meets_its_test(authoring, tmp_path):
    item, _suite, tool = authoring
    _definition(item)
    again = _init_json(tmp_path, tool, item, [{"query": "how many", "expect": "43"}])
    assert again["kept"] == ["count"] and again["added"] == []


def test_init_extends_its_own_output_when_a_question_holds_a_hash(authoring, tmp_path):
    """Review 2 should-fix 3: `#` inside a quoted value is not a comment."""
    item, suite, tool = authoring
    _definition(item)
    _init_json(tmp_path, tool, item, [{"query": "What is the #1 eye color?", "expect": "Blue"}])
    added = _init_json(tmp_path, tool, item, [{"query": "Top hair color?", "expect": "Black"}])
    assert added["added"] == ["top-hair-color"]
    suite.write_text(suite.read_text(encoding="utf-8") + "# a note a person wrote\n", encoding="utf-8")
    refused = _run(tmp_path, tool, "init", item.name, "--answers",
                   str(_answers(tmp_path, {"tests": [{"query": "Q?", "expect": "x"}]})))
    assert refused.returncode == 2 and "comments" in refused.stderr


def test_init_refuses_malformed_existing_metadata_without_modifying_it(authoring, tmp_path):
    item, suite, tool = authoring
    _definition(item)
    suite.write_text("fabTestDataAgent: stable-id\ntests:\n- metadata: invalid\n", encoding="utf-8")
    original = suite.read_bytes()
    result = _run(tmp_path, tool, "init", item.name, "--questions")
    assert result.returncode == 2
    assert "metadata" in result.stderr
    assert suite.read_bytes() == original


def test_text_dry_run_shows_the_generated_suite(authoring, tmp_path):
    item, suite, tool = authoring
    suite.unlink()
    _definition(item)
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path)), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "fabTestDataAgent:" in result.stdout and "how-many-orders-are-there-follow-up-1" in result.stdout
    assert not suite.exists()


def test_init_extends_renamed_suite_by_identity_instead_of_creating_a_duplicate(authoring, tmp_path):
    item, suite, tool = authoring
    _definition(item)
    renamed = suite.with_name("OldName.DataAgent.promptfoo.yaml")
    suite.rename(renamed)
    questions = _run(tmp_path, tool, "init", item.name, "--questions", "--format", "json")
    assert questions.returncode == 0, questions.stderr
    assert Path(json.loads(questions.stdout)["suite"]) == renamed
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert not suite.exists()
    assert len(yaml.safe_load(renamed.read_text(encoding="utf-8"))["tests"]) == 4


def test_lint_all_rejects_duplicate_suite_claims(authoring, tmp_path):
    _item, suite, tool = authoring
    duplicate = tmp_path / "Duplicate.DataAgent.promptfoo.yaml"
    duplicate.write_bytes(suite.read_bytes())
    result = _run(tmp_path, tool, "lint", "--format", "json")
    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert not payload["ok"]
    assert any("duplicate" in str(row["problems"]).lower() for row in payload["suites"])


def test_lint_reports_invalid_effective_config_as_a_finding(authoring, tmp_path):
    item, suite, tool = authoring
    document = yaml.safe_load(suite.read_text(encoding="utf-8"))
    document["providers"] = [None]
    suite.write_text(yaml.safe_dump(document), encoding="utf-8")
    result = _run(tmp_path, tool, "lint", item.name, "--format", "json")
    assert result.returncode == 1, result.stderr
    assert not json.loads(result.stdout)["ok"]


def test_data_agent_authoring_honors_explicit_config(authoring, tmp_path):
    item, _suite, tool = authoring
    config = tmp_path / "settings.yml"
    config.write_text(f"artifact_dir: '{tmp_path.as_posix()}'\nformat: json\n", encoding="utf-8")
    env = {**os.environ, "FAB_TEST_ENABLE_DATA_AGENT": "1", "PROMPTFOO_PATH": str(tool)}
    cli = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")
    command = [str(cli), "--config", str(config), "data-agent", "tests", "lint", item.name]
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8",
                            timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"]
    command[2] = str(tmp_path / "missing.yml")
    result = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8",
                            timeout=60, check=False)
    assert result.returncode == 2
    assert "missing.yml" in result.stderr


def test_text_questions_show_suggestions_keys_and_the_file_shape(authoring, tmp_path):
    item, _suite, tool = authoring
    _definition(item)
    result = _run(tmp_path, tool, "init", item.name, "--questions")
    assert result.returncode == 0, result.stderr
    assert "1. How many rows are in the Orders table?" in result.stdout
    assert "you write the expected answers" in result.stdout
    assert "n number" in result.stdout and '"follow_ups"' in result.stdout


def test_init_requires_force_to_replace_existing_tests(authoring, tmp_path):
    item, suite, tool = authoring
    _definition(item)
    first = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path)))
    assert first.returncode == 0, first.stderr
    changed = {"tests": [{**_CHAIN["tests"][0], "expect": "1,300", "follow_ups": []}]}
    kept = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path, changed)), "--format", "json")
    assert kept.returncode == 0, kept.stderr
    assert json.loads(kept.stdout)["kept"] == ["how-many-orders-are-there"]
    forced = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path, changed)), "--force",
                  "--format", "json")
    assert forced.returncode == 0, forced.stderr
    assert json.loads(forced.stdout)["replaced"] == ["how-many-orders-are-there"]
    tests = yaml.safe_load(suite.read_text(encoding="utf-8"))["tests"]
    first_test = next(test for test in tests if test["metadata"]["id"] == "how-many-orders-are-there")
    assert "1,?300" in first_test["assert"][0]["value"]


def test_init_does_not_echo_secrets_from_a_malformed_existing_suite(authoring, tmp_path):
    item, suite, tool = authoring
    _definition(item)
    suite.write_text('client_secret: "private-value\n', encoding="utf-8")
    result = _run(tmp_path, tool, "init", item.name, "--questions")
    assert result.returncode == 2
    assert "private-value" not in result.stderr + result.stdout
    assert str(suite) in result.stderr


def test_a_dry_run_never_says_written(authoring, tmp_path):
    item, suite, tool = authoring
    _definition(item)
    original = suite.read_bytes()
    result = _run(tmp_path, tool, "init", item.name, "--answers", str(_answers(tmp_path)), "--dry-run")
    assert result.returncode == 0, result.stderr
    first = result.stdout.splitlines()[0]
    assert first.startswith("tests dry run, nothing written: would add=3 replace=0 keep=0 unchanged=0 ")
    assert "tests written" not in result.stdout
    assert suite.read_bytes() == original
