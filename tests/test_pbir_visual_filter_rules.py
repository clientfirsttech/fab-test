"""Contract tests for visual-level filter-pane rules."""

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.pbir

_RULES_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "fab_test"
    / "metadata"
    / "rules"
    / "pbi-inspector-custom-rules.json"
)
_THIN_REPORT_VISUALS = (
    Path(__file__).parents[1]
    / "fabric-artifacts"
    / "ThinReport.Report"
    / "definition"
    / "pages"
    / "6c8284d4d466918cdb1c"
    / "visuals"
)


def _rules_by_id() -> dict[str, dict]:
    rules = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    return {rule["id"]: rule for rule in rules["rules"]}


@pytest.mark.parametrize(
    ("rule_id", "required_property"),
    [
        ("NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL", "isHiddenInViewMode"),
        ("NO_VISUAL_LEVEL_FILTERS_UNLOCKED_IN_FILTER_PANEL", "isLockedInViewMode"),
    ],
)
def test_visual_filter_rules_are_enabled_errors_scoped_to_visible_filter_panes(
    rule_id, required_property
):
    """Given the core ruleset, should enforce each visual filter development setting.

    Report-level, because the filter pane setting lives in report.json and a
    per-visual rule resolves it against visual.json (always absent). The
    expected value is `[]` because the test maps offending visuals to names --
    a boolean test against `[]` is the mismatch that flagged every visual.
    `tests/test_pbir_filter_pane_rules_live.py` checks the behavior with
    PBIR Inspector itself.
    """
    rule = _rules_by_id()[rule_id]
    logic, mapping, expected = rule["test"]
    rule_json = json.dumps(logic)

    assert rule["logType"] == "error"
    assert rule["disabled"] is False
    assert rule["part"] == "Report"
    assert mapping == {"filterPaneVisible": "/objects/outspacePane/0/properties/visible/expr/Literal/Value"}
    assert expected == []
    assert '"map"' in rule_json
    assert required_property in rule_json
    assert '"false"' in rule_json


def test_visual_filter_rules_do_not_traverse_page_or_report_filter_collections():
    """Given page/report filters are consumer controls, should inspect visual filters only."""
    rules = _rules_by_id()

    for rule_id in (
        "NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL",
        "NO_VISUAL_LEVEL_FILTERS_UNLOCKED_IN_FILTER_PANEL",
    ):
        rule_json = json.dumps(rules[rule_id]["test"])
        assert rules[rule_id]["part"] == "Report"
        assert rule_json.count('"part"') == 1  # the nested visuals, and nothing else
        assert '"part": "Visuals"' in rule_json
        assert '"part": "Pages"' not in rule_json


def test_thin_report_covers_visual_filter_hidden_and_locked_permutations():
    """Given the PBIR fixture, should retain the three visual filter states under test."""
    states = set()
    for visual_path in _THIN_REPORT_VISUALS.glob("*/visual.json"):
        visual = json.loads(visual_path.read_text(encoding="utf-8"))
        for filter_config in visual.get("filterConfig", {}).get("filters", []):
            states.add(
                (
                    filter_config.get("isHiddenInViewMode"),
                    filter_config.get("isLockedInViewMode"),
                )
            )

    assert {(None, True), (True, None), (None, None)} <= states
