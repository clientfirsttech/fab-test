"""Live Data Agent: the real CLI against the deployed agents in DATA_AGENT_WORKSPACE.

The unit tests stub Fabric and promptfoo; this runs ``fab-test`` through its own entry point, as a
person or pipeline would, with the real service principal, the pinned promptfoo and the real agent.

A Data Agent answers agentically: the same question can pass one run and fail the next. So this never
asserts which answers were right (the report shows that). It asserts the tester worked: the run
completed, and every question in the suite came back with a verdict. Exit 1 alone cannot tell, since
wrong answers, a timeout and a promptfoo crash all exit 1, so it reads the envelope.

Opt-in: skips unless DATA_AGENT_WORKSPACE is set, because asking a real agent needs a paid Fabric
capacity that is running. `.github/workflows/data-agent-live.yml` sets it. The whole module asks the
agent once (one module-scoped run): every request counts against the principal's Fabric quota.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from .test_playwright_generation_parity_live import _credentials_present

pytestmark = [pytest.mark.data_agent, pytest.mark.integration]

_WORKSPACE = os.environ.get("DATA_AGENT_WORKSPACE", "")

pytestmark.append(pytest.mark.skipif(
    not (_WORKSPACE and _credentials_present()),
    reason="opt-in: set DATA_AGENT_WORKSPACE and a service principal (FABRIC_TENANT_ID, FABRIC_CLIENT_ID, "
           "FABRIC_CLIENT_SECRET, or .fab-test/.env); asking a real agent needs a running Fabric capacity",
))


def _fab_test(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "fab_test.scripts.fab_test", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def _tail(proc: subprocess.CompletedProcess) -> str:
    return f"exit {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> tuple[subprocess.CompletedProcess, Path]:
    """Ask every deployed agent its suite's questions, once for the whole module."""
    output = tmp_path_factory.mktemp("data-agent-live")
    return _fab_test("data-agent", "--workspace", _WORKSPACE, "--report", "--output-dir", str(output)), output


def test_auth_status_sees_the_workspace():
    proc = _fab_test("auth", "status", "--workspace", _WORKSPACE)
    assert proc.returncode == 0, _tail(proc)


def test_dry_run_lists_the_deployed_agents():
    """Enumeration against the service, without asking anything."""
    proc = _fab_test("data-agent", "--workspace", _WORKSPACE, "--dry-run")
    assert proc.returncode == 0, _tail(proc)
    assert ".DataAgent" in proc.stdout, _tail(proc)


def test_wrong_answers_are_findings_not_a_broken_run(run):
    proc, _output = run
    assert proc.returncode in (0, 1), f"a usage or credential failure, not findings\n{_tail(proc)}"


def test_every_question_comes_back_with_a_verdict(run):
    proc, output = run
    envelopes = sorted(output.rglob("envelope.json"))
    assert envelopes, f"the run never wrote an envelope\n{_tail(proc)}"
    for path in envelopes:
        envelope = json.loads(path.read_text(encoding="utf-8-sig"))
        item = path.parent.name
        assert envelope["status"] in ("passed", "failed"), f"{item} did not complete: {envelope['message']}"
        suite = yaml.safe_load((path.parent / "effective.promptfoo.yaml").read_text(encoding="utf-8"))
        asked, judged = len(suite.get("tests") or []), len(envelope.get("test_results") or [])
        assert asked and judged == asked, f"{item}: {judged} of {asked} questions came back with a verdict"
        assert (path.parent / "report.html").is_file(), f"{item}: --report wrote no report"
