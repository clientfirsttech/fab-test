"""Wrapper verdicts and persisted output without live, capacity-consuming agent calls."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from fab_test.scripts import invoke_data_agent as wrapper

pytestmark = pytest.mark.data_agent


@pytest.fixture(autouse=True)
def _no_terminal(monkeypatch):
    """Progress goes to the real terminal; tests that want it hand the wrapper a buffer."""
    monkeypatch.setattr(wrapper, "_terminal", lambda: None)


def _args(tmp_path, **overrides):
    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    suite.write_text("tests:\n- vars: {query: 'Revenue?', conversation: sales}\n", encoding="utf-8")
    return argparse.Namespace(**{
        "artifact_path": str(tmp_path / "Sales.DataAgent"),
        "tests": str(suite), "base_url": "https://agent.example/openai",
        "promptfoo_path": str(tmp_path / "cli.js"), "env_file": None,
        "output_path": str(tmp_path / "results" / "envelope.json"), "timeout": 60,
        **overrides,
    })


def _principal(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "private-secret-value")


def test_maps_failed_components_and_keeps_passing_tests():
    data = {"results": {"results": [
        {"success": False, "description": "Revenue", "testCase": {"assert": [{"type": "contains", "value": "100"}]},
         "response": {"output": "90"}, "gradingResult": {"componentResults": [
             {"pass": False, "reason": "Missing 100", "assertion": {"type": "contains"}},
             {"pass": True, "reason": "Other check"},
         ]}},
        {"success": True, "description": "Refusal", "response": {"output": "Cannot answer"}},
    ]}}
    findings, results = wrapper.map_results(data, "Sales")
    assert len(findings) == 1
    assert findings[0] == {
        "rule": "contains", "severity": "error", "object": "Revenue", "message": "Missing 100",
    }
    assert [r["passed"] for r in results] == [False, True]
    assert results[0]["actual"] == "90"
    assert "100" in results[0]["expected"]


@pytest.mark.parametrize("payload", [{}, {"results": {"results": []}}, {"results": {"results": [{}]}}])
def test_invalid_or_empty_result_is_not_a_pass(payload):
    with pytest.raises(ValueError, match="promptfoo"):
        wrapper.map_results(payload, "Sales")


def test_run_redacts_native_config_envelope_and_quiet_output(tmp_path, monkeypatch, capsys):
    _principal(monkeypatch)
    monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
    monkeypatch.setenv("ANALYZER_REPORT", "1")
    args = _args(tmp_path)
    observed = {}

    def run(command, **kwargs):
        observed.update(kwargs)
        config = yaml.safe_load(Path(command[command.index("--config") + 1]).read_text(encoding="utf-8"))
        assert config["providers"][0]["config"]["workers"] == 1
        output = Path(command[command.index("--output") + 1])
        output.write_text(json.dumps({"results": {"results": [
            {"pass": True, "response": {"output": "private-secret-value Bearer live-token"}},
        ]}}), encoding="utf-8")
        return __import__("subprocess").CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])
    assert wrapper.run_data_agent(args) == 0
    assert observed["env"]["PROMPTFOO_PYTHON"] == sys.executable
    assert capsys.readouterr().out == ""
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["started_at"]
    assert Path(envelope["native_html_output_path"]).is_file()
    for path in Path(args.output_path).parent.iterdir():
        text = path.read_text(encoding="utf-8")
        assert "private-secret-value" not in text
        assert "live-token" not in text
    assert envelope["test_results"][0]["passed"]


def test_missing_credentials_exits_127_without_promptfoo(tmp_path, monkeypatch):
    for key in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
                "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET"):
        monkeypatch.delenv(key, raising=False)
    args = _args(tmp_path, env_file=str(tmp_path / "absent.env"))
    assert wrapper.run_data_agent(args) == 127
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "error"
    assert envelope["message"].count("fab-test auth status") == 1  # the remediation once, not twice
    assert envelope["native_output_path"] == ""


@pytest.mark.parametrize("returncode,payload", [
    (2, {"results": {"results": [{"success": False}]}}),
    (0, {}),
])
def test_crash_or_usage_error_never_becomes_test_verdicts(tmp_path, monkeypatch, returncode, payload):
    _principal(monkeypatch)
    args = _args(tmp_path)

    def run(command, **_kwargs):
        Path(command[command.index("--output") + 1]).write_text(json.dumps(payload), encoding="utf-8")
        return __import__("subprocess").CompletedProcess(command, returncode, "", "usage error Bearer live-token")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])
    assert wrapper.run_data_agent(args) == 1
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "error"
    assert "test_results" not in envelope
    assert "live-token" not in json.dumps(envelope)


_SHUTDOWN_CRASH = (3221226505, "Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src/win/async.c")


@pytest.mark.parametrize(("rows", "status"), [
    ([{"success": True, "description": "Revenue", "response": {"output": "100"}}], "passed"),
    ([], "error"),  # nothing complete to grade: the crash stays an error
])
def test_a_shutdown_crash_after_complete_results_is_graded(tmp_path, monkeypatch, rows, status):
    """Decision 24: Node's libuv abort at exit is not a verdict; eval is never run twice."""
    _principal(monkeypatch)
    args = _args(tmp_path)
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        Path(command[command.index("--output") + 1]).write_text(
            json.dumps({"results": {"results": rows}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, _SHUTDOWN_CRASH[0], "", _SHUTDOWN_CRASH[1])

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])
    wrapper.run_data_agent(args)
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["status"] == status, envelope.get("message")
    assert len(calls) == 1


