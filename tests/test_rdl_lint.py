"""Unit tests for scripts/_rdl_lint.py -- the pure RDL rule engine's core:
namespace-agnostic XML parsing, the rule catalog loader, the check
dispatch table, and the report table builder.

Per-rule tests live in their own modules, one per rule family (Test
Module Split precedent): test_rdl_lint_structure.py, test_rdl_lint_query.py,
test_rdl_lint_parameters.py, test_rdl_lint_layout.py. Always passes on any
machine -- no external tool, synthetic fixtures only.

    pytest tests/test_rdl_lint.py
"""

import json

import pytest

from fab_test.scripts._rdl_lint import (
    CHECKS,
    RdlParseError,
    build_test_results,
    load_rule_catalog,
    parse_rdl,
    run_checks,
)
from tests._rdl_lint_fixtures import write_rdl

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_RDL_2016 = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">
  <DataSets>
    <DataSet Name="Sales">
      <Query><CommandText>EVALUATE 'Sales'</CommandText></Query>
    </DataSet>
  </DataSets>
  <Body><ReportItems><Tablix Name="Tablix1" /></ReportItems></Body>
</Report>
"""

_RDL_2008 = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition">
  <Body><ReportItems><Tablix Name="Tablix1" /></ReportItems></Body>
</Report>
"""


class TestParseRdl:
    def test_strips_namespace_for_the_2016_schema(self, tmp_path):
        path = write_rdl(tmp_path, "report.rdl", _RDL_2016)

        root, namespace = parse_rdl(path)

        assert root.tag == "Report"
        assert root.find("DataSets/DataSet").attrib["Name"] == "Sales"
        assert namespace == "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"

    def test_strips_namespace_for_an_older_schema(self, tmp_path):
        """A rule written against local names alone (`Report`, `Tablix`) works
        the same regardless of which RDL schema version produced the file."""
        path = write_rdl(tmp_path, "report.rdl", _RDL_2008)

        root, namespace = parse_rdl(path)

        assert root.tag == "Report"
        assert root.find(".//Tablix").attrib["Name"] == "Tablix1"
        assert namespace == "http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition"

    def test_raises_rdl_parse_error_for_malformed_xml(self, tmp_path):
        path = write_rdl(tmp_path, "broken.rdl", "<Report><Unclosed>")

        with pytest.raises(RdlParseError, match="not well-formed"):
            parse_rdl(path)

    def test_raises_rdl_parse_error_for_a_missing_file(self, tmp_path):
        missing = tmp_path / "missing.rdl"

        with pytest.raises(RdlParseError):
            parse_rdl(missing)


