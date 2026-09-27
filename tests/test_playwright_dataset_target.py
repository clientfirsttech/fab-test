"""Contract tests for `fab-test playwright --dataset-id` with no report named.

Scope
-----
`fab-test playwright --dataset-id X --dataset-workspace-id Y` with no
`--artifact` used to fall straight into batch discovery: every local
`*.Report`/`.rdl` under `--artifact-dir` ran against the configured
environment, each one force-rebound to dataset X. Naming a dataset without
naming a report now means "the reports built on this dataset", resolved live
through the dependents lookup (Playwright Dataset Target epic).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fab_test.scripts._playwright_dataset_target import dataset_target_requested
from fab_test.scripts.fab_test_execution import _discover_for, _run_analyzer
from fab_test.scripts.fab_test_registry import build_playwright_command

DATASET_ID = "5bf5a7e1-65e5-4d74-944b-1ada5941a664"
DATASET_WS = "c4698d28-b05c-40bc-926c-707563ac85e7"
REPORT_WS = "798dfd00-0000-4000-8000-000000000000"

_CLIENT = "fab_test.scripts.playwright_validation.fabric_service_client.build_fabric_service_client"


@pytest.fixture(autouse=True)
def _no_ambient_scope(monkeypatch, tmp_path):
    # The report workspace also falls back to PLAYWRIGHT_WORKSPACE_ID in a
    # default-located .env, so a developer's own .fab-test/.env must not leak in.
    monkeypatch.chdir(tmp_path)
    for name in (
        "FABRIC_ENVIRONMENT",
        "FABRIC_WORKSPACE_ID",
        "PLAYWRIGHT_WORKSPACE_ID",
        "PLAYWRIGHT_ENV_FILE",
        "GITHUB_WORKSPACE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def local_reports(tmp_path: Path) -> Path:
    """Two local reports that batch discovery would otherwise pick up."""
    (tmp_path / "Sales.Report").mkdir()
    (tmp_path / "Unrelated.Report").mkdir()
    return tmp_path


def _args(artifact_dir: Path, **overrides) -> argparse.Namespace:
    defaults = {
        "artifact": None,
        "target": None,
        "environment": "",
        "workspace_id": "",
        "dataset_id": DATASET_ID,
        "dataset_workspace_id": DATASET_WS,
        "impact_manifest": None,
        "artifact_dir": str(artifact_dir),
        "output_dir": str(artifact_dir / "fab-test-results"),
        "output_format": "text",
        "dry_run": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _client(dependents_by_workspace: dict[str, list[dict]]) -> MagicMock:
    client = MagicMock()
    client.get_dependent_reports.side_effect = lambda workspace_id, _dataset_id: dependents_by_workspace.get(
        workspace_id, []
    )
    return client


def _dep(report_id: str, name: str, workspace_id: str) -> dict:
    return {"id": report_id, "displayName": name, "type": "Report", "workspaceId": workspace_id}


def test_dataset_id_runs_dependents_instead_of_every_local_report(local_reports) -> None:
    """The reported bug: only the dataset's dependents run, not the local batch."""
    args = _args(local_reports)
    client = _client({DATASET_WS: [_dep("r1", "Sales", DATASET_WS)]})

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert artifacts == [Path("Sales.Report")]
    client.get_dependent_reports.assert_called_once_with(DATASET_WS, DATASET_ID)


def test_dependents_are_looked_up_in_the_dataset_and_report_workspaces(local_reports) -> None:
    """A report in the report workspace bound to the dataset is found too, once."""
    args = _args(local_reports, workspace_id=REPORT_WS)
    client = _client(
        {
            DATASET_WS: [_dep("r1", "Sales", DATASET_WS)],
            REPORT_WS: [_dep("r2", "Sales Dev", REPORT_WS), _dep("r1", "Sales", DATASET_WS)],
        }
    )

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert artifacts == [Path("Sales.Report"), Path("Sales Dev.Report")]


def test_without_a_dataset_workspace_the_report_workspace_is_searched(local_reports, monkeypatch) -> None:
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", REPORT_WS)
    args = _args(local_reports, dataset_workspace_id="")
    client = _client({REPORT_WS: [_dep("r2", "Sales Dev", REPORT_WS)]})

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert artifacts == [Path("Sales Dev.Report")]


def test_no_workspace_at_all_refuses_before_any_network_call(local_reports, capsys) -> None:
    args = _args(local_reports, dataset_workspace_id="")

    with patch(_CLIENT) as build_client:
        assert _run_analyzer("playwright", args, Path(args.output_dir)) == 2

    build_client.assert_not_called()
    err = capsys.readouterr().err
    assert "--dataset-workspace-id" in err
    assert "--workspace-id" in err


def test_no_dependents_exits_zero_with_a_notice(local_reports, capsys) -> None:
    args = _args(local_reports)

    with patch(_CLIENT, return_value=_client({})):
        assert _run_analyzer("playwright", args, Path(args.output_dir)) == 0

    assert DATASET_ID in capsys.readouterr().out


