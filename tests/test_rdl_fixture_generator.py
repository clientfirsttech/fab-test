"""tools/generate_rdl_fixtures.py reproduces every generated RDL fixture byte
for byte, so a fixture can always be rebuilt from DS-02.rdl and its one edit
(RDL Rule Coverage epic, Reproducible fixtures)."""

import importlib.util
import json
from pathlib import Path
from uuid import UUID

import pytest

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent
_ARTIFACTS = _REPO / "fabric-artifacts"

# Report Builder files made by hand before the generator existed; DS-02.rdl is
# also the generator's base.
_HAND_BUILT = {"ACC-03", "DS-02", "DS-05", "DS-07", "QRY-01", "QRY-02", "QRY-04", "STR-01"}


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_rdl_fixtures", _REPO / "tools" / "generate_rdl_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_GENERATOR = _load_generator()
_GENERATED = _GENERATOR.fixtures()


@pytest.mark.parametrize("name", sorted(_GENERATED))
def test_regenerates_the_committed_fixture_byte_for_byte(name):
    committed = _ARTIFACTS / f"{name}.PaginatedReport" / f"{name}.rdl"

    assert _GENERATED[name] == committed.read_bytes(), f"{name} drifted: run python tools/generate_rdl_fixtures.py"


def test_every_committed_fixture_is_generated_or_hand_built():
    committed = {p.stem for p in _ARTIFACTS.glob("*.PaginatedReport/*.rdl")}
    rule_fixtures = {name for name in committed if name.removesuffix("-Pass") in _GENERATOR.active_rule_ids()}

    assert rule_fixtures == set(_GENERATED) | _HAND_BUILT


def test_paginated_reports_have_unique_nonzero_git_identities():
    identities = {}
    for folder in sorted(_ARTIFACTS.glob("*.PaginatedReport")):
        platform = json.loads((folder / ".platform").read_text(encoding="utf-8-sig"))
        logical_id = UUID(platform["config"]["logicalId"])
        assert logical_id.int != 0, f"{folder.name}: Git integration needs a nonzero logicalId"
        assert logical_id not in identities, (
            f"{folder.name} and {identities[logical_id]} share logicalId {logical_id}"
        )
        identities[logical_id] = folder.name
    assert identities, "No paginated report Git identities were checked"


def test_check_mode_passes_on_the_committed_tree(capsys):
    assert _GENERATOR.main(["--check"]) == 0


def test_check_mode_names_a_drifted_fixture(tmp_path, capsys):
    name = sorted(_GENERATED)[0]
    (tmp_path / f"{name}.PaginatedReport").mkdir()
    (tmp_path / f"{name}.PaginatedReport" / f"{name}.rdl").write_bytes(b"drifted")

    assert _GENERATOR.main(["--check", "--artifact-dir", str(tmp_path), name]) == 1
    assert name in capsys.readouterr().out
