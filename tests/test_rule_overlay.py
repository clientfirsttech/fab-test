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

from fab_test.scripts._rule_overlay import (
    RuleOverlayError,
    apply_overlay,
    apply_pbir_overlay,
    apply_rdl_overlay,
)

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


# --------------------------------------------------------------------------- #
# PBIR Inspector's own rule shape: {"rules": [{"id", "disabled", "logType"}]}
# --------------------------------------------------------------------------- #

_PBIR_RULE_A = {"id": "RULE_A", "name": "Rule A", "disabled": False, "logType": "warning"}
_PBIR_RULE_B = {"id": "RULE_B", "name": "Rule B", "disabled": False, "logType": "warning"}


def _write_pbir_rules(path, rules):
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")


@pytest.mark.fab_test
def test_apply_pbir_overlay_marks_a_rule_disabled(tmp_path):
    """PBIR's own convention: disabling sets disabled=true rather than removing the rule."""
    upstream = tmp_path / "rules.json"
    _write_pbir_rules(upstream, [_PBIR_RULE_A, _PBIR_RULE_B])

    resolved = apply_pbir_overlay(upstream, {"disable": ["RULE_A"]})

    by_id = {r["id"]: r for r in resolved["rules"]}
    assert by_id["RULE_A"]["disabled"] is True
    assert by_id["RULE_B"]["disabled"] is False


@pytest.mark.fab_test
def test_apply_pbir_overlay_overrides_log_type(tmp_path):
    """A severity override sets logType directly -- PBIR already uses these labels."""
    upstream = tmp_path / "rules.json"
    _write_pbir_rules(upstream, [_PBIR_RULE_A])

    resolved = apply_pbir_overlay(upstream, {"severity": {"RULE_A": "error"}})

    assert resolved["rules"][0]["logType"] == "error"


@pytest.mark.fab_test
def test_apply_pbir_overlay_extends_with_additional_rules(tmp_path):
    """Rules from the extend file are appended."""
    upstream = tmp_path / "rules.json"
    _write_pbir_rules(upstream, [_PBIR_RULE_A])
    extra = tmp_path / "extra.json"
    extra_rule = {"id": "CUSTOM", "name": "Custom", "disabled": False, "logType": "warning"}
    _write_pbir_rules(extra, [extra_rule])

    resolved = apply_pbir_overlay(upstream, {"extend": str(extra)})

    ids = {r["id"] for r in resolved["rules"]}
    assert ids == {"RULE_A", "CUSTOM"}


@pytest.mark.fab_test
def test_apply_pbir_overlay_raises_for_unmatched_id(tmp_path):
    """Disabling an unknown rule ID raises, naming it."""
    upstream = tmp_path / "rules.json"
    _write_pbir_rules(upstream, [_PBIR_RULE_A])

    with pytest.raises(RuleOverlayError, match="NONEXISTENT"):
        apply_pbir_overlay(upstream, {"disable": ["NONEXISTENT"]})


@pytest.mark.fab_test
def test_apply_pbir_overlay_rejects_info_severity_label(tmp_path):
    """'info' is not an observed PBIR logType value -- reject it rather than
    silently passing through something PBIR Inspector may not recognize.
    """
    upstream = tmp_path / "rules.json"
    _write_pbir_rules(upstream, [_PBIR_RULE_A])

    with pytest.raises(RuleOverlayError, match="info"):
        apply_pbir_overlay(upstream, {"severity": {"RULE_A": "info"}})


@pytest.mark.fab_test
def test_apply_pbir_overlay_preserves_other_top_level_keys(tmp_path):
    """Top-level keys besides "rules" (if any) survive the overlay unchanged."""
    upstream = tmp_path / "rules.json"
    upstream.write_text(
        json.dumps({"rules": [_PBIR_RULE_A], "paramMaxVisualsPerPage": 20}), encoding="utf-8"
    )

    resolved = apply_pbir_overlay(upstream, {})

    assert resolved["paramMaxVisualsPerPage"] == 20


@pytest.mark.fab_test
def test_apply_pbir_overlay_never_rewrites_upstream_file(tmp_path):
    """apply_pbir_overlay never mutates or rewrites the upstream file."""
    upstream = tmp_path / "rules.json"
    _write_pbir_rules(upstream, [_PBIR_RULE_A])
    original_text = upstream.read_text(encoding="utf-8")

    apply_pbir_overlay(upstream, {"disable": ["RULE_A"]})

    assert upstream.read_text(encoding="utf-8") == original_text


