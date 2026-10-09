"""`all --workspace` reports only what it ran, and one failed export fails one item.

Found live (Service Targeting, 2026-10-09): one model whose export crossed
Windows' path limit stopped `bpa` analyzing every other model, and the
aggregate summary then listed the local checkout's fixtures -- items the
service run never touched -- in place of the deployed ones.
"""

import argparse
import base64
import errno
from pathlib import Path

import pytest

from fab_test.scripts import _service_export as svc
from fab_test.scripts._mode import resolve_mode
from fab_test.scripts.fab_test_summary import build_all_summary_rows

WS = "11111111-1111-1111-1111-111111111111"


class FakeClient:
    access_token = "token"

    def __init__(self, names: list[str]) -> None:
        self.items = [{"id": f"id-{name}", "displayName": name} for name in names]

    def list_items(self, workspace_id, item_type):
        return self.items


def _tmdl_parts(self, workspace_id, item_id, *, definition_format=""):
    return [{"path": "definition/model.tmdl", "payload": base64.b64encode(b"model").decode()}]


@pytest.fixture
def service(monkeypatch):
    """Two deployed models; writing the one named "Too Long" fails as Windows would."""
    client = FakeClient(["Sales", "Too Long"])
    monkeypatch.setattr(svc, "build_service_client", lambda args: client)
    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition",
        _tmdl_parts,
    )
    write_parts = svc._write_parts

    def failing_write(parts, root, item_type, display_name):
        if display_name == "Too Long":
            raise OSError(errno.ENAMETOOLONG, "File name too long", str(root / "definition" / "model.tmdl"))
        return write_parts(parts, root, item_type, display_name)

    monkeypatch.setattr(svc, "_write_parts", failing_write)
    return client


def _args(tmp_path: Path, **extra) -> argparse.Namespace:
    ns = argparse.Namespace(
        resolved_target=None,
        workspace_id=WS,
        analyzer=extra.pop("analyzer", "all"),
        artifact_dir=str(tmp_path / "checkout"),
        dry_run=False,
        keep_export=False,
        all_items=False,
        mode="service",
        output_format="text",
        **extra,
    )
    ns.resolved_mode = resolve_mode(None, workspace_flag=WS)
    return ns


def test_given_one_export_failing_should_analyze_the_others_and_fail_the_run(service, tmp_path, capsys):
    args = _args(tmp_path)
    artifacts = svc.export_for_analyzer("bpa", args, tmp_path / "out")
    assert [a.name for a in artifacts] == ["Sales.SemanticModel"]
    out = capsys.readouterr().out
    assert "Too Long.SemanticModel" in out
    assert "too long" in out
    assert svc.service_skip_exit("bpa", args) == 1


def test_given_every_export_failing_should_still_exit_1_naming_the_item(service, tmp_path):
    service.items = [{"id": "id-Too Long", "displayName": "Too Long"}]
    with pytest.raises(svc.ServiceExportError, match=r"Too Long\.SemanticModel") as err:
        svc.export_for_analyzer("bpa", _args(tmp_path), tmp_path / "out")
    assert err.value.code == 1


def test_given_a_service_run_should_name_its_own_items_not_the_checkout(service, tmp_path):
    (tmp_path / "checkout" / "Local Fixture.SemanticModel").mkdir(parents=True)
    args = _args(tmp_path)
    svc.export_for_analyzer("bpa", args, tmp_path / "out")
    envelope = tmp_path / "out" / "bpa" / "Sales" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text('{"status": "warning", "findings": []}', encoding="utf-8")
    rows = build_all_summary_rows(tmp_path / "out", ("bpa",), [1], args)
    status = {row["artifact"]: row["status"] for row in rows}
    # The analyzer exits 1 for Too Long alone; Sales keeps its own envelope's verdict.
    assert status == {"Sales": "warning", "Too Long": "failed"}


def test_given_a_service_dry_run_should_list_the_planned_items(service, tmp_path):
    (tmp_path / "checkout" / "Local Fixture.SemanticModel").mkdir(parents=True)
    args = _args(tmp_path)
    args.dry_run = True
    svc.export_for_analyzer("bpa", args, tmp_path / "out")
    rows = build_all_summary_rows(tmp_path / "out", ("bpa",), [0], args)
    assert sorted(row["artifact"] for row in rows) == ["Sales", "Too Long"]


def test_given_a_local_run_should_still_discover_the_checkout(tmp_path):
    (tmp_path / "checkout" / "Local Fixture.SemanticModel").mkdir(parents=True)
    args = _args(tmp_path)
    args.mode = "local"
    assert svc.service_row_stems("bpa", args) is None