@pytest.mark.parametrize("error_row", [
    {"success": False, "error": "Worker failed to become ready", "failureReason": 2},
    {"success": False, "error": "Service principal unavailable",
     "response": {"error": "Service principal unavailable"}},
])
def test_provider_errors_are_not_assertion_failures(tmp_path, monkeypatch, error_row):
    _principal(monkeypatch)
    args = _args(tmp_path)
    monkeypatch.setattr(wrapper, "_evaluate", lambda *_args: {"results": {"results": [error_row]}})
    assert wrapper.run_data_agent(args) == 1
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "error"
    assert error_row["error"] in envelope["message"]
    assert "test_results" not in envelope


_SP_VARS = ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
            "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET")


def _capture_worker(monkeypatch):
    """Run the wrapper against a fake promptfoo that records what its Python worker would see."""
    from fab_test.scripts._credentials import resolve_service_principal

    seen = {}

    def run(command, **kwargs):
        credential_file = Path(kwargs["env"]["PLAYWRIGHT_ENV_FILE"])
        seen.update(cwd=kwargs["cwd"], env=kwargs["env"], credential_file=credential_file,
                    principal=resolve_service_principal(credential_file))
        Path(command[command.index("--output") + 1]).write_text(
            json.dumps({"results": {"results": [{"success": True}]}}), encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])
    return seen


def test_worker_uses_the_preflight_env_file_from_the_callers_directory(tmp_path, monkeypatch):
    for key in (*_SP_VARS, "PLAYWRIGHT_ENV_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".fab-test" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("FABRIC_TENANT_ID=tenant\nFABRIC_CLIENT_ID=client\n"
                        "FABRIC_CLIENT_SECRET=private-secret-value\n", encoding="utf-8")
    suite_dir = tmp_path / "artifacts"
    suite_dir.mkdir()
    args = _args(suite_dir, output_path=str(tmp_path / "result" / "envelope.json"))
    seen = _capture_worker(monkeypatch)

    assert wrapper.run_data_agent(args) == 0
    assert seen["cwd"] == suite_dir  # the worker runs elsewhere, yet gets the preflight's principal
    assert (seen["principal"].tenant_id, seen["principal"].client_secret) == ("tenant", "private-secret-value")


