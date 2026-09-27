"""Unit tests for _rdl_lint.py's structure and data-source rules
(STR-01, DS-01, DS-02, DS-05, DS-07). Split out of test_rdl_lint.py
(Test Module Split precedent) -- see _rdl_lint_fixtures.py for the
shared XML builders and why their shape matters.

    pytest tests/test_rdl_lint_structure.py
"""

import pytest

from fab_test.scripts._rdl_lint import (
    _check_ds01_shared_data_source,
    _check_ds02_unused_datasets,
    _check_ds05_no_select_star,
    _check_ds07_prefer_stored_procedures,
    _check_str01_current_schema,
)
from tests._rdl_lint_fixtures import data_source, dataset, parse, report

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


class TestStr01CurrentSchema:
    def test_flags_an_older_schema(self, tmp_path):
        root, namespace = parse(
            tmp_path, report("", namespace="http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition")
        )

        findings = _check_str01_current_schema(root, namespace, {})

        assert len(findings) == 1
        assert "2008" in findings[0]["message"]

    def test_passes_for_the_current_schema(self, tmp_path):
        root, namespace = parse(tmp_path, report(""))

        assert _check_str01_current_schema(root, namespace, {}) == []


class TestDs01SharedDataSource:
    def test_pbidataset_embedded_connection_is_exempt(self, tmp_path):
        """A bound semantic model has no shared-data-source alternative in
        Fabric -- PBIDATASET is never flagged for embedding its connection."""
        source = data_source("DS1", "PBIDATASET", connect_string="Data Source=x")
        xml = report(f"<DataSources>{source}</DataSources>")
        root, namespace = parse(tmp_path, xml)

        assert _check_ds01_shared_data_source(root, namespace, {}) == []

    def test_relational_embedded_connection_is_flagged(self, tmp_path):
        source = data_source("DS1", "SQLAZURE", connect_string="Data Source=sql;Initial Catalog=db")
        xml = report(f"<DataSources>{source}</DataSources>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_ds01_shared_data_source(root, namespace, {})

        assert len(findings) == 1
        assert "shared data source" in findings[0]["message"]

    def test_relational_data_source_reference_is_not_flagged(self, tmp_path):
        source = data_source("DS1", "SQLAZURE", reference="Shared.rsds")
        xml = report(f"<DataSources>{source}</DataSources>")
        root, namespace = parse(tmp_path, xml)

        assert _check_ds01_shared_data_source(root, namespace, {}) == []

    def test_embedded_password_is_flagged_without_being_echoed(self, tmp_path):
        source = data_source("DS1", "SQLAZURE", connect_string="Data Source=sql;Password=Sup3rSecret!")
        xml = report(f"<DataSources>{source}</DataSources>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_ds01_shared_data_source(root, namespace, {})

        messages = " ".join(f["message"] for f in findings)
        assert "password" in messages.lower()
        assert "Sup3rSecret!" not in messages


class TestDs02UnusedDatasets:
    def test_a_dataset_bound_to_a_tablix_is_used(self, tmp_path):
        xml = report(
            "<DataSets>" + dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('T'[C])") + "</DataSets>"
            '<Body><ReportItems><Tablix Name="T1"><DataSetName>Sales</DataSetName></Tablix></ReportItems></Body>'
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds02_unused_datasets(root, namespace, {}) == []

    def test_a_dataset_referenced_only_in_an_expression_is_used(self, tmp_path):
        """Given a dataset whose name appears only inside an expression
        (e.g. Lookup(..., "Sales")), DS-02 should treat it as used."""
        xml = report(
            "<DataSets>" + dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('T'[C])") + "</DataSets>"
            '<Body><ReportItems><Textbox Name="T1"><Value>'
            '=Lookup(Fields!Key.Value, Fields!Key.Value, Fields!Amount.Value, "Sales")'
            "</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds02_unused_datasets(root, namespace, {}) == []

    def test_a_dataset_referenced_nowhere_is_flagged(self, tmp_path):
        ds = dataset("Orphan", "DS1", "EVALUATE SUMMARIZECOLUMNS('T'[C])")
        xml = report(f"<DataSets>{ds}</DataSets><Body />")
        root, namespace = parse(tmp_path, xml)

        findings = _check_ds02_unused_datasets(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Orphan"


class TestDs05NoSelectStar:
    def test_flags_a_bare_dax_evaluate_of_a_whole_table(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", "EVALUATE 'Sales'") + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_ds05_no_select_star(root, namespace, {})

        assert len(findings) == 1
        assert "SELECT *" in findings[0]["message"]

    def test_does_not_flag_a_projected_dax_query(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('Sales'[Amount])") + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace, {}) == []

    def test_flags_sql_select_star(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", "SELECT * FROM Sales") + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert len(_check_ds05_no_select_star(root, namespace, {})) == 1

    def test_does_not_flag_projected_sql(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", "SELECT Amount FROM Sales") + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace, {}) == []

    def test_power_query_source_is_not_applicable(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'PQO')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", "SELECT * FROM whatever Power Query emits") + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds05_no_select_star(root, namespace, {}) == []


class TestDs07PreferStoredProcedures:
    def test_flags_inline_sql_text(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", "SELECT Amount FROM Sales") + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert len(_check_ds07_prefer_stored_procedures(root, namespace, {})) == 1

    def test_does_not_flag_a_stored_procedure(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'SQLAZURE')}</DataSources>"
            "<DataSets>"
            + dataset("Sales", "DS1", "usp_GetSales", command_type="StoredProcedure")
            + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds07_prefer_stored_procedures(root, namespace, {}) == []

    def test_does_not_apply_to_pbidataset(self, tmp_path):
        xml = report(
            f"<DataSources>{data_source('DS1', 'PBIDATASET')}</DataSources>"
            "<DataSets>" + dataset("Sales", "DS1", "EVALUATE SUMMARIZECOLUMNS('Sales'[Amount])") + "</DataSets>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds07_prefer_stored_procedures(root, namespace, {}) == []
