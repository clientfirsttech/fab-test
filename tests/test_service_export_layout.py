"""Exports fit Windows' 260-character path limit (Service Targeting).

Found live (2026-10-09): `<out>/<analyzer>/<workspace GUID>/<Item>/export/<Item>.Report/...`
reached 262 characters from a 31-character repository root for a report named
"Report with Bookmarks - Broken Visuals". An export is shared by every analyzer
that reads it and a run targets one workspace, so neither needs a folder.
"""

import argparse
import base64
import errno

import pytest

from fab_test.scripts import _service_export as svc
from fab_test.scripts._mode import resolve_mode

WS = "11111111-1111-1111-1111-111111111111"
LONG = "Report with Bookmarks - Broken Visuals"


class FakeClient:
    access_token = "token"

    def __init__(self, items):
        self.items = items

    def list_items(self, workspace_id, item_type):
        return self.items


def _parts(self, workspace_id, item_id, *, definition_format=""):
    return [{"path": "definition/model.tmdl", "payload": base64.b64encode(b"model").decode()}]


@pytest.fixture
def fabric(monkeypatch):
    def install(items):
        monkeypatch.setattr(svc, "build_service_client", lambda args: FakeClient(items))

    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition", _parts
    )
    return install


def _args(**extra) -> argparse.Namespace:
    ns = argparse.Namespace(
        resolved_target=None,
        workspace_id=WS,
        analyzer="bpa",
        dry_run=False,
        keep_export=False,
        all_items=False,
        mode="service",
        output_format="text",
        **extra,
    )
    ns.resolved_mode = resolve_mode(None, workspace_flag=WS)
    return ns


def test_given_an_item_should_export_it_under_export_and_a_short_item_id(fabric, tmp_path):
    fabric([{"id": "0e66f25d-1111-2222-3333-444444444444", "displayName": LONG}])
    [artifact] = svc.export_for_analyzer("bpa", _args(), tmp_path)
    assert artifact.relative_to(tmp_path).parts == ("export", "0e66f25d", f"{LONG}.SemanticModel")


def test_given_two_items_sharing_a_name_should_keep_both(fabric, tmp_path):
    fabric([{"id": "aaaaaaaa-1", "displayName": "Sales"}, {"id": "bbbbbbbb-2", "displayName": "Sales"}])
    artifacts = svc.export_for_analyzer("bpa", _args(), tmp_path)
    assert len(set(artifacts)) == 2


def test_given_a_run_should_leave_no_empty_export_folders_behind(fabric, tmp_path):
    fabric([{"id": "m1", "displayName": "Sales"}])
    args = _args()
    svc.export_for_analyzer("bpa", args, tmp_path / "out")
    svc.finalize_exports(args)
    assert not (tmp_path / "out" / "export").exists()
    assert (tmp_path / "out").exists()


def test_given_a_path_over_the_windows_limit_should_name_the_fix_whatever_the_errno():
    # Windows reports a too-long path as "No such file or directory" when a
    # parent folder could not be created -- the bpa failure found live.
    long_path = "C:\\" + "x" * 260 + "\\model.tmdl"
    error = svc._write_failure(OSError(errno.ENOENT, "No such file or directory", long_path), "Sales.SemanticModel")
    assert "--output-dir" in str(error)
