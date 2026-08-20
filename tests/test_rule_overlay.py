"""Contract tests for the rule overlay engine (Config Consolidation §6).

Scope
-----
An overlay applies deltas (disable/severity/extend) to a packaged BPA
ruleset at run time instead of forking it. Always passes on any machine --
no external tool required, synthetic rule fixtures only.

    pytest tests/test_rule_overlay.py
"""

import json

import pytest

from fabric_ci_cd_dataops.scripts._rule_overlay import RuleOverlayError, apply_overlay

_RULE_A = {"ID": "RULE_A", "Name": "Rule A", "Severity": 1}
_RULE_B = {"ID": "RULE_B", "Name": "Rule B", "Severity": 2}


def _write_rules(path, rules):
    path.write_text(json.dumps(rules), encoding="utf-8")


@pytest.mark.fab_test
def test_apply_overlay_disables_a_rule(tmp_path):
    """A disabled rule is removed; all others stay upstream unchanged."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A, _RULE_B])

    resolved = apply_overlay(upstream, {"disable": ["RULE_A"]})

    ids = {r["ID"] for r in resolved}
    assert ids == {"RULE_B"}
    assert resolved[0] == _RULE_B


@pytest.mark.fab_test
def test_apply_overlay_overrides_severity(tmp_path):
    """A severity override changes only that rule's Severity field."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A, _RULE_B])

    resolved = apply_overlay(upstream, {"severity": {"RULE_A": "warning"}})

    by_id = {r["ID"]: r for r in resolved}
    assert by_id["RULE_A"]["Severity"] == 2
    assert by_id["RULE_B"]["Severity"] == 2  # unchanged (was already 2)
    assert by_id["RULE_A"]["Name"] == "Rule A"  # other fields untouched


@pytest.mark.fab_test
def test_apply_overlay_severity_error_maps_to_three(tmp_path):
    """The 'error' severity label maps to Tabular Editor's severity 3."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A])

    resolved = apply_overlay(upstream, {"severity": {"RULE_A": "error"}})

    assert resolved[0]["Severity"] == 3


@pytest.mark.fab_test
def test_apply_overlay_extends_with_additional_rules(tmp_path):
    """Rules from the extend file are added alongside upstream rules."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A])
    extra = tmp_path / "extra.json"
    extra_rule = {"ID": "CUSTOM_RULE", "Name": "Custom", "Severity": 2}
    _write_rules(extra, [extra_rule])

    resolved = apply_overlay(upstream, {"extend": str(extra)})

    ids = {r["ID"] for r in resolved}
    assert ids == {"RULE_A", "CUSTOM_RULE"}


@pytest.mark.fab_test
def test_apply_overlay_raises_for_unmatched_disable_id(tmp_path):
    """Disabling a rule ID that doesn't exist upstream exits with a clear error."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A])

    with pytest.raises(RuleOverlayError, match="NONEXISTENT_RULE"):
        apply_overlay(upstream, {"disable": ["NONEXISTENT_RULE"]})


@pytest.mark.fab_test
def test_apply_overlay_raises_for_unmatched_severity_id(tmp_path):
    """Overriding severity for an unknown rule ID exits with a clear error."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A])

    with pytest.raises(RuleOverlayError, match="NONEXISTENT_RULE"):
        apply_overlay(upstream, {"severity": {"NONEXISTENT_RULE": "warning"}})


@pytest.mark.fab_test
def test_apply_overlay_lists_every_unmatched_id_at_once(tmp_path):
    """Multiple unmatched IDs across disable and severity are all named together."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A])

    with pytest.raises(RuleOverlayError) as exc_info:
        apply_overlay(upstream, {"disable": ["BOGUS_ONE"], "severity": {"BOGUS_TWO": "warning"}})
    assert "BOGUS_ONE" in str(exc_info.value)
    assert "BOGUS_TWO" in str(exc_info.value)


@pytest.mark.fab_test
def test_apply_overlay_raises_for_unknown_severity_label(tmp_path):
    """An unrecognized severity label (not info/warning/error) is rejected."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A])

    with pytest.raises(RuleOverlayError, match="critical"):
        apply_overlay(upstream, {"severity": {"RULE_A": "critical"}})


@pytest.mark.fab_test
def test_apply_overlay_returns_upstream_unchanged_when_overlay_is_empty(tmp_path):
    """An empty overlay returns the upstream ruleset exactly as-is."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A, _RULE_B])

    assert apply_overlay(upstream, {}) == [_RULE_A, _RULE_B]


@pytest.mark.fab_test
def test_apply_overlay_never_rewrites_the_upstream_file(tmp_path):
    """apply_overlay never mutates or rewrites the upstream rules file."""
    upstream = tmp_path / "rules.json"
    _write_rules(upstream, [_RULE_A, _RULE_B])
    original_text = upstream.read_text(encoding="utf-8")

    apply_overlay(upstream, {"disable": ["RULE_A"], "severity": {"RULE_B": "error"}})

    assert upstream.read_text(encoding="utf-8") == original_text
