"""Unit tests for _rdl_lint.py's query pushdown rules (QRY-01 .. QRY-07).
Split out of test_rdl_lint.py (Test Module Split precedent) -- see
_rdl_lint_fixtures.py for the shared XML builders.

    pytest tests/test_rdl_lint_query.py
"""

import pytest

from fab_test.scripts._rdl_lint import (
    _check_qry01_filter_in_query,
    _check_qry02_no_calculated_fields,
    _check_qry03_aggregate_in_query,
    _check_qry04_sort_in_query,
    _check_qry05_convert_types_in_query,
    _check_qry06_join_in_query,
    _check_qry07_move_complex_sql,
)
from tests._rdl_lint_fixtures import data_source, dataset, parse, report

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


class TestQry01FilterInQuery:
    def test_flags_a_dataset_level_filter(self, tmp_path):
        ds = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            '<Filters><Filter><FilterExpression>=Fields!X.Value</FilterExpression></Filter></Filters>'
            "</DataSet>"
        )
        xml = report(f"<DataSets>{ds}</DataSets>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry01_filter_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Sales"

    def test_flags_a_tablix_level_filter(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1">'
            '<Filters><Filter><FilterExpression>=Fields!X.Value</FilterExpression></Filter></Filters>'
            "</Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry01_filter_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "T1"

    def test_no_filters_passes(self, tmp_path):
        ds = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query></DataSet>"
        )
        xml = report(f"<DataSets>{ds}</DataSets>")
        root, namespace = parse(tmp_path, xml)

        assert _check_qry01_filter_in_query(root, namespace, {}) == []


class TestQry02NoCalculatedFields:
    def test_flags_a_field_with_a_value_expression(self, tmp_path):
        ds = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            '<Fields><Field Name="Total"><Value>=Fields!A.Value + Fields!B.Value</Value></Field></Fields>'
            "</DataSet>"
        )
        xml = report(f"<DataSets>{ds}</DataSets>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry02_no_calculated_fields(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Sales › Total"

    def test_a_plain_datafield_passes(self, tmp_path):
        ds = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            '<Fields><Field Name="Amount"><DataField>Sales[Amount]</DataField></Field></Fields>'
            "</DataSet>"
        )
        xml = report(f"<DataSets>{ds}</DataSets>")
        root, namespace = parse(tmp_path, xml)

        assert _check_qry02_no_calculated_fields(root, namespace, {}) == []


class TestQry03AggregateInQuery:
    def test_flags_an_aggregate_scoped_to_a_whole_dataset(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>'
            '=Sum(Fields!Amount.Value, "Sales")'
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry03_aggregate_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Sales"

    def test_an_ordinary_group_footer_sum_is_not_flagged(self, tmp_path):
        """=Sum(Fields!X.Value) with no dataset-scope argument is the normal,
        correct way RDL shows a group/report total -- not the anti-pattern."""
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>'
            "=Sum(Fields!Amount.Value)"
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_qry03_aggregate_in_query(root, namespace, {}) == []

    def test_deduplicates_the_same_dataset_scoped_aggregate(self, tmp_path):
        xml = report(
            '<Body><ReportItems>'
            '<Textbox Name="Tb1"><Value>=Sum(Fields!Amount.Value, "Sales")</Value></Textbox>'
            '<Textbox Name="Tb2"><Value>=Sum(Fields!Amount.Value, "Sales")</Value></Textbox>'
            "</ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert len(_check_qry03_aggregate_in_query(root, namespace, {})) == 1


class TestQry04SortInQuery:
    def test_flags_an_explicit_group_sort(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers>'
            '<TablixMember><Group Name="G1" />'
            "<SortExpressions><SortExpression><Value>=Fields!X.Value</Value></SortExpression></SortExpressions>"
            "</TablixMember></TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry04_sort_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "T1 › G1"

    def test_no_sort_expressions_passes(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers>'
            '<TablixMember><Group Name="G1" /></TablixMember>'
            "</TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_qry04_sort_in_query(root, namespace, {}) == []


class TestQry05ConvertTypesInQuery:
    def test_a_conversion_repeated_on_the_same_field_reports_once(self, tmp_path):
        xml = report(
            '<Body><ReportItems>'
            '<Textbox Name="Tb1"><Value>=CDate(Fields!Created.Value)</Value></Textbox>'
            '<Textbox Name="Tb2"><Value>=CDate(Fields!Created.Value)</Value></Textbox>'
            "</ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry05_convert_types_in_query(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Fields!Created.Value"

    def test_a_single_occurrence_is_not_flagged(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=CDate(Fields!Created.Value)</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_qry05_convert_types_in_query(root, namespace, {}) == []


class TestQry06JoinInQuery:
    def test_flags_a_lookup_call(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>'
            "=Lookup(Fields!Key.Value, Fields!Key.Value, Fields!Amount.Value, \"Other\")"
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry06_join_in_query(root, namespace, {})

        assert len(findings) == 1

    def test_an_ordinary_expression_is_not_flagged(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1"><Value>=Fields!Amount.Value</Value></Textbox></ReportItems></Body>'
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_qry06_join_in_query(root, namespace, {}) == []


class TestQry07MoveComplexSql:
    def test_flags_command_text_over_the_catalog_threshold(self, tmp_path):
        long_sql = "\n".join(f"-- line {i}" for i in range(60))
        xml = report(
            f"<DataSources>{data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", long_sql) + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_qry07_move_complex_sql(root, namespace, {"max_lines": 50})

        assert len(findings) == 1
        assert findings[0]["object"] == "Sales"

    def test_uses_the_default_threshold_when_the_catalog_omits_it(self, tmp_path):
        short_sql = "SELECT Amount FROM Sales"
        xml = report(
            f"<DataSources>{data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", short_sql) + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_qry07_move_complex_sql(root, namespace, {}) == []

    def test_does_not_apply_to_pbidataset(self, tmp_path):
        long_dax = "EVALUATE\n" + "\n".join(f"-- line {i}" for i in range(60))
        xml = report(
            f"<DataSources>{data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", long_dax) + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_qry07_move_complex_sql(root, namespace, {"max_lines": 50}) == []