def test_promptfoos_environment_carries_no_service_principal(tmp_path, monkeypatch):
    """Decision 19: suites can template {{ env.* }} and run JavaScript, so the secret stays out of env."""
    _principal(monkeypatch)
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "alias-secret-value")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "azure-secret-value")
    monkeypatch.setenv("FABRIC_SCOPE", "https://analysis.windows.net/powerbi/api/.default")
    monkeypatch.setenv("FAB_TEST_DATA_AGENT_ALLOWED_HOSTS", "gateway.contoso.example")
    caller_file = tmp_path / "caller.env"
    caller_file.write_text("FABRIC_TENANT_ID=other\nFABRIC_CLIENT_ID=other\nFABRIC_CLIENT_SECRET=other-secret\n",
                           encoding="utf-8")
    args = _args(tmp_path, env_file=str(caller_file))
    seen = _capture_worker(monkeypatch)

    assert wrapper.run_data_agent(args) == 0
    env = seen["env"]
    assert not {*_SP_VARS, "AZURE_CLIENT_SECRET"} & set(env)
    assert not any(value in json.dumps(env) for value in ("private-secret-value", "alias-secret-value",
                                                           "azure-secret-value"))
    assert env["FABRIC_SCOPE"] and env["FAB_TEST_DATA_AGENT_ALLOWED_HOSTS"]  # the caller's settings pass through
    # The environment won the preflight, so the worker gets that principal, not the caller file's.
    assert seen["principal"].client_secret == "alias-secret-value"
    assert seen["credential_file"] != caller_file
    assert not seen["credential_file"].exists()  # deleted when the run ends
    assert not seen["credential_file"].is_relative_to(Path(args.output_path).parent)


def test_missing_suite_skips_without_credentials(tmp_path):
    args = _args(tmp_path, tests=None)
    assert wrapper.run_data_agent(args) == 0
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "skipped"
    assert "tests init" in envelope["message"]


@pytest.mark.integration
def test_real_promptfoo_maps_native_failures_without_service_calls(tmp_path, monkeypatch):
    from fab_test.scripts._analyzer_tool_bootstrap import probe_executable
    from fab_test.scripts.fab_test_registry import ANALYZERS_JSON, REPO_ROOT

    tool = probe_executable("data_agent", ANALYZERS_JSON, REPO_ROOT)
    if not tool.get("resolved_path") or not shutil.which("node"):
        pytest.skip("Pinned promptfoo and Node are required for the real-tool contract test")
    _principal(monkeypatch)
    args = _args(tmp_path, promptfoo_path=tool["resolved_path"])
    provider = tmp_path / "echo.py"
    provider.write_text(
        "from fab_test.scripts._credentials import resolve_service_principal\n"
        "def call_api(prompt, options, context):\n"
        "    return {'output': prompt + ' ' + resolve_service_principal().client_secret}\n",
        encoding="utf-8",
    )
    Path(args.tests).write_text(yaml.safe_dump({
        "prompts": ["{{query}}"], "tests": [
            {"description": "Passing answer", "vars": {"query": "100", "conversation": "sales"},
             "assert": [{"type": "contains", "value": "100"}]},
            {"description": "Failing answer", "vars": {"query": "90", "conversation": "sales"},
             "assert": [{"type": "contains", "value": "100"}]},
        ],
    }), encoding="utf-8")
    original = wrapper.effective_config

    def echo_config(document, url):
        config = original(document, url)
        config["providers"][0]["id"] = f"file://{provider.as_posix()}"
        return config

    monkeypatch.setattr(wrapper, "effective_config", echo_config)
    monkeypatch.setenv("PROMPTFOO_DISABLE_UPDATE_CHECK", "1")
    assert wrapper.run_data_agent(args) == 1
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "failed", envelope["message"]  # e.g. the Windows libuv exit, item 5
    assert [r["passed"] for r in envelope["test_results"]] == [True, False]
    assert len(envelope["findings"]) == 1
    assert "private-secret-value" not in Path(envelope["native_output_path"]).read_text(encoding="utf-8")


