"""Offline checks for a Data Agent suite before promptfoo validates it."""

import json

import pytest
import yaml

from fab_test.scripts._data_agent_authoring_lint import suite_problems, validate_promptfoo

pytestmark = pytest.mark.data_agent


@pytest.fixture
def paired(tmp_path):
    item = tmp_path / "Sales.DataAgent"
    item.mkdir()
    (item / ".platform").write_text(json.dumps({
        "config": {"logicalId": "stable-id"}, "metadata": {"displayName": "Sales"},
    }), encoding="utf-8")
    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    return item, suite


def _write(path, document):
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def test_valid_suite_has_no_local_findings(paired):
    item, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "tests": [
        {"metadata": {"id": "count"}, "vars": {"query": "How many?"}},
    ]})
    assert suite_problems(item, suite) == []


def test_invalid_or_mismatched_suite_is_reported(paired):
    item, suite = paired
    suite.write_text("tests: [", encoding="utf-8")
    assert "Cannot read" in suite_problems(item, suite)[0]
    _write(suite, {"fabTestDataAgent": "another-id", "tests": []})
    assert any("logicalId" in problem for problem in suite_problems(item, suite))


def test_invalid_yaml_does_not_echo_credential_contents(paired):
    item, suite = paired
    suite.write_text('client_secret: "private-value\n', encoding="utf-8")
    problems = suite_problems(item, suite)
    assert problems
    assert "private-value" not in str(problems)


def test_missing_and_duplicate_test_ids_are_reported(paired):
    item, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "tests": [
        {"metadata": {"id": "same"}}, {"metadata": {"id": "same"}}, {},
    ]})
    problems = suite_problems(item, suite)
    assert any("duplicate" in problem.lower() and "same" in problem for problem in problems)
    assert any("metadata.id" in problem for problem in problems)


def test_credentials_and_hand_built_urls_are_reported_without_echoing_secrets(paired):
    item, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "providers": [{"config": {
        "base_url": "https://example.invalid/agent", "client_secret": "private-value",
    }}], "tests": [{"metadata": {"id": "one"}}]})
    problems = suite_problems(item, suite)
    assert any("base_url" in problem for problem in problems)
    assert any("client_secret" in problem for problem in problems)
    assert "private-value" not in str(problems)


def test_upstream_validator_never_receives_a_suite_with_credentials(paired, tmp_path):
    _, suite = paired
    _write(suite, {"providers": [{"config": {"client_secret": "private-value"}}], "tests": []})
    problems = validate_promptfoo(suite, tmp_path / "not-installed")
    assert any("client_secret" in problem for problem in problems)
    assert "private-value" not in str(problems)


@pytest.mark.integration
def test_real_promptfoo_validates_the_same_effective_config(paired):
    from pathlib import Path

    from fab_test.scripts._analyzer_tool_bootstrap import probe_executable
    from fab_test.scripts.fab_test_registry import ANALYZERS_JSON, REPO_ROOT

    tool = probe_executable("data_agent", ANALYZERS_JSON, REPO_ROOT)
    if not tool.get("resolved_path"):
        pytest.skip("Pinned promptfoo is required")
    _, suite = paired
    document = {
        "fabTestDataAgent": "stable-id", "prompts": ["{{query}}"],
        "tests": [{"metadata": {"id": "count"}, "vars": {"query": "How many?"},
                   "assert": [{"type": "contains", "value": "100"}]}],
    }
    _write(suite, document)
    before = suite.read_bytes()
    assert validate_promptfoo(suite, Path(tool["resolved_path"])) == []
    assert suite.read_bytes() == before
    document["prompts"] = 123
    _write(suite, document)
    assert validate_promptfoo(suite, Path(tool["resolved_path"]))
