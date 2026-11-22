"""Offline checks for a Data Agent suite before promptfoo validates it."""

import json

import pytest
import yaml

from fab_test.scripts._data_agent_authoring_lint import suite_problems, suite_warnings, validate_promptfoo

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


_FABRIC_URL = "https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/a/aiassistant/openai"


@pytest.mark.parametrize("config", [{"base_url": _FABRIC_URL}, {"fabric_urls": {"sales": _FABRIC_URL}}],
                         ids=["base_url", "fabric_urls"])
def test_an_explicit_url_on_a_fabric_host_is_a_warning_not_a_finding(paired, config):
    """Decision 18: the escape hatch still works, so lint warns rather than fails."""
    item, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "providers": [{"config": config}],
                   "tests": [{"metadata": {"id": "one"}}]})
    assert suite_problems(item, suite) == []
    assert any("fab-test resolves the agent" in warning for warning in suite_warnings(suite))


def test_a_url_off_the_fabric_hosts_fails_lint_with_the_runs_message(paired):
    from fab_test.scripts._data_agent_suite import SuiteError, effective_config, load_suite

    item, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "providers": [{"config": {"fabric_urls": {
        "x": "https://evil.example/agent"}}}], "tests": [{"metadata": {"id": "one"}}]})
    problems = suite_problems(item, suite)
    with pytest.raises(SuiteError) as refused:  # the run refuses it before promptfoo starts
        effective_config(load_suite(suite), "https://example.invalid/data-agent")
    assert any(str(refused.value) in problem for problem in problems)
    assert "only to Fabric or Power BI hosts" in str(refused.value)


def test_lint_hands_promptfoo_no_secret(paired, tmp_path, monkeypatch):
    """Decision 19 applies to `promptfoo validate` too."""
    import subprocess

    _, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "tests": [{"metadata": {"id": "one"}}]})
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "private-value")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "private-value")
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "Configuration is valid", "")

    monkeypatch.setattr(subprocess, "run", run)
    tool = tmp_path / "promptfoo.js"
    tool.write_text("", encoding="utf-8")
    assert validate_promptfoo(suite, tool) == []
    assert "private-value" not in seen.values()


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


def _lint(paired, monkeypatch, capsys, resolve, *extra):
    """`tests lint` in process, with how promptfoo is found replaced by ``resolve``."""
    from fab_test.scripts import _data_agent_lint_command as command
    from fab_test.scripts._authoring_output import resolve_inputs
    from fab_test.scripts.fab_test_parser import build_parser

    item, _suite = paired
    monkeypatch.setenv("FAB_TEST_ENABLE_DATA_AGENT", "1")
    monkeypatch.setattr(command, "_promptfoo", resolve)
    args = build_parser().parse_args(["data-agent", "tests", "lint", item.name, "--artifact-dir",
                                      str(item.parent), "--format", "json", *extra])
    resolve_inputs(args)
    code = command.lint_main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _unavailable():
    raise RuntimeError("promptfoo needs Node >= 22; install Node, then run fab-test doctor")


def test_lint_reports_offline_findings_without_promptfoo(paired, monkeypatch, capsys):
    """Review 2 should-fix 6: lint used to exit 127 before checking anything it could check offline."""
    _item, suite = paired
    twice = [{"metadata": {"id": "one"}}, {"metadata": {"id": "one"}}]
    _write(suite, {"fabTestDataAgent": "stable-id", "tests": twice})
    code, out, _err = _lint(paired, monkeypatch, capsys, _unavailable)
    assert code == 1
    assert any("duplicate" in problem for problem in json.loads(out)["suites"][0]["problems"])


def test_lint_without_promptfoo_names_why_and_never_promises_an_install(paired, monkeypatch, capsys):
    _item, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "tests": [{"metadata": {"id": "one"}}]})
    code, _out, err = _lint(paired, monkeypatch, capsys, _unavailable)
    assert code == 127
    assert "Node >= 22" in err and "Would npm install" not in err


def test_lint_counts_warnings_and_still_passes(paired, monkeypatch, capsys, tmp_path):
    _item, suite = paired
    _write(suite, {"fabTestDataAgent": "stable-id", "providers": [{"config": {"base_url": _FABRIC_URL}}],
                   "tests": [{"metadata": {"id": "one"}}]})
    monkeypatch.setattr("fab_test.scripts._data_agent_lint_command.validate_promptfoo", lambda *_a: [])
    code, out, _err = _lint(paired, monkeypatch, capsys, lambda: tmp_path / "promptfoo.js")
    result = json.loads(out)["suites"][0]
    assert code == 0 and result["ok"] and result["warnings"]
    code, out, _err = _lint(paired, monkeypatch, capsys, lambda: tmp_path / "promptfoo.js", "--format", "text", "-q")
    assert code == 0 and out.startswith("tests passed e=0 w=1 ")