class TestLoadRuleCatalog:
    def test_returns_the_rules_list(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text(
            json.dumps({"rules": [{"id": "DS-02", "severity": "error", "disabled": False}]}),
            encoding="utf-8",
        )

        catalog = load_rule_catalog(path)

        assert catalog == [{"id": "DS-02", "severity": "error", "disabled": False}]

    def test_returns_empty_list_when_the_document_has_no_rules_key(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text(json.dumps({"notes": "placeholder"}), encoding="utf-8")

        assert load_rule_catalog(path) == []


class TestRunChecks:
    def test_skips_disabled_rules_even_with_a_registered_check(self, tmp_path):
        root, namespace = parse_rdl(write_rdl(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "error", "disabled": True}]
        CHECKS["FAKE-01"] = lambda _root, _namespace, _rule: [{"object": "x", "message": "should not fire"}]
        try:
            assert run_checks(root, namespace, catalog) == []
        finally:
            del CHECKS["FAKE-01"]

    def test_returns_no_findings_when_no_check_is_registered(self, tmp_path):
        root, namespace = parse_rdl(write_rdl(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-UNIMPLEMENTED", "severity": "error", "disabled": False}]

        assert run_checks(root, namespace, catalog) == []

    def test_dispatches_to_a_registered_check_and_tags_the_finding(self, tmp_path):
        root, namespace = parse_rdl(write_rdl(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "error", "disabled": False}]
        CHECKS["FAKE-01"] = lambda _root, _namespace, _rule: [{"object": "Tablix1", "message": "fired"}]
        try:
            findings = run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert findings == [{"object": "Tablix1", "message": "fired", "rule": "FAKE-01", "severity": "error"}]

    def test_a_finding_own_severity_overrides_the_catalog_default(self, tmp_path):
        root, namespace = parse_rdl(write_rdl(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "warning", "disabled": False}]
        CHECKS["FAKE-01"] = lambda _root, _namespace, _rule: [{"object": "x", "message": "m", "severity": "error"}]
        try:
            findings = run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert findings[0]["severity"] == "error"

    def test_a_check_receives_the_report_namespace(self, tmp_path):
        root, namespace = parse_rdl(write_rdl(tmp_path, "r.rdl", _RDL_2008))
        catalog = [{"id": "FAKE-01", "severity": "warning", "disabled": False}]
        seen = []

        def _spy_check(_root, ns, _rule):
            seen.append(ns)
            return []

        CHECKS["FAKE-01"] = _spy_check
        try:
            run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert seen == ["http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition"]

    def test_a_finding_own_rule_wins_over_the_catalog_entry_being_iterated(self, tmp_path):
        """LAY-03/SUB-01's shared check tags its own findings with a
        compound "rule" -- this loop must not stamp the single catalog ID
        it's iterating over that."""
        root, namespace = parse_rdl(write_rdl(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "error", "disabled": False}]
        CHECKS["FAKE-01"] = lambda _root, _namespace, _rule: [
            {"rule": "FAKE-01/FAKE-02", "object": "x", "message": "m"}
        ]
        try:
            findings = run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert findings[0]["rule"] == "FAKE-01/FAKE-02"


class TestBuildTestResults:
    def test_marks_an_unimplemented_rule_as_skip(self):
        catalog = [{"id": "DS-02", "severity": "error", "disabled": False, "description": "No unused datasets"}]

        rows = build_test_results(catalog, [], implemented=set())

        assert rows == [{
            "rule": "DS-02", "severity": "error", "object": "",
            "message": "No unused datasets", "status": "skip",
        }]

    def test_marks_a_disabled_rule_as_skip_even_if_implemented(self):
        catalog = [{"id": "FAKE-01", "severity": "error", "disabled": True, "description": "d"}]

        rows = build_test_results(catalog, [], implemented={"FAKE-01"})

        assert rows[0]["status"] == "skip"
        assert rows[0]["message"] == "d"

    def test_marks_an_implemented_clean_rule_as_pass(self):
        catalog = [{"id": "FAKE-01", "severity": "error", "disabled": False, "description": "d"}]

        rows = build_test_results(catalog, [], implemented={"FAKE-01"})

        assert rows[0]["status"] == "pass"

    def test_uses_the_finding_severity_as_status_when_a_rule_fires(self):
        catalog = [{"id": "FAKE-01", "severity": "warning", "disabled": False, "description": "d"}]
        findings = [{"rule": "FAKE-01", "severity": "error", "object": "Tablix1", "message": "boom"}]

        rows = build_test_results(catalog, findings, implemented={"FAKE-01"})

        assert rows[0]["status"] == "error"
        assert rows[0]["object"] == "Tablix1"
        assert rows[0]["message"] == "boom"

    def test_a_compound_rule_finding_is_shown_under_every_id_it_names(self):
        catalog = [
            {"id": "FAKE-01", "severity": "error", "disabled": False, "description": "d1"},
            {"id": "FAKE-02", "severity": "error", "disabled": False, "description": "d2"},
        ]
        findings = [{"rule": "FAKE-01/FAKE-02", "severity": "error", "object": "x", "message": "boom"}]

        rows = build_test_results(catalog, findings, implemented={"FAKE-01"})

        rows_by_rule = {row["rule"]: row for row in rows}
        assert rows_by_rule["FAKE-01"]["status"] == "error"
        assert rows_by_rule["FAKE-02"]["status"] == "error"
        assert rows_by_rule["FAKE-02"]["object"] == "x"


class TestBuildTestResultsEveryHit:
    """A rule that fires on several elements shows every offender (RDL
    Finding Clarity epic) -- not only the first."""

    _CATALOG = [{"id": "FAKE-01", "severity": "error", "disabled": False, "description": "d"}]

    def test_one_row_per_hit(self):
        findings = [
            {"rule": "FAKE-01", "severity": "error", "object": "DataSet1", "message": "m1"},
            {"rule": "FAKE-01", "severity": "error", "object": "DataSet2", "message": "m2"},
            {"rule": "FAKE-01", "severity": "error", "object": "DataSet3", "message": "m3"},
        ]

        rows = build_test_results(self._CATALOG, findings, implemented={"FAKE-01"})

        assert [(r["object"], r["message"], r["status"]) for r in rows] == [
            ("DataSet1", "m1", "error"), ("DataSet2", "m2", "error"), ("DataSet3", "m3", "error"),
        ]

    def test_each_row_keeps_its_own_hit_severity(self):
        findings = [
            {"rule": "FAKE-01", "severity": "error", "object": "a", "message": "m"},
            {"rule": "FAKE-01", "severity": "warning", "object": "b", "message": "m"},
        ]

        rows = build_test_results(self._CATALOG, findings, implemented={"FAKE-01"})

        assert [r["status"] for r in rows] == ["error", "warning"]

    def test_a_clean_rule_is_still_exactly_one_row(self):
        rows = build_test_results(self._CATALOG, [], implemented={"FAKE-01"})

        assert len(rows) == 1
        assert rows[0]["status"] == "pass"

    def test_source_urls_ride_on_every_hit_row(self):
        catalog = [{**self._CATALOG[0], "source_urls": ["https://x"]}]
        findings = [
            {"rule": "FAKE-01", "severity": "error", "object": "a", "message": "m"},
            {"rule": "FAKE-01", "severity": "error", "object": "b", "message": "m"},
        ]

        rows = build_test_results(catalog, findings, implemented={"FAKE-01"})

        assert all(r["source_urls"] == ["https://x"] for r in rows)
