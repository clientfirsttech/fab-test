"""A paginated report that fails to render says when its workspace has no capacity.

Power BI renders a paginated report only on a capacity (Fabric, Premium or
Premium Per User). In a workspace without one, the embedded report shows
"Query execution failed for dataset ..." and the run recorded only "RDL error
modal detected", which sent a reader to the report and its data rather than to
the workspace's licence. When a paginated case fails that way, fab-test now
checks the workspace once and, when it has no capacity, says so with the fix.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts import invoke_playwright
from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig
from fab_test.scripts.playwright_validation.paginated_capacity import (
    NO_CAPACITY,
    RDL_ERROR,
    capacity_hint,
    explain_paginated_failures,
)
from fab_test.scripts.playwright_validation.phase_timing import PhaseClock
from fab_test.scripts.playwright_validation.service_client import FabricRestClient, FabricToken
from fab_test.scripts.playwright_validation.test_cases import TestCase


def _config(report_type: str) -> PlaywrightValidationConfig:
    return PlaywrightValidationConfig(
        workspace_id="ws-1", report_id="r-1", report_name="Sales", dataset_id="d-1", page_ids=[], bookmark_ids=[],
        user_name="", role="", use_rls=False, cloud="public", client_id="c", client_secret="s", tenant_id="t",
        timeout_seconds=30, headless=True, report_type=report_type)


_PAGINATED, _INTERACTIVE = _config("paginated"), _config("report")


def _row(name: str, status: str, actual: str) -> dict[str, Any]:
    return {"test_name": name, "status": status, "actual": actual}


_ROWS = [_row("Sales", "error", RDL_ERROR), _row("Sales [Region=West]", "pass", "rendered"),
         _row("Sales [Region=East]", "error", "Timed out after 20s")]


def _counting(answer: str):
    calls = []

    def hint(_config) -> str:
        calls.append(1)
        return answer

    return hint, calls


def test_given_an_rdl_error_in_a_workspace_without_a_capacity_should_say_so_on_that_case():
    hint, calls = _counting(NO_CAPACITY)

    rows = explain_paginated_failures(_ROWS, _PAGINATED, hint)

    assert rows[0]["actual"] == f"{RDL_ERROR}: {NO_CAPACITY}"
    assert rows[1:] == _ROWS[1:]                                   # a pass, and a failure of another kind
    assert len(calls) == 1                                         # one lookup for the whole run


@pytest.mark.parametrize("rows, config", [([_row("Sales", "pass", "rendered")], _PAGINATED),
                                          (_ROWS, _INTERACTIVE)])
def test_given_no_rdl_error_or_an_interactive_report_should_not_look_up_the_workspace(rows, config):
    hint, calls = _counting(NO_CAPACITY)

    assert explain_paginated_failures(rows, config, hint) == rows
    assert not calls


def test_given_a_workspace_on_a_capacity_should_leave_the_error_as_it_was():
    hint, _calls = _counting("")

    assert explain_paginated_failures(_ROWS, _PAGINATED, hint) == _ROWS


@pytest.mark.parametrize("on_capacity, expected", [(False, NO_CAPACITY), (True, ""), (None, "")])
def test_given_the_workspaces_capacity_should_hint_only_when_it_has_none(on_capacity, expected):
    assert capacity_hint(_PAGINATED, lambda _config: on_capacity) == expected


def test_given_a_lookup_that_fails_should_add_nothing_rather_than_fail_the_run():
    def broken(_config):
        raise RuntimeError("no network")

    assert capacity_hint(_PAGINATED, broken) == ""


@pytest.mark.parametrize("body, expected", [({"isOnDedicatedCapacity": False}, False),
                                            ({"isOnDedicatedCapacity": True, "capacityId": "c"}, True),
                                            ({"name": "Sales"}, None)])
def test_given_a_workspace_should_read_whether_it_is_on_a_capacity(body, expected):
    response = MagicMock(status_code=200, text=str(body))
    response.json.return_value = body

    with patch("fab_test.scripts.playwright_validation.service_client.requests.request",
               return_value=response) as request:
        assert FabricRestClient(FabricToken(access_token="t")).workspace_on_capacity("ws-1") is expected

    assert request.call_args.args[1].endswith("/v1.0/myorg/groups/ws-1")


def test_given_a_finished_run_should_put_the_hint_in_the_envelope(tmp_path: Path, monkeypatch):
    case = TestCase(test_case="Sales", report_name="Sales", report_id="r-1", workspace_id="ws-1", page_id="",
                    page_name="", bookmark_id="", bookmark_name="", dataset_id="d-1", user_name="", role="",
                    report_type="paginated")
    cases_dir = tmp_path / "test-cases"
    (cases_dir / "Sales").mkdir(parents=True)
    (cases_dir / "Sales" / "result.json").write_text(json.dumps({"status": "error", "error": RDL_ERROR}),
                                                     encoding="utf-8")
    monkeypatch.setattr("fab_test.scripts.playwright_validation.paginated_capacity.capacity_hint",
                        lambda _config: NO_CAPACITY)
    envelope = tmp_path / "envelope.json"

    code = invoke_playwright._finish_report(
        subprocess.CompletedProcess([], 1, stdout=""), None, [case], cases_dir, _PAGINATED, PhaseClock(),
        argparse.Namespace(), ("Sales", envelope))

    written = json.loads(envelope.read_text(encoding="utf-8"))
    assert code == 1
    assert written["test_results"][0]["actual"] == f"{RDL_ERROR}: {NO_CAPACITY}"
    assert written["findings"][0]["message"] == f"{RDL_ERROR}: {NO_CAPACITY}"
