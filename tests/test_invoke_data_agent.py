"""Wrapper contract for invoke_data_agent.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.fab_test
def test_generate_effective_promptfoo_config_injects_provider_and_serial_execution(tmp_path):
    from fab_test.scripts.invoke_data_agent import generate_effective_config

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    authored = artifact / "promptfooconfig.yaml"
    authored.write_text(
        """
description: Sample
tests:
  - description: turn 1
    vars:
      conversation: sales
      query: hello
  - description: turn 2
    vars:
      query: world
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "results" / "envelope.json"

    generated = generate_effective_config(
        artifact_path=artifact,
        output_path=output_path,
        provider_path=Path("/repo/src/fab_test/scripts/fabric_data_agent_provider.py"),
        agent_url="https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/id/aiassistant/openai",
    )
    data = yaml.safe_load(generated.read_text(encoding="utf-8"))

    assert data["providers"][0]["id"].startswith("file:///repo/src/fab_test/scripts/fabric_data_agent_provider.py")
    assert data["providers"][0]["config"]["fabric_urls"]["agent1"].endswith("/aiassistant/openai")
    assert data["providers"][0]["config"]["max_retries"] == 3
    assert data["evaluateOptions"]["maxConcurrency"] == 1
    assert data["commandLineOptions"]["workers"] == 1