@pytest.mark.integration
def test_real_promptfoo_worker_reads_callers_env_file(tmp_path, monkeypatch):
    from fab_test.scripts._analyzer_tool_bootstrap import probe_executable
    from fab_test.scripts.fab_test_registry import ANALYZERS_JSON, REPO_ROOT

    tool = probe_executable("data_agent", ANALYZERS_JSON, REPO_ROOT)
    if not tool.get("resolved_path") or not shutil.which("node"):
        pytest.skip("Pinned promptfoo and Node are required for the real-tool contract test")
    for key in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
                "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET", "PLAYWRIGHT_ENV_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROMPTFOO_DISABLE_UPDATE_CHECK", "1")
    env_file = tmp_path / ".fab-test" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("FABRIC_TENANT_ID=tenant\nFABRIC_CLIENT_ID=client\n"
                        "FABRIC_CLIENT_SECRET=private-secret-value\n", encoding="utf-8")
    suite_dir = tmp_path / "artifacts"
    suite_dir.mkdir()
    args = _args(suite_dir, promptfoo_path=tool["resolved_path"],
                 output_path=str(tmp_path / "result" / "envelope.json"))
    provider = suite_dir / "credential_probe.py"
    provider.write_text(
        "from fab_test.scripts._credentials import resolve_service_principal\n"
        "def call_api(prompt, options, context):\n"
        "    return {'output': 'found' if resolve_service_principal() else 'missing'}\n",
        encoding="utf-8",
    )
    Path(args.tests).write_text(yaml.safe_dump({
        "prompts": ["{{query}}"], "tests": [
            {"vars": {"query": "check"}, "assert": [{"type": "equals", "value": "found"}]},
        ],
    }), encoding="utf-8")
    original = wrapper.effective_config

    def probe_config(document, url):
        config = original(document, url)
        config["providers"][0]["id"] = f"file://{provider.as_posix()}"
        return config

    monkeypatch.setattr(wrapper, "effective_config", probe_config)
    assert wrapper.run_data_agent(args) == 0
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["status"] == "passed"
    assert "private-secret-value" not in json.dumps(envelope)


