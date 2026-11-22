"""Data Agent suites pair by identity and produce a runnable promptfoo config."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from fab_test.scripts._data_agent_suite import SuiteError, effective_config, load_suite, pair_suite, suite_index

pytestmark = pytest.mark.data_agent


def _item(root: Path, name: str = "Sales") -> Path:
    item = root / f"{name}.DataAgent"
    item.mkdir()
    (item / ".platform").write_text(json.dumps({
        "metadata": {"displayName": "Deployed Sales"}, "config": {"logicalId": "stable-id"},
    }), encoding="utf-8")
    return item


def test_pairs_renamed_suite_by_logical_id(tmp_path):
    item = _item(tmp_path)
    suite = tmp_path / "OldName.DataAgent.promptfoo.yaml"
    suite.write_text("fabTestDataAgent: stable-id\ntests: []\n", encoding="utf-8")
    assert pair_suite(item, suite_index(tmp_path)) == suite
    assert pair_suite(item, {}) is None


def test_duplicate_suites_name_both_files(tmp_path):
    for name in ("First", "Second"):
        (tmp_path / f"{name}.DataAgent.promptfoo.yaml").write_text(
            "fabTestDataAgent: stable-id\n", encoding="utf-8",
        )
    with pytest.raises(SuiteError, match=r"First.*Second"):
        suite_index(tmp_path)


def test_explicit_suite_overrides_identity_pairing(tmp_path):
    item = _item(tmp_path)
    explicit = tmp_path / "custom.yaml"
    explicit.write_text("tests: []\n", encoding="utf-8")
    assert pair_suite(item, {}, explicit) == explicit


@pytest.mark.parametrize("content", ["[not, a, mapping]", "tests: [", ""])
def test_unreadable_suite_is_an_actionable_error(tmp_path, content):
    path = tmp_path / "suite.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SuiteError, match=r"suite\.yaml"):
        load_suite(path)


def test_conversation_pins_both_concurrency_and_python_workers():
    authored = {
        "fabTestDataAgent": "stable-id", "prompts": ["{{query}}"],
        "providers": [{"id": "file://provider.ts", "config": {"timeout": 90, "workers": 8}}],
        "evaluateOptions": {"maxConcurrency": 8, "showProgressBar": False},
        "tests": [{"vars": {"conversation": "sales", "query": "What about last year?"}}],
    }
    config = effective_config(authored, "https://agent.example/openai")
    assert "fabTestDataAgent" not in config
    assert config["evaluateOptions"] == {"maxConcurrency": 1, "showProgressBar": False}
    provider = config["providers"][0]
    assert provider["id"].endswith("fabric_data_agent_provider.py")
    assert provider["config"] == {"base_url": "https://agent.example/openai", "workers": 1, "timeout": 90}
    assert authored["providers"][0]["config"]["workers"] == 8


def test_explicit_urls_and_template_agent_vars_are_preserved():
    authored = {
        "providers": [{"config": {
            "base_url": "https://escape.fabric.microsoft.com/openai",
            "fabric_urls": {"sales": "https://template.fabric.microsoft.com/openai"},
        }}],
        "tests": [{"vars": {"agent": "sales", "query": "Revenue?"}}],
    }
    config = effective_config(authored, "https://resolved.example/openai")
    assert config["providers"][0]["config"]["base_url"] == "https://escape.fabric.microsoft.com/openai"
    assert config["providers"][0]["config"]["fabric_urls"] == {"sales": "https://template.fabric.microsoft.com/openai"}
    assert config["tests"] == authored["tests"]
    assert yaml.safe_load(yaml.safe_dump(config)) == config


def test_provider_loads_in_a_fresh_promptfoo_worker():
    provider = effective_config({"tests": []}, "https://agent.example/openai")["providers"][0]["id"]
    path = provider.removeprefix("file://")
    script = (
        "import importlib.util, pathlib, sys; "
        "path = pathlib.Path(sys.argv[1]); "
        "sys.path.insert(0, str(path.parent)); "
        "spec = importlib.util.spec_from_file_location(path.stem, path); "
        "module = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(module); "
        "assert callable(module.call_api)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, path],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("invalid", [
    {"providers": False}, {"providers": [None]},
    {"defaultTest": False}, {"evaluateOptions": False},
])
def test_invalid_config_is_not_silently_replaced_with_defaults(invalid):
    authored = {"tests": [{"vars": {"conversation": "sales"}}], **invalid}
    with pytest.raises(SuiteError, match="promptfoo"):
        effective_config(authored, "https://resolved.example/openai")


@pytest.mark.parametrize("authored", [
    {"env": {"FAB_TEST_DATA_AGENT_ALLOWED_HOSTS": "evil.example"}},
    {"env": {"fabric_scope": "https://graph.microsoft.com/.default"}},
    {"env": {"PLAYWRIGHT_ENV_FILE": "attacker.env"}},
    {"env": {"PROMPTFOO_PYTHON": "evil.exe"}},
    {"providers": [{"env": {"FABRIC_CLIENT_SECRET": "x"}}]},
], ids=["allowlist", "scope", "credential-file", "interpreter", "provider-env"])
def test_a_suite_env_cannot_set_fab_tests_own_variables(authored):
    """Decision 17: a suite must not widen where the token goes, retarget it, or swap the interpreter."""
    with pytest.raises(SuiteError, match="caller's environment"):
        effective_config({"tests": [], **authored}, "https://resolved.example/openai")


def test_a_suite_env_may_set_its_own_variables():
    config = effective_config({"tests": [], "env": {"REGION": "west"}}, "https://resolved.example/openai")
    assert config["env"] == {"REGION": "west"}


@pytest.mark.integration
def test_real_promptfoo_accepts_effective_config_and_test_metadata(tmp_path):
    from fab_test.scripts._analyzer_tool_bootstrap import probe_executable
    from fab_test.scripts.fab_test_registry import ANALYZERS_JSON, REPO_ROOT
    from fab_test.scripts.invoke_data_agent import promptfoo_command

    tool = probe_executable("data_agent", ANALYZERS_JSON, REPO_ROOT)
    if not tool.get("resolved_path"):
        pytest.skip("Pinned promptfoo is required for schema characterization")
    config = effective_config({
        "fabTestDataAgent": "stable-id", "prompts": ["{{query}}"],
        "tests": [{"metadata": {"id": "revenue"}, "vars": {"query": "Revenue?", "conversation": "sales"},
                   "assert": [{"type": "contains", "value": "100"}]}],
    }, "https://unused.example/openai")
    path = tmp_path / "effective.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    proc = subprocess.run(
        [*promptfoo_command(Path(tool["resolved_path"])), "validate", "config", "--config", str(path)],
        env={**os.environ, "PROMPTFOO_CONFIG_DIR": str(tmp_path / "state"),
             "PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE_CHECK": "1"},
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
