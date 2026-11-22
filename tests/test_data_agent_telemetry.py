"""Data Agent telemetry: its table, type and mode, answers kept, and no secret (decision 20, Review 1 item 11).

The envelope comes from the real wrapper with a fake promptfoo, so the test sees what a run would ship.
"""

import json
import subprocess
from pathlib import Path

import pytest

from fab_test.scripts import invoke_data_agent as wrapper
from fab_test.scripts.fab_test_telemetry import _send_telemetry
from tests.test_data_agent_wrapper import _args, _principal

pytestmark = [pytest.mark.data_agent, pytest.mark.telemetry]


class _Sink:
    def __init__(self):
        self.records: list[tuple[str, dict]] = []

    def add(self, table, payload):
        self.records.append((table, payload))


class _EnabledArgs:
    def __init__(self):
        self.telemetry, self.mode, self.output_format, self.environment = True, "service", "text", ""
        self.file_config = {"telemetry": {"eventhouse": {"uri": "https://trd-x.z9.kusto.fabric.microsoft.com",
                                                         "database": "fabric_ops"}}}


def _envelope(tmp_path, monkeypatch) -> dict:
    _principal(monkeypatch)
    monkeypatch.setattr(wrapper, "_terminal", lambda: None)
    args = _args(tmp_path)

    def run(command, **_kwargs):
        Path(command[command.index("--output") + 1]).write_text(json.dumps({"results": {"results": [
            {"success": True, "description": "Count", "response": {"output": "16,376"}},
            {"success": False, "description": "Leak", "response": {"output": "private-secret-value Bearer live-tok"},
             "gradingResult": {"componentResults": [{"pass": False, "reason": "did not decline"}]}},
        ]}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])
    assert wrapper.run_data_agent(args) == 1
    return json.loads(Path(args.output_path).read_text(encoding="utf-8"))


def test_a_data_agent_record_goes_to_the_dynamic_table_typed_and_moded(tmp_path, monkeypatch):
    envelope = {**_envelope(tmp_path, monkeypatch), "mode": "service"}
    sink = _Sink()
    _send_telemetry("data_agent", tmp_path / "Sales.DataAgent", envelope, _EnabledArgs(), sink=sink)
    [(table, payload)] = sink.records
    assert table == "fabric_dynamic_analysis"
    assert payload["artifact_type"] == "DataAgent" and payload["analyzer"] == "data_agent"
    assert payload["mode"] == "service" and payload["status"] == "failed"


def test_a_data_agent_record_keeps_the_answers_and_no_secret(tmp_path, monkeypatch):
    """Answer history is what shows drift; the token, secret and agent URL never ship."""
    envelope = {**_envelope(tmp_path, monkeypatch), "mode": "service"}
    sink = _Sink()
    _send_telemetry("data_agent", tmp_path / "Sales.DataAgent", envelope, _EnabledArgs(), sink=sink)
    shipped = json.dumps(sink.records[0][1])
    assert "16,376" in shipped
    assert "private-secret-value" not in shipped and "live-tok" not in shipped
    assert "agent.example" not in shipped  # the resolved agent URL is a connection detail
