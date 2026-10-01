"""Only verified rules are active: a rule earns "active" by tripping a real
Report Builder fixture named for it, and "planned" rules neither run nor
appear in a user's results (RDL Rule Coverage epic)."""

import json
from pathlib import Path

import pytest

from fab_test.scripts._rdl_lint import CHECKS, build_test_results, parse_rdl, run_checks

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent
_CATALOG_PATH = _REPO / "src" / "fab_test" / "metadata" / "rules" / "rdl-rules.json"
_FIXTURES = _REPO / ".fabric" / "artifacts" / "rdl"
_RULES = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
_ACTIVE = [r for r in _RULES if r.get("status") == "active"]


def _rule(rule_id: str, status: str | None = None) -> dict:
    rule = {"id": rule_id, "name": "n", "severity": "error", "disabled": False, "description": "d"}
    if status is not None:
        rule["status"] = status
    return rule


class TestEngine:
    def test_a_planned_rule_is_not_run(self):
        ran = []
        CHECKS["FAKE-01"] = lambda *_: ran.append(1) or [{"object": "x", "message": "m"}]
        try:
            root, ns = parse_rdl(_FIXTURES / "DS-02.rdl")
            findings = run_checks(root, ns, [_rule("FAKE-01", "planned")])
        finally:
            del CHECKS["FAKE-01"]

        assert findings == []
        assert ran == []

    def test_a_rule_with_no_status_is_active(self):
        CHECKS["FAKE-01"] = lambda *_: [{"object": "x", "message": "m"}]
        try:
            root, ns = parse_rdl(_FIXTURES / "DS-02.rdl")
            findings = run_checks(root, ns, [_rule("FAKE-01")])
        finally:
            del CHECKS["FAKE-01"]

        assert len(findings) == 1

    def test_a_planned_rule_has_no_results_row(self):
        catalog = [_rule("FAKE-01", "active"), _rule("FAKE-02", "planned")]

        rows = build_test_results(catalog, [], implemented={"FAKE-01", "FAKE-02"})

        assert [r["rule"] for r in rows] == ["FAKE-01"]


class TestPackagedCatalog:
    def test_every_rule_declares_a_status(self):
        assert {r["id"]: r.get("status") for r in _RULES if r.get("status") not in ("active", "planned")} == {}

    def test_some_rules_are_active(self):
        assert _ACTIVE

    @pytest.mark.parametrize("rule", _ACTIVE, ids=lambda r: r["id"])
    def test_an_active_rule_has_a_check_and_a_fixture_that_trips_it(self, rule):
        fixture = _FIXTURES / f"{rule['id']}.rdl"
        assert rule["id"] in CHECKS, f"{rule['id']} is active but has no check"
        assert fixture.exists(), f"{rule['id']} is active but has no real fixture {fixture.name}"
        root, ns = parse_rdl(fixture)
        fired = {r for f in run_checks(root, ns, _RULES) for r in f["rule"].split("/")}
        assert rule["id"] in fired
