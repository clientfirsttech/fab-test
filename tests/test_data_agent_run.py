"""Feature-gated CLI discovery and service-only Data Agent execution."""

import argparse
import json

import pytest

from fab_test.scripts._data_agent_run import discover_data_agents, resolve_data_agent_mode
from fab_test.scripts._mode import ModeError
from fab_test.scripts._service_export import ServiceExportError
from fab_test.scripts._target import select_target
from fab_test.scripts.fab_test_parser import build_parser
from fab_test.scripts.fab_test_registry import visible_analyzers

pytestmark = pytest.mark.data_agent


def _args(tmp_path, **overrides):
    return argparse.Namespace(**{
        "resolved_target": None, "workspace_id": "", "file_config": {},
        "artifact_dir": str(tmp_path), "output_dir": str(tmp_path / "results"),
        "dry_run": True, "tests": None, "all_items": False, "playwright_env_file": None,
        **overrides,
    })


def _item(root, name="Sales", identity="stable", display="Deployed Sales"):
    path = root / f"{name}.DataAgent"
    path.mkdir()
    (path / ".platform").write_text(json.dumps({
        "metadata": {"displayName": display}, "config": {"logicalId": identity},
    }), encoding="utf-8")
    return path


def test_disabled_stub_stays_hidden_and_refuses_arbitrary_arguments(monkeypatch):
    monkeypatch.setenv("FAB_TEST_ENABLE_DATA_AGENT", "0")
    assert "data_agent" not in visible_analyzers()
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["agent", "tests", "init", "--format", "json"])
    assert raised.value.code == 2


def test_enabled_by_default_without_the_variable(monkeypatch):
    monkeypatch.delenv("FAB_TEST_ENABLE_DATA_AGENT", raising=False)
    assert "data_agent" in visible_analyzers()
    args = build_parser().parse_args(["data-agent", "tests", "init", "Sales", "--questions"])
    assert (args.authoring_noun, args.action) == ("tests", "init")


def test_enabled_run_alias_and_flags(monkeypatch):
    monkeypatch.setenv("FAB_TEST_ENABLE_DATA_AGENT", "1")
    args = build_parser().parse_args(["agent", "Dev.Workspace/Sales.DataAgent", "--tests", "suite.yaml", "-q"])
    assert args.tests == "suite.yaml"
    assert args.quiet
    assert "data_agent" in visible_analyzers()


@pytest.mark.parametrize("source", ["flag", "env", "config"])
def test_bare_run_is_service_and_records_workspace_source(tmp_path, monkeypatch, source):
    monkeypatch.delenv("FABRIC_WORKSPACE_ID", raising=False)
    args = _args(tmp_path)
    if source == "flag":
        args.workspace_id = "Dev"
    elif source == "env":
        monkeypatch.setenv("FABRIC_WORKSPACE_ID", "Dev")
    else:
        args.file_config = {"workspace": "Dev"}
    mode = resolve_data_agent_mode(args)
    assert (mode.mode, mode.workspace, mode.source) == ("service", "Dev", source)


def test_bare_run_requires_workspace_and_desktop_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("FABRIC_WORKSPACE_ID", raising=False)
    with pytest.raises(ModeError, match="FABRIC_WORKSPACE_ID"):
        resolve_data_agent_mode(_args(tmp_path))
    with pytest.raises(ModeError, match="local"):
        resolve_data_agent_mode(_args(tmp_path, resolved_target=select_target("local/Sales", None)))


def test_dry_run_pairs_by_identity_without_credentials_or_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "Dev")
    item = _item(tmp_path)
    suite = tmp_path / "Renamed.DataAgent.promptfoo.yaml"
    suite.write_text("fabTestDataAgent: stable\ntests: []", encoding="utf-8")
    args = _args(tmp_path)
    assert discover_data_agents(args) == [item]
    assert args.data_agent_suites[item] == suite
    assert args.data_agent_names[item] == "Deployed Sales"


def test_remote_target_requires_explicit_suite(tmp_path):
    args = _args(tmp_path, resolved_target=select_target("Dev.Workspace/Sales.DataAgent", None))
    with pytest.raises(ServiceExportError, match="--tests"):
        discover_data_agents(args)


def test_enumeration_limit_refuses_before_resolving_urls(tmp_path, monkeypatch):
    from fab_test.scripts import _data_agent_run as run

    agents = [{"id": str(i), "displayName": f"Agent{i}"} for i in range(6)]
    monkeypatch.setattr(run, "credential_secret", lambda _env: "test-secret")
    monkeypatch.setattr(run, "build_service_client", lambda _args: object())
    monkeypatch.setattr(run, "list_data_agents", lambda _client, _ws: agents)
    args = _args(tmp_path, workspace_id="00000000-0000-0000-0000-000000000000", dry_run=False)
    with pytest.raises(ServiceExportError, match="--all") as raised:
        discover_data_agents(args)
    assert raised.value.code == 2
    args.all_items = True
    assert len(discover_data_agents(args)) == 6
    assert all(path.suffix == ".DataAgent" for path in args.data_agent_suites)
    assert all(suite is None for suite in args.data_agent_suites.values())


def test_service_target_pairs_local_item_by_display_name(tmp_path):
    item = _item(tmp_path, name="Renamed")
    suite = tmp_path / "Original.DataAgent.promptfoo.yaml"
    suite.write_text("fabTestDataAgent: stable\ntests: []", encoding="utf-8")
    args = _args(tmp_path, resolved_target=select_target("Dev.Workspace/Deployed Sales.DataAgent", None))
    assert discover_data_agents(args) == [item]
    assert args.data_agent_suites[item] == suite


def test_missing_path_is_not_reinterpreted_as_remote_target(tmp_path):
    suite = tmp_path / "suite.yaml"
    suite.write_text("tests: []", encoding="utf-8")
    target = select_target(str(tmp_path / "Missing.DataAgent"), None)
    with pytest.raises(ServiceExportError, match="Check the path"):
        discover_data_agents(_args(tmp_path, resolved_target=target, tests=str(suite), workspace_id="Dev"))