# --------------------------------------------------------------------------- #
# RDL's own rule shape: {"rules": [{"id", "disabled", "severity"}]} -- same
# {"rules": [...]} envelope as PBIR, but "severity" is set directly rather
# than through a "logType" indirection, and "info" is a valid label.
# --------------------------------------------------------------------------- #

_RDL_RULE_A = {"id": "DS-02", "name": "No unused datasets", "disabled": False, "severity": "error"}
_RDL_RULE_B = {"id": "QRY-07", "name": "Move complex SQL into views", "disabled": False, "severity": "warning"}


def _write_rdl_rules(path, rules):
    path.write_text(json.dumps({"rules": rules}), encoding="utf-8")


@pytest.mark.fab_test
def test_apply_rdl_overlay_marks_a_rule_disabled(tmp_path):
    """RDL's own convention: disabling sets disabled=true rather than removing the rule."""
    upstream = tmp_path / "rules.json"
    _write_rdl_rules(upstream, [_RDL_RULE_A, _RDL_RULE_B])

    resolved = apply_rdl_overlay(upstream, {"disable": ["DS-02"]})

    by_id = {r["id"]: r for r in resolved["rules"]}
    assert by_id["DS-02"]["disabled"] is True
    assert by_id["QRY-07"]["disabled"] is False


@pytest.mark.fab_test
def test_apply_rdl_overlay_overrides_severity(tmp_path):
    """A severity override sets the catalog's own severity field directly."""
    upstream = tmp_path / "rules.json"
    _write_rdl_rules(upstream, [_RDL_RULE_A])

    resolved = apply_rdl_overlay(upstream, {"severity": {"DS-02": "warning"}})

    assert resolved["rules"][0]["severity"] == "warning"


@pytest.mark.fab_test
def test_apply_rdl_overlay_accepts_info_severity_label(tmp_path):
    """Unlike PBIR, the RDL catalog has no restriction ruling out 'info'."""
    upstream = tmp_path / "rules.json"
    _write_rdl_rules(upstream, [_RDL_RULE_A])

    resolved = apply_rdl_overlay(upstream, {"severity": {"DS-02": "info"}})

    assert resolved["rules"][0]["severity"] == "info"


@pytest.mark.fab_test
def test_apply_rdl_overlay_extends_with_additional_rules(tmp_path):
    """Rules from the extend file are appended."""
    upstream = tmp_path / "rules.json"
    _write_rdl_rules(upstream, [_RDL_RULE_A])
    extra = tmp_path / "extra.json"
    extra_rule = {"id": "CUSTOM", "name": "Custom", "disabled": False, "severity": "warning"}
    _write_rdl_rules(extra, [extra_rule])

    resolved = apply_rdl_overlay(upstream, {"extend": str(extra)})

    ids = {r["id"] for r in resolved["rules"]}
    assert ids == {"DS-02", "CUSTOM"}


@pytest.mark.fab_test
def test_apply_rdl_overlay_raises_for_unmatched_id(tmp_path):
    """Disabling an unknown rule ID raises, naming it."""
    upstream = tmp_path / "rules.json"
    _write_rdl_rules(upstream, [_RDL_RULE_A])

    with pytest.raises(RuleOverlayError, match="NONEXISTENT"):
        apply_rdl_overlay(upstream, {"disable": ["NONEXISTENT"]})


@pytest.mark.fab_test
def test_apply_rdl_overlay_raises_for_unknown_severity_label(tmp_path):
    """An unrecognized severity label (not info/warning/error) is rejected."""
    upstream = tmp_path / "rules.json"
    _write_rdl_rules(upstream, [_RDL_RULE_A])

    with pytest.raises(RuleOverlayError, match="critical"):
        apply_rdl_overlay(upstream, {"severity": {"DS-02": "critical"}})


@pytest.mark.fab_test
def test_apply_rdl_overlay_preserves_other_top_level_keys(tmp_path):
    """Top-level keys besides "rules" (e.g. "notes") survive the overlay unchanged."""
    upstream = tmp_path / "rules.json"
    upstream.write_text(json.dumps({"rules": [_RDL_RULE_A], "notes": "Tier A only"}), encoding="utf-8")

    resolved = apply_rdl_overlay(upstream, {})

    assert resolved["notes"] == "Tier A only"


@pytest.mark.fab_test
def test_apply_rdl_overlay_never_rewrites_upstream_file(tmp_path):
    """apply_rdl_overlay never mutates or rewrites the upstream file."""
    upstream = tmp_path / "rules.json"
    _write_rdl_rules(upstream, [_RDL_RULE_A])
    original_text = upstream.read_text(encoding="utf-8")

    apply_rdl_overlay(upstream, {"disable": ["DS-02"]})

    assert upstream.read_text(encoding="utf-8") == original_text
