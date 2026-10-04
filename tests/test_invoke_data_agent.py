"""Wrapper contract for invoke_data_agent.py."""

from __future__ import annotations

import json
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
    assert data["evaluateOptions"]["maxConcurrency"] == 1
    assert data["commandLineOptions"]["workers"] == 1


@pytest.mark.fab_test
def test_generate_effective_promptfoo_config_keeps_authored_explicit_urls(tmp_path):
    from fab_test.scripts.invoke_data_agent import generate_effective_config

    artifact = tmp_path / "Sales Agent.DataAgent"
    artifact.mkdir()
    authored = artifact / "promptfooconfig.yaml"
    authored.write_text(
        """
providers:
  - id: file://./provider.ts
    config:
      fabric_urls:
        agent1: https://example.invalid/custom
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

    assert data["providers"][0]["config"]["fabric_urls"]["agent1"] == "https://example.invalid/custom"


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
    assert html_path == "promptfoo-report.html"


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
