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
    _check_prm01_default_value,
    _check_prm03_parameter_count,
    _check_prm04_multivalue_nullable,
    _check_prm05_show_parameter_values,
    _check_qry01_filter_in_query,
    _check_qry02_no_calculated_fields,
    _check_qry03_aggregate_in_query,
    _check_qry04_sort_in_query,
    _check_qry05_convert_types_in_query,
    _check_qry06_join_in_query,
    _check_qry07_move_complex_sql,
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
        CHECKS["FAKE-01"] = lambda _root, _namespace, _rule: [{"object": "x", "message": "should not fire"}]
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
        CHECKS["FAKE-01"] = lambda _root, _namespace, _rule: [{"object": "Tablix1", "message": "fired"}]
        try:
            findings = run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert findings == [{"object": "Tablix1", "message": "fired", "rule": "FAKE-01", "severity": "error"}]

    def test_a_finding_own_severity_overrides_the_catalog_default(self, tmp_path):
        root, namespace = parse_rdl(_write(tmp_path, "r.rdl", _RDL_2016))
        catalog = [{"id": "FAKE-01", "severity": "warning", "disabled": False}]
        CHECKS["FAKE-01"] = lambda _root, _namespace, _rule: [{"object": "x", "message": "m", "severity": "error"}]
        try:
            findings = run_checks(root, namespace, catalog)
        finally:
            del CHECKS["FAKE-01"]

        assert findings[0]["severity"] == "error"

    def test_a_check_receives_the_report_namespace(self, tmp_path):
        root, namespace = parse_rdl(_write(tmp_path, "r.rdl", _RDL_2008))
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

        findings = _check_str01_current_schema(root, namespace, {})

        assert len(findings) == 1
        assert "2008" in findings[0]["message"]

    def test_passes_for_the_current_schema(self, tmp_path):
        root, namespace = _parse(tmp_path, _report(""))

        assert _check_str01_current_schema(root, namespace, {}) == []


