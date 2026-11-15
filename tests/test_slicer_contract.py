"""Contract Format (PBIR Slicer Default State epic): reading a slicer contract.

A contract is an ODCS v3 document whose `type: custom`, `engine: fab-test`
quality rules state what a report's slicers open with. These tests cover
reading and validating it; compiling it to JSON Logic is a later task.

    pytest tests/test_slicer_contract.py
"""

import datetime
from pathlib import Path

import pytest
import yaml

from fab_test.scripts._slicer_contract import (
    CHECKS,
    ContractError,
    dax_literal,
    load_contract,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report.odcs.yaml"


def _rule(**implementation):
    return {"id": "r1", "type": "custom", "engine": "fab-test",
            "implementation": {"page": "Overview", **implementation}}


def _contract(*quality, table="Date", column="Semester", **envelope):
    return {
        "apiVersion": "v3.1.0", "kind": "DataContract", "id": "c", "version": "1.0.0", "status": "active",
        "customProperties": [{"property": "fabTestReport", "value": "3a4f0bd3-6174-4bb8-a99c-175836b6b9eb"}],
        "schema": [{"name": table, "properties": [{"name": column, "quality": list(quality)}]}],
        **envelope,
    }


def _load(tmp_path, document):
    path = tmp_path / "x.odcs.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return load_contract(path)


def _errors(tmp_path, document):
    with pytest.raises(ContractError) as caught:
        _load(tmp_path, document)
    return str(caught.value)


@pytest.mark.pbir
def test_given_a_rule_should_identify_its_slicer_by_page_and_bound_field(tmp_path):
    contract = _load(tmp_path, _contract(_rule(selected=["FY27-S1"])))

    [expectation] = contract.expectations
    assert (expectation.rule_id, expectation.page, expectation.table, expectation.column) == (
        "r1", "Overview", "Date", "Semester")
    assert (expectation.check, expectation.expected) == ("selected", ["FY27-S1"])
    assert contract.report_logical_id == "3a4f0bd3-6174-4bb8-a99c-175836b6b9eb"


@pytest.mark.pbir
def test_given_rules_for_another_engine_should_ignore_them(tmp_path):
    pql_rule = {"type": "custom", "engine": "pql-test", "implementation": {"expression": "1", "mustBe": 1}}

    contract = _load(tmp_path, _contract(pql_rule, {"type": "library", "metric": "nullValues", "mustBe": 0}))

    assert contract.expectations == []


@pytest.mark.pbir
def test_given_no_severity_should_default_to_error_and_accept_warning(tmp_path):
    contract = _load(tmp_path, _contract(_rule(selected=[]), {**_rule(selected=[]), "id": "r2", "severity": "warning"}))

    assert [e.severity for e in contract.expectations] == ["error", "warning"]


@pytest.mark.pbir
def test_given_a_visual_id_should_refuse_it_and_name_its_path(tmp_path):
    message = _errors(tmp_path, _contract(_rule(selected=["x"], visual="ce885ceced4291ade64c")))

    assert "schema[0].properties[0].quality[0].implementation.visual" in message


@pytest.mark.pbir
def test_given_every_kind_of_mistake_should_report_all_of_them_with_paths(tmp_path):
    document = _contract(
        {**_rule(selected=["x"], contains=["y"]), "severity": "fatal"},
        {"type": "custom", "engine": "fab-test", "implementation": {"selected": "x"}},
        kind="Contract",
    )
    del document["status"]

    message = _errors(tmp_path, document)

    for path in ("kind", "status",
                 "schema[0].properties[0].quality[0].implementation",
                 "schema[0].properties[0].quality[0].severity",
                 "schema[0].properties[0].quality[1].id",
                 "schema[0].properties[0].quality[1].implementation.page",
                 "schema[0].properties[0].quality[1].implementation.selected"):
        assert f"{path}:" in message, path


@pytest.mark.pbir
def test_given_no_report_pairing_should_name_the_custom_property(tmp_path):
    document = _contract(_rule(selected=["x"]))
    document["customProperties"] = []

    assert "customProperties.fabTestReport" in _errors(tmp_path, document)


@pytest.mark.pbir
@pytest.mark.parametrize("implementation, path", [
    ({"range": {"from": "soon"}}, "implementation.range.from"),
    ({"range": {}}, "implementation.range"),
    ({"relative": {"range": "Last", "duration": 0, "period": "Months"}}, "implementation.relative.duration"),
    ({"relative": {"range": "Previous", "duration": 2, "period": "Months"}}, "implementation.relative.range"),
    ({"contains": [""]}, "implementation.contains"),
    ({"selected": [["nested"]]}, "implementation.selected"),
    ({"range": {"from": datetime.date(2026, 2, 1), "to": datetime.date(2026, 1, 1)}}, "implementation.range"),
])
def test_given_a_malformed_check_should_name_the_offending_key(tmp_path, implementation, path):
    assert path in _errors(tmp_path, _contract(_rule(**implementation)))


@pytest.mark.pbir
@pytest.mark.parametrize("value, literal", [
    ("Bad", "'Bad'"),
    ("O'Neil", "'O''Neil'"),
    ("'MarvelFact'[Number of Characters]", "'''MarvelFact''[Number of Characters]'"),
    (1940, "1940L"),
    (2.5, "2.5D"),
    (True, "true"),
    (3.0, "3D"),
    (1e16, "10000000000000000D"),
    (1e-05, "0.00001D"),
    (None, "null"),
    (datetime.date(2026, 10, 28), "datetime'2026-10-28T00:00:00'"),
])
def test_given_a_value_as_the_user_sees_it_should_encode_the_dax_literal_desktop_writes(value, literal):
    assert dax_literal(value) == literal


@pytest.mark.pbir
def test_given_the_test_bed_contract_should_load_one_expectation_per_example_slicer():
    contract = load_contract(EXAMPLE)

    pages = {e.page for e in contract.expectations}
    assert len(contract.expectations) == 10
    assert pages == {"Standard Slicers", "Date Between", "Date Relative", "Date Picker", "Input Slicer"}
    assert {e.check for e in contract.expectations} == set(CHECKS)


@pytest.mark.pbir
def test_given_duplicate_or_reserved_ids_should_refuse_them(tmp_path):
    message = _errors(tmp_path, _contract(_rule(selected=["a"]), _rule(selected=["b"]),
                                          {**_rule(selected=["c"]), "id": "page.Overview"}))

    assert "'r1': used by more than one rule" in message
    assert "'page.Overview'" in message and "reserved" in message


@pytest.mark.pbir
def test_given_a_fab_test_rule_that_isnt_type_custom_should_say_so_instead_of_skipping_it(tmp_path):
    message = _errors(tmp_path, _contract({**_rule(selected=["x"]), "type": "Custom"}))

    assert "schema[0].properties[0].quality[0].type" in message


@pytest.mark.pbir
def test_given_nodes_that_arent_mappings_should_report_their_paths_not_crash(tmp_path):
    document = _contract(_rule(selected=["x"]))
    document["schema"].append("Sales")
    document["schema"][0]["properties"].append(None)
    document["schema"][0]["properties"][0]["quality"].append(7)

    message = _errors(tmp_path, document)

    for path in ("schema[1]:", "schema[0].properties[1]:", "schema[0].properties[0].quality[1]:"):
        assert path in message


@pytest.mark.pbir
def test_given_an_empty_input_slicer_should_accept_contains_nothing(tmp_path):
    [expectation] = _load(tmp_path, _contract(_rule(contains=[]))).expectations

    assert expectation.expected == []
