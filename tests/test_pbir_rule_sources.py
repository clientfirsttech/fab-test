"""Telling a report's PBIR rules from its slicer contract's (PBIR Slicer Default State epic).

A run checks two rule sets: the packaged (or --rules) PBIR rules every report
gets, and the `CONTRACT.*` rules compiled from the report's own contract. The
run says which contract paired (or why none did), splits its counts by
source, and tags every envelope row with `source`.
"""

import json
from pathlib import Path

import pytest

from fab_test.scripts._pbir_rule_sources import contract_line, count_line, source_of, tag_sources

LOGICAL_ID = "b3cba6e7-ddfc-4bcd-b4b1-5f2a3d5297fc"


def _report(tmp_path: Path, logical_id: str | None = LOGICAL_ID) -> Path:
    report = tmp_path / "Sales.Report"
    report.mkdir()
    if logical_id:
        (report / ".platform").write_text(json.dumps({"config": {"logicalId": logical_id}}), encoding="utf-8")
    return report


def _summary(tmp_path: Path, rules: int, navigators: int) -> Path:
    path = tmp_path / "_contract.json"
    path.write_text(json.dumps({"file": "contracts/Sales.Report.odcs.yaml", "rules": [{}] * rules,
                                "navigators": [{}] * navigators}), encoding="utf-8")
    return path


@pytest.mark.pbir
@pytest.mark.parametrize("rule, source", [("CONTRACT.half-year-current", "contract"),
                                          ("CONTRACT.page.Standard Slicers", "contract"),
                                          ("SHOW_VISUAL_HEADER", "rules"), ("contract-like", "rules")])
def test_given_a_rule_id_should_name_the_rule_set_it_came_from(rule, source):
    assert source_of(rule) == source


@pytest.mark.pbir
def test_given_envelope_rows_should_tag_each_with_its_source():
    rows = [{"rule": "CONTRACT.r1"}, {"rule": "SHOW_VISUAL_HEADER"}]

    assert [r["source"] for r in tag_sources(rows)] == ["contract", "rules"]


@pytest.mark.pbir
def test_given_a_paired_contract_should_name_its_file_relative_to_here_and_what_it_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # the summary records the file as found under --artifact-dir

    line = contract_line(_report(tmp_path), _summary(tmp_path, rules=12, navigators=3))

    shown = Path("contracts") / "Sales.Report.odcs.yaml"
    assert line == f"📜 Slicer contract: {shown} (12 slicer checks, 3 bookmark navigators)"


@pytest.mark.pbir
def test_given_a_contract_outside_here_should_show_its_full_path(tmp_path, monkeypatch):
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    summary = _summary(tmp_path, rules=1, navigators=0)
    summary.write_text(json.dumps({"file": str(tmp_path / "Sales.Report.odcs.yaml"), "rules": [{}]}), encoding="utf-8")

    assert contract_line(_report(tmp_path), summary) == (
        f"📜 Slicer contract: {tmp_path / 'Sales.Report.odcs.yaml'} (1 slicer check)")


@pytest.mark.pbir
def test_given_no_contract_should_say_none_paired_and_with_which_logical_id(tmp_path):
    line = contract_line(_report(tmp_path), None)

    assert line == (f"📜 Slicer contract: none (no *.odcs.yaml under --artifact-dir has fabTestReport {LOGICAL_ID}; "
                    "only the PBIR rules run)")


@pytest.mark.pbir
def test_given_a_report_without_a_logical_id_should_say_it_cant_pair(tmp_path):
    line = contract_line(_report(tmp_path, logical_id=None), None)

    assert line == "📜 Slicer contract: none (the report has no .platform logicalId to pair on; pass --contract FILE)"


@pytest.mark.pbir
@pytest.mark.parametrize("rules, paired, expected", [
    (["SHOW_VISUAL_HEADER", "CONTRACT.r1", "CONTRACT.r2"], True, "1 from the PBIR rules, 2 from the slicer contract"),
    (["SHOW_VISUAL_HEADER"], True, "1 from the PBIR rules, 0 from the slicer contract"),  # the contract passed
    (["SHOW_VISUAL_HEADER"], False, "1 from the PBIR rules"),
])
def test_given_findings_should_split_the_count_by_rule_set(rules, paired, expected):
    assert count_line([{"rule": r} for r in rules], paired) == expected


FOUND = "'Fiscal Calendar'[Half Year] opens with ['2025 H2']; the contract expects 2026 H2"
# As PBIR Inspector writes a failed rule's message (CRLF and all).
WRAPPED = ("Rule \"Standard Slicers: 'Fiscal Calendar'[Half Year] opens with 2026 H2\" FAILED with result: [\r\n"
           f"  {json.dumps(FOUND)}\r\n], expected: []")


@pytest.mark.pbir
def test_given_a_contract_finding_should_carry_only_what_the_rule_found():
    [row] = tag_sources([{"rule": "CONTRACT.half-year-current", "message": WRAPPED}])

    assert row["message"] == FOUND


@pytest.mark.pbir
@pytest.mark.parametrize("rule, message", [("SHOW_VISUAL_HEADER", WRAPPED),                 # not ours to reword
                                           ("CONTRACT.r1", "no result list to unwrap"),
                                           ("CONTRACT.r1", 'FAILED with result: [1, 2], expected: []')])
def test_given_any_other_message_should_leave_it_as_pbir_inspector_wrote_it(rule, message):
    assert tag_sources([{"rule": rule, "message": message}])[0]["message"] == message
