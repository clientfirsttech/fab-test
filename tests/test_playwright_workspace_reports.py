"""Contract tests for `fab-test playwright --from-workspace`.

Scope
-----
With no `--artifact`, playwright discovers its targets by scanning
`--artifact-dir` for `*.Report` folders and `.rdl` files, then resolves each
name in the workspace. Playwright reads nothing from those folders, so a run
from outside the repo found nothing, and a run inside it tested names the
workspace did not have. `--from-workspace` lists the Report and
PaginatedReport items from Fabric instead, so a run depends on the workspace
and not on the checkout.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts.fab_test_execution import _discover_for, _run_analyzer
from fab_test.scripts.fab_test_parser import build_parser
from fab_test.scripts.fab_test_registry import build_playwright_command

WORKSPACE = "c4698d28-b05c-40bc-926c-707563ac85e7"

_CLIENT = "fab_test.scripts.playwright_validation.fabric_service_client.build_fabric_service_client"


@pytest.fixture(autouse=True)
def _no_ambient_scope(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "FABRIC_ENVIRONMENT",
        "FABRIC_WORKSPACE_ID",
        "PLAYWRIGHT_WORKSPACE_ID",
        "PLAYWRIGHT_ENV_FILE",
        "GITHUB_WORKSPACE",
    ):
        monkeypatch.delenv(name, raising=False)


def _args(artifact_dir: Path, **overrides) -> argparse.Namespace:
    defaults = {
        "artifact": None,
        "target": None,
        "environment": "",
        "workspace_id": WORKSPACE,
        "dataset_id": "",
        "dataset_workspace_id": "",
        "impact_manifest": None,
        "from_workspace": True,
        "artifact_dir": str(artifact_dir),
        "output_dir": str(artifact_dir / "fab-test-results"),
        "output_format": "text",
        "dry_run": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _client(reports: list[dict], paginated: list[dict]) -> MagicMock:
    client = MagicMock()
    by_type = {"Report": reports, "PaginatedReport": paginated}
    client.list_items.side_effect = lambda _workspace_id, item_type: by_type.get(item_type, [])
    return client


def _item(item_id: str, name: str) -> dict:
    return {"id": item_id, "displayName": name}


def test_flag_is_accepted_on_the_playwright_subcommand() -> None:
    parsed = build_parser().parse_args(["playwright", "--from-workspace", "--workspace-id", WORKSPACE])

    assert parsed.from_workspace is True
    assert build_parser().parse_args(["playwright"]).from_workspace is False


def test_targets_come_from_the_workspace_not_from_local_folders(tmp_path) -> None:
    """A checkout holding names the workspace lacks must not decide the run."""
    (tmp_path / "OnlyLocal.Report").mkdir()
    args = _args(tmp_path)
    client = _client([_item("r1", "Sales")], [_item("p1", "Invoice")])

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert artifacts == [Path("Sales.Report"), Path("Invoice.Report")]


def test_runs_with_no_local_artifacts_at_all(tmp_path) -> None:
    args = _args(tmp_path / "empty-checkout")
    client = _client([_item("r1", "Sales")], [])

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert artifacts == [Path("Sales.Report")]


def test_both_item_types_are_listed_in_the_resolved_workspace(tmp_path) -> None:
    args = _args(tmp_path)
    client = _client([], [])

    with patch(_CLIENT, return_value=client):
        _discover_for("playwright", args, "*.Report")

    listed = {call.args[1] for call in client.list_items.call_args_list}
    assert listed == {"Report", "PaginatedReport"}
    assert all(call.args[0] == WORKSPACE for call in client.list_items.call_args_list)


def test_each_target_forces_its_own_type_and_real_name(tmp_path) -> None:
    """A paginated report must not be auto-detected as an interactive one."""
    args = _args(tmp_path)
    client = _client([_item("r1", "Sales")], [_item("p1", "Invoice")])

    with patch(_CLIENT, return_value=client):
        sales, invoice = _discover_for("playwright", args, "*.Report")

    sales_cmd = build_playwright_command(sales, args, Path(args.output_dir))
    invoice_cmd = build_playwright_command(invoice, args, Path(args.output_dir))

    assert sales_cmd[sales_cmd.index("--artifact") + 1] == "Sales"
    assert sales_cmd[sales_cmd.index("--report-type") + 1] == "report"
    assert invoice_cmd[invoice_cmd.index("--artifact") + 1] == "Invoice"
    assert invoice_cmd[invoice_cmd.index("--report-type") + 1] == "paginated"
    assert invoice_cmd[invoice_cmd.index("--workspace-id") + 1] == WORKSPACE


def test_a_report_and_a_paginated_report_sharing_a_name_both_run(tmp_path) -> None:
    args = _args(tmp_path)
    client = _client([_item("r1", "Sales")], [_item("p1", "Sales")])

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert len({a.stem for a in artifacts}) == 2
    commands = [build_playwright_command(a, args, Path(args.output_dir)) for a in artifacts]
    types = [cmd[cmd.index("--report-type") + 1] for cmd in commands]
    assert types == ["report", "paginated"]


def test_an_empty_workspace_finds_nothing_to_run(tmp_path) -> None:
    args = _args(tmp_path)

    with patch(_CLIENT, return_value=_client([], [])):
        assert _discover_for("playwright", args, "*.Report") == []


def test_no_workspace_refuses_before_any_network_call(tmp_path, capsys) -> None:
    args = _args(tmp_path, workspace_id="")

    with patch(_CLIENT) as build_client:
        assert _run_analyzer("playwright", args, Path(args.output_dir)) == 2

    build_client.assert_not_called()
    assert "--from-workspace" in capsys.readouterr().err


def test_a_named_artifact_keeps_its_own_resolution(tmp_path) -> None:
    """--artifact already resolves remotely; the flag must not widen it."""
    args = _args(tmp_path, artifact="Sales")

    with patch(_CLIENT) as build_client:
        artifacts = _discover_for("playwright", args, "*.Report")

    build_client.assert_not_called()
    assert artifacts == [Path("Sales")]


def test_without_the_flag_local_discovery_is_unchanged(tmp_path) -> None:
    (tmp_path / "Local.Report").mkdir()
    args = _args(tmp_path, from_workspace=False)

    with patch(_CLIENT) as build_client:
        artifacts = _discover_for("playwright", args, "*.Report")

    build_client.assert_not_called()
    assert [a.name for a in artifacts] == ["Local.Report"]