@pytest.mark.fab_test
def test_generate_effective_promptfoo_config_preserves_authored_provider_settings(tmp_path):
    from fab_test.scripts.invoke_data_agent import generate_effective_config

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    authored = artifact / "promptfooconfig.yaml"
    authored.write_text(
        """
providers:
  - id: file://./provider.ts
    config:
      base_url: https://example.invalid/custom-base
      fabric_urls:
        agent1: https://example.invalid/custom
      timeout: 90
      max_retries: 7
      retry_delay: 4
evaluateOptions:
  maxConcurrency: 3
commandLineOptions:
  workers: 2
tests:
  - vars:
      agent: agent1
      query: hello
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "results" / "envelope.json"

    generated = generate_effective_config(
        artifact_path=artifact,
        output_path=output_path,
        provider_path=Path("/repo/src/fab_test/scripts/fabric_data_agent_provider.py"),
        agent_url="https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/id/aiassistant/openai",
    )
    data = yaml.safe_load(generated.read_text(encoding="utf-8"))

    assert data["providers"][0]["config"]["base_url"] == "https://example.invalid/custom-base"
    assert data["providers"][0]["config"]["fabric_urls"]["agent1"] == "https://example.invalid/custom"
    assert data["providers"][0]["config"]["timeout"] == 90
    assert data["providers"][0]["config"]["max_retries"] == 7
    assert data["providers"][0]["config"]["retry_delay"] == 4
    assert data["evaluateOptions"]["maxConcurrency"] == 3
    assert data["commandLineOptions"]["workers"] == 2


@pytest.mark.fab_test
def test_promptfoo_eval_requests_json_and_html_outputs(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    captured: dict[str, object] = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    invoke_data_agent.run_promptfoo_eval(
        "/tools/promptfoo",
        tmp_path / "promptfooconfig.effective.yaml",
        tmp_path / "native.json",
        html_output_path=tmp_path / "report.html",
    )

    command = captured["command"]
    assert command.count("--output") == 2
    assert str(tmp_path / "native.json") in command
    assert str(tmp_path / "report.html") in command


@pytest.mark.fab_test
def test_promptfoo_results_are_mapped_to_findings_and_test_results(tmp_path):
    from fab_test.scripts.invoke_data_agent import map_promptfoo_results

    result_path = tmp_path / "results.json"
    result_path.write_text(
        json.dumps(
            {
                "results": {
                    "results": [
                        {
                            "description": "reject joke",
                            "success": False,
                            "vars": {"query": "tell me a joke"},
                            "response": {"output": "No"},
                            "gradingResult": {
                                "componentResults": [
                                    {
                                        "pass": False,
                                        "assertion": {"type": "contains", "value": "not relevant"},
                                        "reason": "substring missing",
                                    }
                                ]
                            },
                        },
                        {
                            "description": "answer sales",
                            "success": True,
                            "vars": {"query": "sales?"},
                            "response": {"output": "231"},
                            "gradingResult": {"componentResults": [{"pass": True}]},
                        },
                    ]
                },
                "outputPath": "promptfoo-report.html",
            }
        ),
        encoding="utf-8",
    )

    findings, test_results, html_path = map_promptfoo_results(result_path, suite_name="Sales Agent")

    assert len(findings) == 1
    assert findings[0]["rule"] == "promptfoo_assertion_failed"
    assert findings[0]["object"] == "reject joke"
    assert "substring missing" in findings[0]["message"]
    assert len(test_results) == 2
    assert test_results[0]["suite_name"] == "Sales Agent"
    assert test_results[0]["test_name"] == "reject joke"
    assert test_results[0]["passed"] is False
    assert html_path.endswith("promptfoo-report.html")


@pytest.mark.fab_test
def test_promptfoo_results_distinguish_provider_transport_failures(tmp_path):
    from fab_test.scripts.invoke_data_agent import map_promptfoo_results

    result_path = tmp_path / "results.json"
    result_path.write_text(
        json.dumps(
            {
                "results": {
                    "results": [
                        {
                            "description": "transport failure",
                            "success": False,
                            "response": {"error": "HTTP 401: ******"},
                            "gradingResult": {"componentResults": []},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    findings, test_results, html_path = map_promptfoo_results(result_path, suite_name="Sales Agent")

    assert html_path == ""
    assert findings == [
        {
            "rule": "promptfoo_provider_error",
            "severity": "error",
            "object": "transport failure",
            "message": "HTTP 401: ******",
        }
    ]
    assert test_results[0]["expected"] == "provider returns a response without transport errors"
    assert test_results[0]["actual"] == "HTTP 401: ******"


def _set_service_principal(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "22222222-2222-2222-2222-222222222222")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "super-secret-value")


@pytest.mark.fab_test
def test_invoke_data_agent_preflight_names_exact_variables_before_promptfoo(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    (artifact / "promptfooconfig.yaml").write_text("tests: []\n", encoding="utf-8")
    output_path = tmp_path / "results" / "envelope.json"
    monkeypatch.delenv("FABRIC_TENANT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(
        invoke_data_agent,
        "run_promptfoo_eval",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("promptfoo must not run")),
    )

    code = invoke_data_agent.main(
        [
            "--artifact-path",
            str(artifact),
            "--artifact-name",
            "Sales Agent",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--output-path",
            str(output_path),
        ]
    )

    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 127
    assert envelope["status"] == "error"
    assert "FABRIC_TENANT_ID" in envelope["message"]
    assert "FABRIC_CLIENT_ID" in envelope["message"]
    assert "FABRIC_CLIENT_SECRET" in envelope["message"]
    assert "fab-test auth status" in envelope["message"]


@pytest.mark.fab_test
def test_invoke_data_agent_skips_a_folder_without_promptfoo_config(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    output_path = tmp_path / "results" / "envelope.json"
    _set_service_principal(monkeypatch)

    code = invoke_data_agent.main(
        [
            "--artifact-path",
            str(artifact),
            "--artifact-name",
            "Sales Agent",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--output-path",
            str(output_path),
        ]
    )

    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert envelope["status"] == "skipped"
    assert "fab-test data-agent init" in envelope["message"]


@pytest.mark.fab_test
def test_invoke_data_agent_missing_promptfoo_is_a_127_preflight(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    (artifact / "promptfooconfig.yaml").write_text("tests: []\n", encoding="utf-8")
    output_path = tmp_path / "results" / "envelope.json"
    _set_service_principal(monkeypatch)
    monkeypatch.setattr(
        invoke_data_agent,
        "_resolve_promptfoo_path",
        lambda _raw: (_ for _ in ()).throw(RuntimeError("promptfoo not found. install it.")),
    )
    monkeypatch.setattr(
        invoke_data_agent,
        "_resolve_agent_url",
        lambda _args: (_ for _ in ()).throw(AssertionError("URL resolution must not run before promptfoo preflight")),
    )

    code = invoke_data_agent.main(
        [
            "--artifact-path",
            str(artifact),
            "--artifact-name",
            "Sales Agent",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--output-path",
            str(output_path),
        ]
    )

    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 127
    assert envelope["status"] == "error"
    assert "promptfoo not found" in envelope["message"]


@pytest.mark.fab_test
def test_invoke_data_agent_reports_missing_native_output_after_promptfoo_runs(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    (artifact / "promptfooconfig.yaml").write_text("tests: []\n", encoding="utf-8")
    output_path = tmp_path / "results" / "envelope.json"
    _set_service_principal(monkeypatch)
    monkeypatch.setattr(invoke_data_agent, "_resolve_promptfoo_path", lambda _raw: "/tools/promptfoo")
    monkeypatch.setattr(
        invoke_data_agent,
        "_resolve_agent_url",
        lambda _args: "https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/id/aiassistant/openai",
    )
    monkeypatch.setattr(
        invoke_data_agent,
        "run_promptfoo_eval",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""),
    )

    code = invoke_data_agent.main(
        [
            "--artifact-path",
            str(artifact),
            "--artifact-name",
            "Sales Agent",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--output-path",
            str(output_path),
        ]
    )

    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 1
    assert envelope["status"] == "error"
    assert "native.json" in envelope["message"]
    assert "--output" in envelope["message"]


@pytest.mark.fab_test
def test_invoke_data_agent_honors_authored_base_url_without_service_resolution(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    (artifact / "promptfooconfig.yaml").write_text(
        """
providers:
  - config:
      base_url: https://example.invalid/custom-agent
tests:
  - description: healthy
    vars:
      query: hello
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "results" / "envelope.json"
    native_output = output_path.with_name("native.json")
    html_output = output_path.with_name("report.html")
    _set_service_principal(monkeypatch)
    monkeypatch.setattr(invoke_data_agent, "_resolve_promptfoo_path", lambda _raw: "/tools/promptfoo")
    monkeypatch.setattr(
        invoke_data_agent,
        "_resolve_agent_url",
        lambda _args: (_ for _ in ()).throw(AssertionError("authored base_url should be the escape hatch")),
    )

    def _fake_promptfoo(_promptfoo_path, _config_path, _native_output, *, html_output_path, env):
        native_output.write_text(
            json.dumps(
                {
                    "results": {
                        "results": [
                            {
                                "description": "healthy",
                                "success": True,
                                "response": {"output": "ok"},
                                "gradingResult": {"componentResults": [{"pass": True}]},
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        html_output_path.write_text("<html></html>", encoding="utf-8")
        return subprocess.CompletedProcess(["promptfoo"], 0, stdout="", stderr="")

    monkeypatch.setattr(invoke_data_agent, "run_promptfoo_eval", _fake_promptfoo)

    code = invoke_data_agent.main(
        [
            "--artifact-path",
            str(artifact),
            "--artifact-name",
            "Sales Agent",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--output-path",
            str(output_path),
        ]
    )

    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert envelope["status"] == "passed"
    assert envelope["native_html_output_path"] == str(html_output)


@pytest.mark.fab_test
def test_invoke_data_agent_redacts_envelope_native_and_effective_config(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    env_file = artifact / ".env"
    env_file.write_text(
        "FABRIC_TENANT_ID=11111111-1111-1111-1111-111111111111\n"
        "FABRIC_CLIENT_ID=22222222-2222-2222-2222-222222222222\n"
        "FABRIC_CLIENT_SECRET=super-secret-value\n"
        "PROMPTFOO_API_KEY=file-secret-value\n",
        encoding="utf-8",
    )
    (artifact / "promptfooconfig.yaml").write_text(
        """
description: file-secret-value should not survive
providers:
  - config:
      base_url: https://example.invalid/custom-agent
tests:
  - description: provider error
    vars:
      query: hello
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "results" / "envelope.json"
    native_output = output_path.with_name("native.json")
    html_output = output_path.with_name("report.html")
    monkeypatch.delenv("FABRIC_TENANT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(invoke_data_agent, "_resolve_promptfoo_path", lambda _raw: "/tools/promptfoo")

    def _fake_promptfoo(_promptfoo_path, _config_path, _native_output, *, html_output_path, env):
        native_output.write_text(
            json.dumps(
                {
                    "results": {
                        "results": [
                            {
                                "description": "provider error",
                                "success": False,
                                "response": {
                                    "error": "super-secret-value file-secret-value Authorization: ******"
                                },
                                "gradingResult": {"componentResults": []},
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        html_output_path.write_text("<html></html>", encoding="utf-8")
        return subprocess.CompletedProcess(["promptfoo"], 1, stdout="", stderr="")

    monkeypatch.setattr(invoke_data_agent, "run_promptfoo_eval", _fake_promptfoo)

    code = invoke_data_agent.main(
        [
            "--artifact-path",
            str(artifact),
            "--artifact-name",
            "Sales Agent",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--output-path",
            str(output_path),
            "--env-file",
            str(env_file),
        ]
    )

    envelope_text = output_path.read_text(encoding="utf-8")
    native_text = native_output.read_text(encoding="utf-8")
    effective_config_text = output_path.with_name("promptfooconfig.effective.yaml").read_text(encoding="utf-8")

    assert code == 1
    for text in (envelope_text, native_text, effective_config_text):
        assert "super-secret-value" not in text
        assert "file-secret-value" not in text
        assert "<redacted>" in text or "******" in text
    assert json.loads(envelope_text)["native_html_output_path"] == str(html_output)


@pytest.mark.fab_test
def test_invoke_data_agent_reports_partial_service_principal_from_env_file(monkeypatch, tmp_path):
    from fab_test.scripts import invoke_data_agent

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    (artifact / "promptfooconfig.yaml").write_text("tests: []\n", encoding="utf-8")
    env_file = artifact / ".env"
    env_file.write_text(
        "FABRIC_TENANT_ID=11111111-1111-1111-1111-111111111111\n"
        "FABRIC_CLIENT_ID=22222222-2222-2222-2222-222222222222\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "results" / "envelope.json"
    monkeypatch.delenv("FABRIC_TENANT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_ID", raising=False)
    monkeypatch.delenv("FABRIC_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(
        invoke_data_agent,
        "run_promptfoo_eval",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("promptfoo must not run")),
    )

    code = invoke_data_agent.main(
        [
            "--artifact-path",
            str(artifact),
            "--artifact-name",
            "Sales Agent",
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--output-path",
            str(output_path),
            "--env-file",
            str(env_file),
        ]
    )

    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 127
    assert envelope["status"] == "error"
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in envelope["message"]
