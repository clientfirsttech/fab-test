"""The Data Agent wrapper tells its caller why a run failed, once (Polite HTTP epic, Data Agent Wrapper Timeout).

Always mocked: promptfoo is replaced by a function that writes the provider's progress lines.
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from fab_test.scripts import invoke_data_agent as wrapper
from fab_test.scripts._data_agent_progress import Progress
from tests.test_data_agent_wrapper import _args, _no_terminal, _principal

pytestmark = pytest.mark.data_agent
__all__ = ["_no_terminal"]  # an autouse fixture, used by name

BLOCKED = ("Fabric is rate-limiting this identity (RequestBlocked) until 16:38:24 UTC. Every run or tool using "
           "the same identity shares its quota. Wait and rerun.")
RETRY_AFTER = "2026-11-22T16:38:24Z"


def _suite(args, count: int) -> None:
    Path(args.tests).write_text(yaml.safe_dump({"tests": [
        {"description": f"Q{n}", "vars": {"query": f"Question {n}?"}} for n in range(1, count + 1)
    ]}), encoding="utf-8")


def _progress(env, *lines) -> None:
    with Path(env["FAB_TEST_DATA_AGENT_PROGRESS"]).open("a", encoding="utf-8") as stream:
        for line in lines:
            stream.write(json.dumps(line) + "\n")


def _envelope(args) -> dict:
    return json.loads(Path(args.output_path).read_text(encoding="utf-8"))


@pytest.fixture
def promptfoo(monkeypatch):
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])

    def install(run):
        monkeypatch.setattr(wrapper.subprocess, "run", run)
    return install


def test_given_promptfoo_killed_at_the_timeout_should_name_the_last_cause_not_the_command(
        tmp_path, monkeypatch, promptfoo):
    _principal(monkeypatch)
    args = _args(tmp_path, timeout=198)
    _suite(args, 7)

    def run(command, **kwargs):
        _progress(kwargs["env"],
                  {"query": "Question 1?", "seconds": 18, "error": False},
                  {"query": "Question 2?", "seconds": 16, "error": True, "message": BLOCKED,
                   "retry_after": RETRY_AFTER})
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    promptfoo(run)

    assert wrapper.run_data_agent(args) == 1
    envelope = _envelope(args)
    assert envelope["status"] == "error"
    assert "did not finish within 198 s" in envelope["message"]
    assert "2 of 7 questions" in envelope["message"] and "1 answered" in envelope["message"]
    assert BLOCKED in envelope["message"] and "--timeout" in envelope["message"]
    assert "node" not in envelope["message"] and "Command '" not in envelope["message"]
    assert envelope["retry_after"] == RETRY_AFTER


def test_given_a_timeout_with_no_failure_should_say_the_agent_was_slow(tmp_path, monkeypatch, promptfoo):
    _principal(monkeypatch)
    args = _args(tmp_path, timeout=60)
    _suite(args, 3)

    def run(command, **kwargs):
        _progress(kwargs["env"], {"query": "Question 1?", "seconds": 40, "error": False})
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    promptfoo(run)

    wrapper.run_data_agent(args)
    message = _envelope(args)["message"]
    assert "1 of 3 questions" in message and "slow" in message and "--timeout" in message
    assert "retry_after" not in _envelope(args)


def test_given_every_question_failing_for_one_reason_should_say_it_once(tmp_path, monkeypatch, promptfoo):
    _principal(monkeypatch)
    args = _args(tmp_path)
    _suite(args, 3)

    def run(command, **kwargs):
        _progress(kwargs["env"], *[
            {"query": f"Question {n}?", "seconds": 0, "error": True, "message": text, "retry_after": RETRY_AFTER}
            for n, text in ((1, BLOCKED), (2, f"Not asked: {BLOCKED}"), (3, f"Not asked: {BLOCKED}"))])
        Path(command[command.index("--output") + 1]).write_text(json.dumps({"results": {"results": [
            {"success": False, "description": f"Q{n}", "response": {"error": text}, "failureReason": 2}
            for n, text in ((1, BLOCKED), (2, f"Not asked: {BLOCKED}"), (3, f"Not asked: {BLOCKED}"))
        ]}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 100, "", "")

    promptfoo(run)

    assert wrapper.run_data_agent(args) == 1
    envelope = _envelope(args)
    assert envelope["message"] == f"3 of 3 questions could not be asked: {BLOCKED}"
    assert envelope["retry_after"] == RETRY_AFTER


def test_given_questions_failing_for_different_reasons_should_name_the_first_and_count_the_rest(
        tmp_path, monkeypatch, promptfoo):
    _principal(monkeypatch)
    args = _args(tmp_path)
    _suite(args, 3)

    def run(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_text(json.dumps({"results": {"results": [
            {"success": True, "description": "Q1", "response": {"output": "42"}},
            {"success": False, "description": "Q2", "response": {"error": "api.example answered HTTP 404: gone."}},
            {"success": False, "description": "Q3", "response": {"error": "api.example did not answer (reset)."}},
        ]}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 100, "", "")

    promptfoo(run)

    wrapper.run_data_agent(args)
    message = _envelope(args)["message"]
    assert message.startswith("2 of 3 questions could not be asked: api.example answered HTTP 404: gone.")
    assert "1 more failed another way" in message


def test_progress_names_why_a_question_failed(tmp_path):
    shown = io.StringIO()
    path = tmp_path / "progress.jsonl"
    path.write_text(json.dumps({"query": "How many?", "seconds": 16, "error": True, "message": BLOCKED}) + "\n",
                    encoding="utf-8")

    Progress(shown, path, 1, "Sales")._drain()

    assert shown.getvalue().splitlines() == ["  … 1/1 failed after 16 s: How many?", f"      {BLOCKED}"]