def test_real_console_script_output_modes_and_service_mode(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the subprocess contract test")
    import os

    item = tmp_path / "Sales.DataAgent"
    item.mkdir()
    (item / ".platform").write_text(json.dumps({
        "config": {"logicalId": "stable"}, "metadata": {"displayName": "Sales"},
    }), encoding="utf-8")
    (tmp_path / "Sales.DataAgent.promptfoo.yaml").write_text(yaml.safe_dump({
        "fabTestDataAgent": "stable", "prompts": ["{{query}}"],
        "providers": [{"config": {"base_url": "https://unused.fabric.microsoft.com/openai"}}],
        "tests": [{"vars": {"query": "Revenue?"}}],
    }), encoding="utf-8")
    tool = tmp_path / "fixture.js"
    tool.write_text(
        "const fs = require('fs'); const args = process.argv;\n"
        "if (args.includes('--version')) { console.log('0.124.0'); process.exit(0); }\n"
        "const output = args[args.indexOf('--output') + 1];\n"
        "fs.writeFileSync(output, JSON.stringify({results: {results: "
        "[{success: true, description: 'Revenue', response: {output: '100'}}]}}));\n",
        encoding="utf-8",
    )
    env = {**os.environ, "FAB_TEST_ENABLE_DATA_AGENT": "1", "PROMPTFOO_PATH": str(tool),
           "FABRIC_WORKSPACE_ID": "00000000-0000-0000-0000-000000000000",
           "FABRIC_TENANT_ID": "tenant", "FABRIC_CLIENT_ID": "client",
           "FABRIC_CLIENT_SECRET": "private-secret-value", "CI": "true",
           "FABRIC_SERVICE_PRINCIPAL_ID": "", "FABRIC_SERVICE_PRINCIPAL_SECRET": ""}
    config = tmp_path / "fab-test.yml"
    config.write_text(yaml.safe_dump({"artifact_dir": str(tmp_path)}), encoding="utf-8")
    cli = str(Path(sys.executable).with_name("fab-test.exe")) if sys.platform == "win32" else "fab-test"
    for index, flags in enumerate([[], ["-q"], ["-v"], ["--format", "json"], ["--report"], ["--open-report"]]):
        output = tmp_path / f"result-{index}"
        proc = subprocess.run(
            [cli, "data-agent", "--artifact-dir", str(tmp_path), "--output-dir", str(output),
             "--no-telemetry", *flags],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        envelope = json.loads((output / "data_agent" / "Sales" / "envelope.json").read_text(encoding="utf-8"))
        assert envelope["mode"] == "service"
        assert envelope["source"] == "env"
        if flags == ["-q"]:
            assert len(proc.stdout.strip().splitlines()) == 1
        if "--format" in flags:
            assert json.loads(proc.stdout)["analyzer"] == "data_agent"
        if "--report" in flags or "--open-report" in flags:
            assert Path(envelope["native_html_output_path"]).is_file()
    for command in (["list"], ["explain", "data-agent"], ["doctor", "--analyzer", "data-agent"],
                    ["all", "--output-dir", str(tmp_path / "all-results"), "--no-telemetry"],
                    ["local", "--dry-run"]):
        artifact_flags = ["--artifact-dir", str(tmp_path)] if command[0] != "doctor" else []
        proc = subprocess.run(
            [cli, "--config", str(config), *command, *artifact_flags, "--format", "json"],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload
        if command[0] == "local":
            assert "data_agent" not in proc.stdout
        if command[0] == "all":
            assert "data_agent" in proc.stdout
    tool.write_text(
        "if (process.argv.includes('--version')) { console.log('0.124.0'); process.exit(0); }\n"
        "setTimeout(() => {}, 10000);\n",
        encoding="utf-8",
    )
    output = tmp_path / "timeout-result"
    proc = subprocess.run(
        [cli, "--config", str(config), "data-agent", "--artifact-dir", str(tmp_path), "--output-dir", str(output),
         "--timeout", "3", "--no-telemetry", "-q"],
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=10,
    )
    assert proc.returncode == 1
    envelope = json.loads((output / "data_agent" / "Sales" / "envelope.json").read_text(encoding="utf-8"))
    assert envelope["status"] == "error"
    assert envelope["started_at"]  # the wrapper, not the outer timeout fallback, recorded this failure
    assert envelope["duration_ms"] < 3000


def test_progress_shows_each_answer_live_then_a_verdict_per_test(tmp_path, monkeypatch):
    """Follow-up 18: a minute of live agent calls must not look hung."""
    import io

    _principal(monkeypatch)
    args = _args(tmp_path)
    Path(args.tests).write_text(yaml.safe_dump({"tests": [
        {"description": "Count", "vars": {"query": "How many?"}},
        {"description": "Refuse", "vars": {"query": "My balance?"}},
    ]}), encoding="utf-8")
    shown = io.StringIO()
    shown.close = lambda: None  # the wrapper closes the terminal it opened; keep the buffer readable
    monkeypatch.setattr(wrapper, "_terminal", lambda: shown)
    live = []

    def run(command, **kwargs):
        progress = Path(kwargs["env"]["FAB_TEST_DATA_AGENT_PROGRESS"])
        for query, seconds in (("How many?", 18), ("My balance?", 21)):
            with progress.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"query": query, "seconds": seconds, "error": False}) + "\n")
            # the watcher polls every 0.25 s: wait until it prints, while promptfoo still "runs"
            deadline = time.monotonic() + 10
            while query not in shown.getvalue() and time.monotonic() < deadline:
                time.sleep(0.05)
            live.append(shown.getvalue())
        Path(command[command.index("--output") + 1]).write_text(json.dumps({"results": {"results": [
            {"success": True, "description": "Count", "response": {"output": "42"}},
            {"success": False, "description": "Refuse", "response": {"output": "Sure: 9"},
             "gradingResult": {"componentResults": [{"pass": False, "reason": "did not decline"}]}},
        ]}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])

    assert wrapper.run_data_agent(args) == 1
    text = shown.getvalue()
    assert "asking 2 questions of Sales" in text and "live agent calls" in text
    assert "1/2 answered in 18 s: How many?" in live[0]  # printed while the run was still going
    assert "2/2 answered in 21 s: My balance?" in live[1]
    assert "✓ Count" in text and "✗ Refuse: did not decline" in text


def test_progress_stays_off_under_quiet_and_in_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
    assert wrapper._terminal() is None
    monkeypatch.delenv("ANALYZER_VERBOSITY")
    monkeypatch.setenv("CI", "true")
    assert wrapper._terminal() is None
