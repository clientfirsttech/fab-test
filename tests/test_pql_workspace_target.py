"""`pql-test "WS.Workspace/NAME"` runs that deployed model (Service Targeting).

Found live (2026-10-09): a typed or untyped workspace target fell into local
discovery, printed "no *.SemanticModel artifacts found under <cwd>", and
exited 0 -- a pass for a model nobody tested. It now takes the same path as
`pql-test --workspace`, narrowed to the one model the target names.
"""

import argparse

import pytest

from fab_test.scripts import _service_export as svc
from fab_test.scripts._mode import resolve_mode
from fab_test.scripts._target import parse_target

WS = "11111111-1111-1111-1111-111111111111"


class FakeClient:
    access_token = "token"

    def list_items(self, workspace_id, item_type):
        return [{"id": "m1", "displayName": "Sales"}, {"id": "m2", "displayName": "Finance"}]


@pytest.fixture
def fabric(monkeypatch):
    downloads: list[str] = []
    monkeypatch.setattr(svc, "build_service_client", lambda args: FakeClient())
    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition",
        lambda self, workspace_id, item_id, **kwargs: downloads.append(item_id) or [],
    )
    return downloads


def _args(target: str) -> argparse.Namespace:
    resolved = parse_target(target, default_type="SemanticModel")
    ns = argparse.Namespace(
        resolved_target=resolved,
        workspace_id=WS,
        analyzer="pql_test",
        dry_run=False,
        keep_export=False,
        all_items=False,
        mode="service",
        output_format="text",
    )
    ns.resolved_mode = resolve_mode(resolved, workspace_flag="")
    return ns


@pytest.mark.parametrize("target", ["Dev.Workspace/Sales.SemanticModel", "Dev.Workspace/Sales"])
def test_given_a_workspace_target_should_run_only_that_deployed_model(fabric, tmp_path, target):
    args = _args(target)
    assert svc.is_service_run("pql_test", args)
    paths = svc.export_for_analyzer("pql_test", args, tmp_path)
    assert [p.as_posix() for p in paths] == ["Dev.Workspace/Sales.SemanticModel"]
    assert fabric == []  # pql-test reads the live model; nothing is downloaded


def test_given_a_workspace_target_naming_no_model_should_exit_1_naming_it(fabric, tmp_path):
    with pytest.raises(svc.ServiceExportError, match="Missing") as err:
        svc.export_for_analyzer("pql_test", _args("Dev.Workspace/Missing.SemanticModel"), tmp_path)
    assert err.value.code == 1


def test_given_no_target_and_no_workspace_flag_should_keep_the_repository_path():
    args = argparse.Namespace(mode="service", analyzer="pql_test", resolved_target=None)
    assert not svc.is_service_run("pql_test", args)