class TestDs01SharedDataSource:
    def test_pbidataset_embedded_connection_is_exempt(self, tmp_path):
        """A bound semantic model has no shared-data-source alternative in
        Fabric -- PBIDATASET is never flagged for embedding its connection."""
        xml = _report(f"<DataSources>{_data_source('DS1', 'PBIDATASET', connect_string='Data Source=x')}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds01_shared_data_source(root, namespace, {}) == []

    def test_relational_embedded_connection_is_flagged(self, tmp_path):
        source = _data_source("DS1", "SQLAZURE", connect_string="Data Source=sql;Initial Catalog=db")
        xml = _report(f"<DataSources>{source}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds01_shared_data_source(root, namespace, {})

        assert len(findings) == 1
        assert "shared data source" in findings[0]["message"]

    def test_relational_data_source_reference_is_not_flagged(self, tmp_path):
        xml = _report(f"<DataSources>{_data_source('DS1', 'SQLAZURE', reference='Shared.rsds')}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds01_shared_data_source(root, namespace, {}) == []

    def test_embedded_password_is_flagged_without_being_echoed(self, tmp_path):
        source = _data_source("DS1", "SQLAZURE", connect_string="Data Source=sql;Password=Sup3rSecret!")
        xml = _report(f"<DataSources>{source}</DataSources>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds01_shared_data_source(root, namespace, {})

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

        assert _check_ds02_unused_datasets(root, namespace, {}) == []

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

        assert _check_ds02_unused_datasets(root, namespace, {}) == []

    def test_a_dataset_referenced_nowhere_is_flagged(self, tmp_path):
        dataset = _dataset("Orphan", "DS1", "EVALUATE SUMMARIZECOLUMNS('T'[C])")
        xml = _report(f"<DataSets>{dataset}</DataSets><Body />")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds02_unused_datasets(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Orphan"


class TestDs05NoSelectStar:
    def test_flags_a_bare_dax_evaluate_of_a_whole_table(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE 'Sales'") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_ds05_no_select_star(root, namespace, {})

        assert len(findings) == 1
        assert "SELECT *" in findings[0]["message"]

    def test_does_not_flag_a_projected_dax_query(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('Sales'[Amount])") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace, {}) == []

    def test_flags_sql_select_star(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT * FROM Sales") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert len(_check_ds05_no_select_star(root, namespace, {})) == 1

    def test_does_not_flag_projected_sql(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT Amount FROM Sales") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace, {}) == []

    def test_power_query_source_is_not_applicable(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PQO')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT * FROM whatever Power Query emits") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace, {}) == []


class TestDs07PreferStoredProcedures:
    def test_flags_inline_sql_text(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "SELECT Amount FROM Sales") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert len(_check_ds07_prefer_stored_procedures(root, namespace, {})) == 1

    def test_does_not_flag_a_stored_procedure(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>"
            + _dataset("Sales", "DS1", "usp_GetSales", command_type="StoredProcedure")
            + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds07_prefer_stored_procedures(root, namespace, {}) == []

    def test_does_not_apply_to_pbidataset(self, tmp_path):
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('Sales'[Amount])") + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_ds07_prefer_stored_procedures(root, namespace, {}) == []


# --------------------------------------------------------------------------- #
# Query pushdown rules (QRY-01 .. QRY-07)
# --------------------------------------------------------------------------- #


class TestQry01FilterInQuery:
    def test_flags_a_dataset_level_filter(self, tmp_path):
        dataset = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            '<Filters><Filter><FilterExpression>=Fields!X.Value</FilterExpression></Filter></Filters>'
            "</DataSet>"
        )
        xml = _report(f"<DataSets>{dataset}</DataSets>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry01_filter_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Sales"

    def test_flags_a_tablix_level_filter(self, tmp_path):
        xml = _report(
            '<Body><ReportItems><Tablix Name="T1">'
            '<Filters><Filter><FilterExpression>=Fields!X.Value</FilterExpression></Filter></Filters>'
            "</Tablix></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry01_filter_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "T1"

    def test_no_filters_passes(self, tmp_path):
        dataset = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query></DataSet>"
        )
        xml = _report(f"<DataSets>{dataset}</DataSets>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry01_filter_in_query(root, namespace, {}) == []


class TestQry02NoCalculatedFields:
    def test_flags_a_field_with_a_value_expression(self, tmp_path):
        dataset = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            '<Fields><Field Name="Total"><Value>=Fields!A.Value + Fields!B.Value</Value></Field></Fields>'
            "</DataSet>"
        )
        xml = _report(f"<DataSets>{dataset}</DataSets>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry02_no_calculated_fields(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Total"

    def test_a_plain_datafield_passes(self, tmp_path):
        dataset = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            '<Fields><Field Name="Amount"><DataField>Sales[Amount]</DataField></Field></Fields>'
            "</DataSet>"
        )
        xml = _report(f"<DataSets>{dataset}</DataSets>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry02_no_calculated_fields(root, namespace, {}) == []


class TestQry03AggregateInQuery:
    def test_flags_an_aggregate_scoped_to_a_whole_dataset(self, tmp_path):
        xml = _report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>'
            '=Sum(Fields!Amount.Value, "Sales")'
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry03_aggregate_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Sales"

    def test_an_ordinary_group_footer_sum_is_not_flagged(self, tmp_path):
        """=Sum(Fields!X.Value) with no dataset-scope argument is the normal,
        correct way RDL shows a group/report total -- not the anti-pattern."""
        xml = _report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>'
            "=Sum(Fields!Amount.Value)"
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry03_aggregate_in_query(root, namespace, {}) == []

    def test_deduplicates_the_same_dataset_scoped_aggregate(self, tmp_path):
        xml = _report(
            '<Body><ReportItems>'
            '<Textbox Name="Tb1"><Value>=Sum(Fields!Amount.Value, "Sales")</Value></Textbox>'
            '<Textbox Name="Tb2"><Value>=Sum(Fields!Amount.Value, "Sales")</Value></Textbox>'
            "</ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert len(_check_qry03_aggregate_in_query(root, namespace, {})) == 1


class TestQry04SortInQuery:
    def test_flags_an_explicit_group_sort(self, tmp_path):
        xml = _report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers>'
            '<TablixMember><Group Name="G1">'
            "<SortExpressions><SortExpression><Value>=Fields!X.Value</Value></SortExpression></SortExpressions>"
            "</Group></TablixMember></TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry04_sort_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "G1"

    def test_no_sort_expressions_passes(self, tmp_path):
        xml = _report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers>'
            '<TablixMember><Group Name="G1" /></TablixMember>'
            "</TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry04_sort_in_query(root, namespace, {}) == []


class TestQry05ConvertTypesInQuery:
    def test_a_conversion_repeated_on_the_same_field_reports_once(self, tmp_path):
        xml = _report(
            '<Body><ReportItems>'
            '<Textbox Name="Tb1"><Value>=CDate(Fields!Created.Value)</Value></Textbox>'
            '<Textbox Name="Tb2"><Value>=CDate(Fields!Created.Value)</Value></Textbox>'
            "</ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry05_convert_types_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Fields!Created.Value"

    def test_a_single_occurrence_is_not_flagged(self, tmp_path):
        xml = _report(
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=CDate(Fields!Created.Value)</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry05_convert_types_in_query(root, namespace, {}) == []


class TestQry06JoinInQuery:
    def test_flags_a_lookup_call(self, tmp_path):
        xml = _report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>'
            "=Lookup(Fields!Key.Value, Fields!Key.Value, Fields!Amount.Value, \"Other\")"
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry06_join_in_query(root, namespace, {})

        assert len(findings) == 1

    def test_an_ordinary_expression_is_not_flagged(self, tmp_path):
        xml = _report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>=Fields!Amount.Value</Value></Textbox></ReportItems></Body>'
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry06_join_in_query(root, namespace, {}) == []


class TestQry07MoveComplexSql:
    def test_flags_command_text_over_the_catalog_threshold(self, tmp_path):
        long_sql = "\n".join(f"-- line {i}" for i in range(60))
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", long_sql) + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        findings = _check_qry07_move_complex_sql(root, namespace, {"max_lines": 50})

        assert len(findings) == 1
        assert findings[0]["object"] == "Sales"

    def test_uses_the_default_threshold_when_the_catalog_omits_it(self, tmp_path):
        short_sql = "SELECT Amount FROM Sales"
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", short_sql) + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry07_move_complex_sql(root, namespace, {}) == []

    def test_does_not_apply_to_pbidataset(self, tmp_path):
        long_dax = "EVALUATE\n" + "\n".join(f"-- line {i}" for i in range(60))
        xml = _report(
            f"<DataSources>{_data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + _dataset("Sales", "DS1", long_dax) + "</DataSets>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_qry07_move_complex_sql(root, namespace, {"max_lines": 50}) == []


# --------------------------------------------------------------------------- #
# Parameter rules (PRM-01, PRM-03, PRM-04, PRM-05)
# --------------------------------------------------------------------------- #


def _report_parameter(
    name: str, *, default: bool = True, multi_value: bool = False, nullable: bool = False, allow_blank: bool = False
) -> str:
    parts = ["<DataType>Integer</DataType>"]
    if default:
        parts.append("<DefaultValue><Values><Value>1</Value></Values></DefaultValue>")
    if allow_blank:
        parts.append("<AllowBlank>true</AllowBlank>")
    if nullable:
        parts.append("<Nullable>true</Nullable>")
    if multi_value:
        parts.append("<MultiValue>true</MultiValue>")
    return f'<ReportParameter Name="{name}">{"".join(parts)}</ReportParameter>'


class TestPrm01DefaultValue:
    def test_flags_a_parameter_with_no_default(self, tmp_path):
        param = _report_parameter("Region", default=False)
        xml = _report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_prm01_default_value(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Region"

    def test_a_parameter_with_a_default_passes(self, tmp_path):
        param = _report_parameter("Region", default=True)
        xml = _report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_prm01_default_value(root, namespace, {}) == []


class TestPrm03ParameterCount:
    def test_flags_separate_year_month_day_parameters_under_the_threshold(self, tmp_path):
        """Fires even when the total count is under max_parameters -- the
        anti-pattern is the date decomposition, not the raw count."""
        params = "".join(_report_parameter(n) for n in ("Year", "Month", "Day"))
        xml = _report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_prm03_parameter_count(root, namespace, {"max_parameters": 5})

        assert len(findings) == 1
        assert "DateTime" in findings[0]["message"]

    def test_unrelated_parameters_under_the_threshold_pass(self, tmp_path):
        params = "".join(_report_parameter(n) for n in ("Region", "Product"))
        xml = _report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_prm03_parameter_count(root, namespace, {"max_parameters": 5}) == []

    def test_flags_a_count_over_the_catalog_threshold(self, tmp_path):
        params = "".join(_report_parameter(f"P{i}") for i in range(6))
        xml = _report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_prm03_parameter_count(root, namespace, {"max_parameters": 5})

        assert any("threshold" in f["message"] for f in findings)

    def test_uses_the_default_threshold_when_the_catalog_omits_it(self, tmp_path):
        params = "".join(_report_parameter(f"P{i}") for i in range(3))
        xml = _report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_prm03_parameter_count(root, namespace, {}) == []


class TestPrm04MultivalueNullable:
    def test_flags_multivalue_with_nullable(self, tmp_path):
        param = _report_parameter("Region", multi_value=True, nullable=True)
        xml = _report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_prm04_multivalue_nullable(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Region"

    def test_multivalue_with_allow_blank_is_not_flagged(self, tmp_path):
        param = _report_parameter("Region", multi_value=True, allow_blank=True)
        xml = _report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_prm04_multivalue_nullable(root, namespace, {}) == []

    def test_multivalue_alone_is_not_flagged(self, tmp_path):
        param = _report_parameter("Region", multi_value=True)
        xml = _report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = _parse(tmp_path, xml)

        assert _check_prm04_multivalue_nullable(root, namespace, {}) == []


class TestPrm05ShowParameterValues:
    def test_flags_a_parameter_never_displayed(self, tmp_path):
        param = _report_parameter("Region")
        xml = _report(f"<ReportParameters>{param}</ReportParameters><Body />")
        root, namespace = _parse(tmp_path, xml)

        findings = _check_prm05_show_parameter_values(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Region"

    def test_a_value_reference_counts_as_displayed(self, tmp_path):
        param = _report_parameter("Region")
        xml = _report(
            f"<ReportParameters>{param}</ReportParameters>"
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=Parameters!Region.Value</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_prm05_show_parameter_values(root, namespace, {}) == []

    def test_a_label_reference_also_counts_as_displayed(self, tmp_path):
        """Given a parameter referenced as Parameters!X.Label rather than
        .Value in a textbox, PRM-05 should count it as displayed."""
        param = _report_parameter("Region")
        xml = _report(
            f"<ReportParameters>{param}</ReportParameters>"
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=Parameters!Region.Label</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = _parse(tmp_path, xml)

        assert _check_prm05_show_parameter_values(root, namespace, {}) == []
