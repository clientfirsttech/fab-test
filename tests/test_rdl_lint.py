"""Unit tests for scripts/_rdl_lint.py -- the pure RDL rule engine.

Scope
-----
Namespace-agnostic XML parsing, the rule catalog loader, and the check
dispatch table. Always passes on any machine -- no external tool, synthetic
fixtures only.

    pytest tests/test_rdl_lint.py
"""

import json

import pytest

from fab_test.scripts._rdl_lint import (
    CHECKS,
    CURRENT_RDL_NAMESPACE,
    RdlParseError,
    _check_ds01_shared_data_source,
    _check_ds02_unused_datasets,
    _check_ds05_no_select_star,
    _check_ds07_prefer_stored_procedures,
    _check_str01_current_schema,
    build_test_results,
    load_rule_catalog,
    parse_rdl,
    run_checks,
)

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


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestParseRdl:
    def test_strips_namespace_for_the_2016_schema(self, tmp_path):
        path = _write(tmp_path, "report.rdl", _RDL_2016)

        root, namespace = parse_rdl(path)

        assert root.tag == "Report"
        assert root.find("DataSets/DataSet").attrib["Name"] == "Sales"
        assert namespace == "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"

    def test_strips_namespace_for_an_older_schema(self, tmp_path):
        """A rule written against local names alone (`Report`, `Tablix`) works
        the same regardless of which RDL schema version produced the file."""
        path = _write(tmp_path, "report.rdl", _RDL_2008)

        root, namespace = parse_rdl(path)

        assert root.tag == "Report"
        assert root.find(".//Tablix").attrib["Name"] == "Tablix1"
        assert namespace == "http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition"

    def test_raises_rdl_parse_error_for_malformed_xml(self, tmp_path):
        path = _write(tmp_path, "broken.rdl", "<Report><Unclosed>")

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
        root, namespace = parse_rdl(_write(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "error", "disabled": True}]
        CHECKS["FAKE-01"] = lambda _root, _namespace: [{"object": "x", "message": "should not fire"}]
        try:
            assert run_checks(root, namespace, catalog) == []
        finally:
            del CHECKS["FAKE-01"]

    def test_returns_no_findings_when_no_check_is_registered(self, tmp_path):
        root, namespace = parse_rdl(_write(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-UNIMPLEMENTED", "severity": "error", "disabled": False}]

        assert run_checks(root, namespace, catalog) == []

    def test_dispatches_to_a_registered_check_and_tags_the_finding(self, tmp_path):
        root, namespace = parse_rdl(_write(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "error", "disabled": False}]
        CHECKS["FAKE-01"] = lambda _root, _namespace: [{"object": "Tablix1", "message": "fired"}]
        try:
            findings = run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert findings == [{"object": "Tablix1", "message": "fired", "rule": "FAKE-01", "severity": "error"}]

    def test_a_finding_own_severity_overrides_the_catalog_default(self, tmp_path):
        root, namespace = parse_rdl(_write(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "warning", "disabled": False}]
        CHECKS["FAKE-01"] = lambda _root, _namespace: [{"object": "x", "message": "m", "severity": "error"}]
        try:
            findings = run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert findings[0]["severity"] == "error"

    def test_a_check_receives_the_report_namespace(self, tmp_path):
        root, namespace = parse_rdl(_write(tmp_path, "r.rdl", _RDL_2008))
        catalog = [{"id": "FAKE-01", "severity": "warning", "disabled": False}]
        seen = []

        def _spy_check(_root, ns):
            seen.append(ns)
            return []

        CHECKS["FAKE-01"] = _spy_check
        try:
            run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert seen == ["http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition"]


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


# --------------------------------------------------------------------------- #
# Structure and data source rules (STR-01, DS-01, DS-02, DS-05, DS-07)
# --------------------------------------------------------------------------- #
#
# Fixture shape mirrors a real Report Builder-authored .rdl
# (.fabric/artifacts/PaginatedExample-WithFilter.rdl), confirmed live:
# DataSet/Query has direct children DataSourceName, then CommandText --
# CommandType/CommandText also appear nested inside rd:DesignerState under
# a *different* namespace, which parse_rdl's stripping collapses to the
# same local names, so a real check must never findall(".//CommandText")
# to mean "this dataset's own query".


def _report(body: str, *, namespace: str = CURRENT_RDL_NAMESPACE) -> str:
    # rd: is declared because _dataset()'s DesignerState fixture uses it,
    # matching a real Report Builder-authored .rdl's own root attributes.
    return (
        f'<Report xmlns="{namespace}" '
        'xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">'
        f"{body}</Report>"
    )


def _data_source(name: str, provider: str, *, connect_string: str = "", reference: str = "") -> str:
    if reference:
        return f'<DataSource Name="{name}"><DataSourceReference>{reference}</DataSourceReference></DataSource>'
    return (
        f'<DataSource Name="{name}"><ConnectionProperties>'
        f"<DataProvider>{provider}</DataProvider><ConnectString>{connect_string}</ConnectString>"
        f"</ConnectionProperties></DataSource>"
    )


def _dataset(name: str, data_source_name: str, command_text: str, *, command_type: str = "") -> str:
    # A DesignerState blob with its own (different-namespace) CommandText,
    # deliberately included so a check that used a recursive .// search
    # for CommandText would double the wrong way -- confirms the fixture
    # exercises the real collision, not just the happy path.
    designer_state = (
        '<rd:DesignerState><QueryDefinition xmlns="http://schemas.microsoft.com/AnalysisServices/QueryDefinition">'
        "<CommandType>DAX</CommandType><Query><Statement>EVALUATE 'DecoyTable'</Statement></Query>"
        "</QueryDefinition></rd:DesignerState>"
    )
    command_type_xml = f"<CommandType>{command_type}</CommandType>" if command_type else ""
    return (
        f'<DataSet Name="{name}"><Query><DataSourceName>{data_source_name}</DataSourceName>'
        f"{designer_state}{command_type_xml}<CommandText>{command_text}</CommandText></Query></DataSet>"
    )


def _parse(tmp_path, xml: str):
    path = tmp_path / "r.rdl"
    path.write_text(xml, encoding="utf-8")
    return parse_rdl(path)


class TestStr01CurrentSchema:
    def test_flags_an_older_schema(self, tmp_path):
        root, namespace = _parse(
            tmp_path, _report("", namespace="http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition")
        )

        findings = _check_str01_current_schema(root, namespace)

        assert len(findings) == 1
        assert "2008" in findings[0]["message"]

    def test_passes_for_the_current_schema(self, tmp_path):
        root, namespace = _parse(tmp_path, _report(""))

        assert _check_str01_current_schema(root, namespace) == []


class TestDs01SharedDataSource:
    def test_pbidataset_embedded_connection_is_exempt(self, tmp_path):
        """A bound semantic model has no shared-data-source alternative in
        Fabric -- PBIDATASET is never flagged for embedding its connection."""
        xml = _report(f"<DataSources>{_data_source('DS1', 'PBIDATASET', connect_string='Data Source=x')}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds01_shared_data_source(root, namespace) == []

    def test_relational_embedded_connection_is_flagged(self, tmp_path):
        source = _data_source("DS1", "SQLAZURE", connect_string="Data Source=sql;Initial Catalog=db")
        xml = _report(f"<DataSources>{source}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds01_shared_data_source(root, namespace)

        assert len(findings) == 1
        assert "shared data source" in findings[0]["message"]

    def test_relational_data_source_reference_is_not_flagged(self, tmp_path):
        xml = _report(f"<DataSources>{_data_source('DS1', 'SQLAZURE', reference='Shared.rsds')}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds01_shared_data_source(root, namespace) == []

    def test_embedded_password_is_flagged_without_being_echoed(self, tmp_path):
        source = _data_source("DS1", "SQLAZURE", connect_string="Data Source=sql;Password=Sup3rSecret!")
        xml = _report(f"<DataSources>{source}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds01_shared_data_source(root, namespace)

        messages = " ".join(f["message"] for f in findings)
        assert "password" in messages.lower()
        assert "Sup3rSecret!" not in messages


class TestDs02UnusedDatasets:
    def test_a_dataset_bound_to_a_tablix_is_used(self, tmp_path):
        xml = _report(
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('T'[C])") + "</DataSets>"
            '<Body><ReportItems><Tablix Name="T1"><DataSetName>Sales</DataSetName></Tablix></ReportItems></Body>'
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds02_unused_datasets(root, namespace) == []

    def test_a_dataset_referenced_only_in_an_expression_is_used(self, tmp_path):
        """Given a dataset whose name appears only inside an expression
        (e.g. Lookup(..., "Sales")), DS-02 should treat it as used."""
        xml = _report(
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('T'[C])") + "</DataSets>"
            '<Body><ReportItems><Textbox Name="T1"><Value>'
            '=Lookup(Fields!Key.Value, Fields!Key.Value, Fields!Amount.Value, "Sales")'
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds02_unused_datasets(root, namespace) == []

    def test_a_dataset_referenced_nowhere_is_flagged(self, tmp_path):
        dataset = _dataset("Orphan", "DS1", "EVALUATE SUMMARIZECOLUMNS('T'[C])")
        xml = _report(f"<DataSets>{dataset}</DataSets><Body />")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds02_unused_datasets(root, namespace)

        assert len(findings) == 1
        assert findings[0]["object"] == "Orphan"


class TestDs05NoSelectStar:
    def test_flags_a_bare_dax_evaluate_of_a_whole_table(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE 'Sales'") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds05_no_select_star(root, namespace)

        assert len(findings) == 1
        assert "SELECT *" in findings[0]["message"]

    def test_does_not_flag_a_projected_dax_query(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('Sales'[Amount])") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace) == []

    def test_flags_sql_select_star(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT * FROM Sales") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert len(_check_ds05_no_select_star(root, namespace)) == 1

    def test_does_not_flag_projected_sql(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT Amount FROM Sales") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace) == []

    def test_power_query_source_is_not_applicable(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PQO')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT * FROM whatever Power Query emits") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace) == []


class TestDs07PreferStoredProcedures:
    def test_flags_inline_sql_text(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT Amount FROM Sales") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert len(_check_ds07_prefer_stored_procedures(root, namespace)) == 1

    def test_does_not_flag_a_stored_procedure(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>"
            + _dataset("Sales", "DS1", "usp_GetSales", command_type="StoredProcedure")
            + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds07_prefer_stored_procedures(root, namespace) == []

    def test_does_not_apply_to_pbidataset(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('Sales'[Amount])") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds07_prefer_stored_procedures(root, namespace) == []
