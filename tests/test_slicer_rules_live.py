"""Contract To JSON Logic, measured with PBIR Inspector (PBIR Slicer Default State epic).

Runs the real CLI on a copy of the SampleModel-DefaultState test bed with its
contract beside it, so pairing, compiling, resolving and reporting are all
exercised the way a developer would hit them.
"""

import argparse
import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.integration, pytest.mark.pbir]

ROOT = Path(__file__).resolve().parents[1]
TEST_BED = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report"
CONTRACT = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report.odcs.yaml"
RULE_IDS = {"alignment-default", "eye-color-default", "fiscal-semester-current", "half-year-current",
            "year-default", "first-appearance-range", "relative-date-default", "date-picker-default",
            "chart-measure-default", "character-name-default"}
# One value changed per rule; half-year-current already fails on 2026-11-14.
ONE_VALUE_OFF = {
    "alignment-default": {"selected": ["Good"]},
    "eye-color-default": {"selected": ["Black"]},
    "fiscal-semester-current": {"selected": ["FY27-S2"]},
    "year-default": {"selected": [1941]},
    "first-appearance-range": {"range": {"to": datetime.date(2026, 10, 27)}},
    "relative-date-default": {"relative": {"range": "Last", "duration": 19, "period": "Calendar Months"}},
    "date-picker-default": {"range": {"from": datetime.date(1939, 10, 2), "to": datetime.date(1951, 8, 27)}},
    "chart-measure-default": {"selected": ["Running Total"]},
    "character-name-default": {"contains": ["Spider"]},
}


@pytest.fixture(scope="module")
def inspector() -> None:
    from fab_test.scripts._readiness import resolve_tool

    try:
        resolve_tool("pbir", argparse.Namespace())
    except (RuntimeError, OSError) as exc:
        pytest.skip(f"PBIR Inspector unavailable: {exc}")


def _bed(tmp_path: Path, contract: dict | None) -> Path:
    shutil.copytree(TEST_BED, tmp_path / TEST_BED.name)
    if contract is not None:
        (tmp_path / CONTRACT.name).write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    return tmp_path


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _rules(document: dict):
    for table in document["schema"]:
        for column in table["properties"]:
            yield from column["quality"]


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "pbir", "--artifact", "SampleModel-DefaultState",
         "--artifact-dir", str(root), "--output-dir", str(root / "out"), "--as-of", "2026-11-14", *extra],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "GITHUB_ACTIONS": "", "CI": ""},
    )


def _failed(root: Path) -> set[str]:
    [native] = list((root / "out").glob("pbir/*/native.json/*.json"))
    results = json.loads(native.read_text(encoding="utf-8-sig"))["Results"]
    return {r["RuleId"] for r in results if not r["Pass"] and r["RuleId"].startswith("CONTRACT.")}


def _envelope(root: Path) -> dict:
    [envelope] = list((root / "out").glob("pbir/*/envelope.json"))
    return json.loads(envelope.read_text(encoding="utf-8"))


def test_given_the_test_bed_contract_should_fail_only_the_stale_calendar_default(inspector, tmp_path):
    root = _bed(tmp_path, _contract())

    result = _run(root)

    assert result.returncode == 1, result.stderr
    assert _failed(root) == {"CONTRACT.half-year-current"}
    [finding] = [f for f in _envelope(root)["findings"] if f["rule"] == "CONTRACT.half-year-current"]
    assert finding["object"] == "Standard Slicers"
    assert "2025 H2" in finding["message"] and "2026 H2" in finding["message"]


def test_given_one_value_off_in_every_rule_and_a_missing_page_should_fail_each(inspector, tmp_path):
    document = _contract()
    for rule in _rules(document):
        rule["implementation"].update(ONE_VALUE_OFF.get(rule["id"], {}))
    ghost = copy.deepcopy(document["schema"][0]["properties"][0]["quality"][0])
    ghost.update(id="ghost-page", implementation={"page": "Renamed Away", "selected": ["Bad"]})
    document["schema"][0]["properties"][0]["quality"].append(ghost)
    root = _bed(tmp_path, document)

    _run(root)

    assert _failed(root) == {f"CONTRACT.{rule_id}" for rule_id in RULE_IDS} | {"CONTRACT.page.Renamed Away"}


def test_given_as_of_should_record_it_and_every_resolved_value_in_the_envelope(inspector, tmp_path):
    root = _bed(tmp_path, _contract())

    _run(root)

    contract = _envelope(root)["contract"]
    assert contract["as_of"] == "2026-11-14"
    assert contract["report_logical_id"] == "b3cba6e7-ddfc-4bcd-b4b1-5f2a3d5297fc"
    by_id = {rule["id"]: rule["expected"] for rule in contract["rules"]}
    assert by_id["fiscal-semester-current"] == ["FY27-S1"] and by_id["half-year-current"] == ["2026 H2"]


def test_given_an_explicit_contract_should_use_it_instead_of_pairing(inspector, tmp_path):
    root = _bed(tmp_path, None)
    document = _contract()
    document["customProperties"][0]["value"] = "00000000-0000-0000-0000-000000000000"
    explicit = tmp_path / "elsewhere.yaml"
    explicit.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    _run(root, "--contract", str(explicit))

    assert _failed(root) == {"CONTRACT.half-year-current"}


def test_given_a_malformed_contract_should_exit_2_before_analysis(tmp_path):
    document = _contract()
    document["schema"][0]["properties"][0]["quality"][0]["implementation"]["selected"] = "Bad"
    root = _bed(tmp_path, document)

    result = _run(root)

    assert result.returncode == 2
    assert "implementation.selected" in result.stderr
    assert not (root / "out").exists() or not list((root / "out").glob("pbir/*/envelope.json"))


def test_given_a_report_without_a_contract_should_run_unchanged(inspector, tmp_path):
    root = _bed(tmp_path, None)

    _run(root)

    assert "contract" not in _envelope(root)
    assert _failed(root) == set()
