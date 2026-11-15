"""Pairing slicer contracts with reports (PBIR Slicer Default State epic, Contract To JSON Logic).

In-process and tool-free: which contract a report gets, and what happens to
its ruleset. `test_slicer_rules_live.py` covers the same path end to end.
"""

import argparse
import datetime
import json
from pathlib import Path

import pytest
import yaml

from fab_test.scripts._slicer_contract_run import apply_slicer_contract, prepare_contracts

LOGICAL_ID = "3a4f0bd3-6174-4bb8-a99c-175836b6b9eb"


def _contract(logical_id=LOGICAL_ID, selected=("Bad",), engine="fab-test"):
    rule = {"id": "r1", "type": "custom", "engine": engine,
            "implementation": {"page": "Overview", "selected": list(selected)}}
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "id": "c", "version": "1", "status": "active",
            "customProperties": [{"property": "fabTestReport", "value": logical_id}],
            "schema": [{"name": "T", "properties": [{"name": "C", "quality": [rule]}]}]}


def _write(path: Path, document) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document) if not isinstance(document, str) else document, encoding="utf-8")
    return path


def _report(root: Path, logical_id=LOGICAL_ID) -> Path:
    report = root / "Sales.Report"
    _write(report / ".platform", json.dumps({"config": {"logicalId": logical_id}}))
    return report


def _args(root: Path, analyzer="pbir", **extra) -> argparse.Namespace:
    settings = {"analyzer": analyzer, "artifact_dir": str(root), "output_dir": str(root / "out"),
                "as_of": datetime.date(2026, 11, 14), "contract": None}
    return argparse.Namespace(**{**settings, **extra})


def _base_rules(root: Path) -> Path:
    return _write(root / "base.json", json.dumps({"rules": [{"id": "PACKAGED"}]}))


@pytest.mark.pbir
def test_given_a_paired_contract_should_append_its_rules_to_that_reports_own_ruleset(tmp_path):
    report = _report(tmp_path)
    _write(tmp_path / "Sales.Report.odcs.yaml", _contract())
    args = _args(tmp_path)

    assert prepare_contracts(args) is None
    rules_path, summary = apply_slicer_contract(report, args, tmp_path / "out", _base_rules(tmp_path))

    ids = [r["id"] for r in json.loads(rules_path.read_text(encoding="utf-8"))["rules"]]
    assert ids[0] == "PACKAGED" and "CONTRACT.r1" in ids
    assert rules_path.parent == tmp_path / "out" / "pbir" / "Sales"
    assert json.loads(summary.read_text(encoding="utf-8"))["as_of"] == "2026-11-14"


@pytest.mark.pbir
def test_given_a_report_with_another_logical_id_should_leave_its_ruleset_alone(tmp_path):
    report = _report(tmp_path, logical_id="00000000-0000-0000-0000-000000000000")
    _write(tmp_path / "Sales.Report.odcs.yaml", _contract())
    args = _args(tmp_path)
    prepare_contracts(args)
    base = _base_rules(tmp_path)

    assert apply_slicer_contract(report, args, tmp_path / "out", base) == (base, None)


@pytest.mark.pbir
def test_given_an_explicit_contract_should_apply_it_whatever_the_logical_id(tmp_path):
    report = _report(tmp_path, logical_id="00000000-0000-0000-0000-000000000000")
    explicit = _write(tmp_path / "elsewhere" / "contract.yaml", _contract())
    args = _args(tmp_path / "empty", contract=str(explicit))
    (tmp_path / "empty").mkdir()

    prepare_contracts(args)
    _rules_path, summary = apply_slicer_contract(report, args, tmp_path / "out", _base_rules(tmp_path))

    assert summary is not None


@pytest.mark.pbir
def test_given_a_pql_test_only_contract_should_not_read_it(tmp_path):
    _write(tmp_path / "Model.odcs.yaml", {"apiVersion": "v3.1.0", "schema": [
        {"name": "T", "properties": [{"name": "C", "quality": [{"type": "custom", "engine": "pql-test"}]}]}]})
    args = _args(tmp_path)

    assert prepare_contracts(args) is None
    assert args.slicer_contracts == {}


@pytest.mark.pbir
@pytest.mark.parametrize("files, message", [
    ({"a.odcs.yaml": _contract(), "b.odcs.yaml": _contract()}, "both pair with report"),
    ({"a.odcs.yaml": _contract(selected=["{nope}"])}, "'nope'"),
    ({"a.odcs.yaml": "engine: fab-test schema: [unclosed"}, "a.odcs.yaml"),
])
def test_given_a_contract_problem_should_exit_2_naming_it(tmp_path, capsys, files, message):
    for name, document in files.items():
        _write(tmp_path / name, document)

    assert prepare_contracts(_args(tmp_path)) == 2
    assert message in capsys.readouterr().err


@pytest.mark.pbir
def test_given_an_analyzer_that_never_runs_pbir_should_not_read_contracts(tmp_path):
    _write(tmp_path / "a.odcs.yaml", "schema: [unclosed")

    assert prepare_contracts(_args(tmp_path, analyzer="bpa")) is None


@pytest.mark.pbir
def test_given_broken_yaml_with_no_fab_test_rules_should_warn_and_skip_it(tmp_path, capsys):
    _write(tmp_path / "Model.odcs.yaml", "schema: [unclosed")
    args = _args(tmp_path)

    assert prepare_contracts(args) is None
    assert args.slicer_contracts == {} and "skipped" in capsys.readouterr().err
