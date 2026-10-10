"""tools/deploy_rdl_fixtures.py: a fixture is committed only as the Fabric
service returns it, and near-misses don't stay in the workspace (RDL Rule
Coverage epic, Reproducible fixtures). Runs against an in-memory workspace."""

import base64
import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent


def _load_tool():
    spec = importlib.util.spec_from_file_location("deploy_rdl_fixtures", _REPO / "tools" / "deploy_rdl_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TOOL = _load_tool()
_WS = "ws-1"


class FakeWorkspace:
    """Fabric's items API for one workspace, held in memory."""

    def __init__(self, *, reject=(), rewrite=()):
        self.items: dict[str, dict] = {}
        self.reject, self.rewrite = set(reject), set(rewrite)
        self.deleted: list[str] = []

    def call(self, method: str, path: str, body: dict | None = None):
        base = f"/workspaces/{_WS}/items"
        if method == "GET" and path == f"{base}?type=PaginatedReport":
            return {"value": [{"id": i, "displayName": item["name"]} for i, item in self.items.items()]}
        if method == "POST" and path == base:
            return self._store(f"id-{len(self.items)}", body["displayName"], body["definition"])
        item_id, _, action = path.removeprefix(base + "/").partition("/")
        if method == "POST" and action == "updateDefinition":
            return self._store(item_id, self.items[item_id]["name"], body["definition"])
        if method == "POST" and action == "getDefinition":
            item = self.items[item_id]
            parts = [(f"{item['name']}.rdl", item["rdl"]), (".platform", b'{"metadata": {}}')]
            return {"definition": {"parts": [{"path": p, "payload": base64.b64encode(b).decode()} for p, b in parts]}}
        if method == "DELETE":
            self.deleted.append(self.items.pop(item_id)["name"])
            return None
        raise AssertionError(f"unexpected call {method} {path}")

    def _store(self, item_id, name, definition):
        if name in self.reject:
            raise _TOOL.DeployError(f"HTTP 400 for {name}")
        rdl = base64.b64decode(definition["parts"][0]["payload"])
        self.items[item_id] = {"name": name, "rdl": rdl + b"<!-- rewritten -->" if name in self.rewrite else rdl}
        return {"id": item_id}


def _fixture(root: Path, name: str, content: bytes = b"<Report />") -> Path:
    path = root / f"{name}.PaginatedReport" / f"{name}.rdl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestRoundTrip:
    def test_a_new_fixture_is_created_kept_and_given_its_platform(self, tmp_path):
        _fixture(tmp_path, "LAY-01")
        fabric = FakeWorkspace()

        code = _TOOL.round_trip(["LAY-01"], tmp_path, _WS, fabric.call)

        assert code == 0
        assert (tmp_path / "LAY-01.PaginatedReport" / ".platform").exists()
        assert [item["name"] for item in fabric.items.values()] == ["LAY-01"]

    def test_a_near_miss_is_removed_from_the_workspace_afterwards(self, tmp_path):
        _fixture(tmp_path, "LAY-01-Pass")
        fabric = FakeWorkspace()

        assert _TOOL.round_trip(["LAY-01-Pass"], tmp_path, _WS, fabric.call) == 0
        assert fabric.items == {} and fabric.deleted == ["LAY-01-Pass"]
        assert (tmp_path / "LAY-01-Pass.PaginatedReport" / ".platform").exists()

    def test_an_existing_item_is_updated_not_duplicated(self, tmp_path):
        _fixture(tmp_path, "LAY-01", b"<Report>v2</Report>")
        fabric = FakeWorkspace()
        fabric.items["id-9"] = {"name": "LAY-01", "rdl": b"<Report>v1</Report>"}

        assert _TOOL.round_trip(["LAY-01"], tmp_path, _WS, fabric.call) == 0
        assert fabric.items == {"id-9": {"name": "LAY-01", "rdl": b"<Report>v2</Report>"}}

    def test_a_rejected_fixture_fails_the_run_but_the_rest_still_deploy(self, tmp_path):
        _fixture(tmp_path, "PRM-04")
        _fixture(tmp_path, "LAY-01")
        fabric = FakeWorkspace(reject={"PRM-04"})

        assert _TOOL.round_trip(["PRM-04", "LAY-01"], tmp_path, _WS, fabric.call) == 1
        assert not (tmp_path / "PRM-04.PaginatedReport" / ".platform").exists()
        assert (tmp_path / "LAY-01.PaginatedReport" / ".platform").exists()

    def test_a_fixture_the_service_changes_is_not_committed(self, tmp_path):
        path = _fixture(tmp_path, "LAY-01")
        fabric = FakeWorkspace(rewrite={"LAY-01"})

        assert _TOOL.round_trip(["LAY-01"], tmp_path, _WS, fabric.call) == 1
        assert path.read_bytes() == b"<Report />"
        assert not (tmp_path / "LAY-01.PaginatedReport" / ".platform").exists()


def test_an_unknown_fixture_exits_2_before_signing_in(tmp_path, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("signed in before checking the fixture names")

    monkeypatch.setattr(_TOOL, "build_fabric_service_client", no_network)

    assert _TOOL.main(["--workspace", "fab-test [Dev]", "--artifact-dir", str(tmp_path), "NOPE-01"]) == 2