def test_no_dependents_under_format_json_emits_exactly_one_json_object(local_reports, capsys) -> None:
    """`fab-test all --format json` parses stdout as one document; a second,
    unrelated JSON object printed for the empty-dependents case would break that."""
    import json

    args = _args(local_reports, output_format="json")

    with patch(_CLIENT, return_value=_client({})):
        assert _run_analyzer("playwright", args, Path(args.output_dir)) == 0

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)  # raises if more than one JSON value was printed
    assert payload["artifacts"] == []


def test_dependent_report_command_carries_its_workspace_and_the_dataset(local_reports) -> None:
    """Each dependent renders in its own workspace, embedded against the named dataset."""
    args = _args(local_reports, workspace_id=REPORT_WS)
    client = _client({DATASET_WS: [_dep("r1", "Sales", DATASET_WS)]})
    with patch(_CLIENT, return_value=client):
        (artifact,) = _discover_for("playwright", args, "*.Report")

    cmd = build_playwright_command(artifact, args, Path(args.output_dir))

    def flag(name: str) -> str:
        return cmd[cmd.index(name) + 1]

    assert flag("--artifact") == "Sales"
    assert flag("--workspace-id") == DATASET_WS
    assert flag("--dataset-id") == DATASET_ID
    assert flag("--dataset-workspace-id") == DATASET_WS
    assert flag("--report-type") == "report"


def test_dataset_id_with_an_artifact_keeps_the_binding_override(local_reports) -> None:
    """Naming a report keeps today's meaning: override that report's dataset."""
    args = _args(local_reports, artifact="Sales")
    assert not dataset_target_requested(args)

    with patch(_CLIENT) as build_client:
        artifacts = _discover_for("playwright", args, "*.Report")

    assert [a.name for a in artifacts] == ["Sales.Report"]
    build_client.assert_not_called()


def test_impact_manifest_is_not_a_dataset_target(local_reports) -> None:
    assert not dataset_target_requested(_args(local_reports, impact_manifest="m.json"))


def test_two_reports_sharing_name_and_workspace_both_survive(local_reports) -> None:
    """Fabric doesn't forbid two items sharing a name in one workspace either;
    the report ID is the last-resort disambiguator."""
    args = _args(local_reports)
    client = _client({DATASET_WS: [_dep("r1", "Sales", DATASET_WS), _dep("r2", "Sales", DATASET_WS)]})

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert len(artifacts) == 2
    assert len({a.stem for a in artifacts}) == 2


def test_two_dependents_sharing_a_display_name_both_survive(local_reports) -> None:
    """Different report IDs, different workspaces, same display name: neither
    is dropped, and each still resolves against its own real name/workspace."""
    other_ws = "11111111-2222-4333-8444-555555555555"
    args = _args(local_reports, workspace_id=other_ws)
    client = _client(
        {
            DATASET_WS: [_dep("r1", "Sales", DATASET_WS)],
            other_ws: [_dep("r2", "Sales", other_ws), _dep("r1", "Sales", DATASET_WS)],
        }
    )

    with patch(_CLIENT, return_value=client):
        artifacts = _discover_for("playwright", args, "*.Report")

    assert len(artifacts) == 2
    assert len({a.stem for a in artifacts}) == 2  # distinct stems, nothing dropped

    commands = {a.stem: build_playwright_command(a, args, Path(args.output_dir)) for a in artifacts}
    workspaces = {cmd[cmd.index("--workspace-id") + 1] for cmd in commands.values()}
    assert workspaces == {DATASET_WS, other_ws}
    for cmd in commands.values():
        assert cmd[cmd.index("--artifact") + 1] == "Sales"


def test_dataset_workspace_alone_refuses_before_any_local_report_runs(local_reports, capsys) -> None:
    """The reported bug: --dataset-workspace-id with no --dataset-id used to
    force every locally discovered report onto that (commonly inaccessible)
    workspace instead of refusing."""
    args = _args(local_reports, dataset_id="")

    with patch(_CLIENT) as build_client:
        assert _run_analyzer("playwright", args, Path(args.output_dir)) == 2

    build_client.assert_not_called()
    err = capsys.readouterr().err
    assert "--dataset-workspace-id" in err
    assert "--dataset-id" in err


def test_dataset_workspace_alone_with_an_artifact_keeps_the_binding_override(local_reports) -> None:
    """A single --artifact run may legitimately point only the workspace half
    of an auto-detected dataset elsewhere; unaffected by the batch refusal."""
    args = _args(local_reports, dataset_id="", artifact="Sales")

    with patch(_CLIENT) as build_client:
        artifacts = _discover_for("playwright", args, "*.Report")

    assert [a.name for a in artifacts] == ["Sales.Report"]
    build_client.assert_not_called()


def test_dataset_workspace_alone_with_an_impact_manifest_keeps_todays_behavior(local_reports) -> None:
    args = _args(local_reports, dataset_id="", impact_manifest="m.json")

    with patch(_CLIENT) as build_client:
        artifacts = _discover_for("playwright", args, "*.Report")

    assert artifacts == [Path(".")]
    build_client.assert_not_called()
