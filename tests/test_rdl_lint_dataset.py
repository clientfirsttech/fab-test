"""Tier B dataset and field checks (DS-03, DS-04, DS-06, STR-03, PRM-02)."""

import pytest

from fab_test.scripts._rdl_checks_dataset import (
    _check_ds03_static_parameter_lists,
    _check_ds04_share_one_dataset,
    _check_ds06_orphan_query_columns,
)
from tests._rdl_lint_fixtures import data_source, dataset, parse, report

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


def _parameter_from(dataset_name: str, *, element: str = "ValidValues") -> str:
    return (
        '<ReportParameters><ReportParameter Name="Region"><DataType>String</DataType>'
        f"<{element}><DataSetReference><DataSetName>{dataset_name}</DataSetName>"
        f"<ValueField>Region</ValueField></DataSetReference></{element}>"
        "</ReportParameter></ReportParameters>"
    )


def _report(provider: str, command_text: str, *, element: str = "ValidValues") -> str:
    return report(
        f"<DataSources>{data_source('DS1', provider)}</DataSources>"
        f"<DataSets>{dataset('Regions', 'DS1', command_text)}</DataSets>"
        + _parameter_from("Regions", element=element)
    )


class TestDs03StaticParameterLists:
    def test_flags_valid_values_from_a_dax_datatable(self, tmp_path):
        root, namespace = parse(
            tmp_path, _report("PBIDATASET", 'EVALUATE DATATABLE("Region", STRING, {{"East"}, {"West"}})')
        )

        findings = _check_ds03_static_parameter_lists(root, namespace, {})

        assert [f["object"] for f in findings] == ["Region › Regions"]

    def test_flags_a_sql_list_with_no_table(self, tmp_path):
        root, namespace = parse(
            tmp_path, _report("SQL", "SELECT 'East' AS Region UNION ALL SELECT 'West -- from nowhere'")
        )

        assert len(_check_ds03_static_parameter_lists(root, namespace, {})) == 1

    def test_flags_power_query_enter_data(self, tmp_path):
        mashup = '{"MashupDocument":"Source = Table.FromRows(Json.Document(Binary.Decompress(Binary.FromText('
        root, namespace = parse(tmp_path, _report("PQO", mashup))

        assert len(_check_ds03_static_parameter_lists(root, namespace, {})) == 1

    def test_flags_a_default_value_list_too(self, tmp_path):
        root, namespace = parse(
            tmp_path, _report("SQL", "SELECT 'East' AS Region", element="DefaultValue")
        )

        assert len(_check_ds03_static_parameter_lists(root, namespace, {})) == 1

    def test_a_list_read_from_a_table_is_not_flagged(self, tmp_path):
        root, namespace = parse(tmp_path, _report("SQL", "SELECT DISTINCT Region FROM dbo.Sales"))

        assert _check_ds03_static_parameter_lists(root, namespace, {}) == []

    def test_a_dax_list_read_from_the_model_is_not_flagged(self, tmp_path):
        root, namespace = parse(tmp_path, _report("PBIDATASET", "EVALUATE VALUES(Geography[Region])"))

        assert _check_ds03_static_parameter_lists(root, namespace, {}) == []


def _with_fields(provider: str, command_text: str, data_fields: list[str], *, command_type: str = "") -> str:
    fields = "".join(f'<Field Name="F{i}"><DataField>{f}</DataField></Field>' for i, f in enumerate(data_fields))
    ds = dataset("Main", "DS1", command_text, command_type=command_type)
    ds = ds.replace("</DataSet>", f"<Fields>{fields}</Fields></DataSet>")
    return report(f"<DataSources>{data_source('DS1', provider)}</DataSources><DataSets>{ds}</DataSets>")


class TestDs06OrphanQueryColumns:
    def test_flags_a_dax_column_no_field_reads(self, tmp_path):
        xml = _with_fields(
            "PBIDATASET", "EVALUATE SUMMARIZECOLUMNS('Sales'[Region], Sales[Year], \"Total\", [Amount])",
            ["Sales[Region]", "[Total]"],
        )
        root, namespace = parse(tmp_path, xml)

        assert [f["object"] for f in _check_ds06_orphan_query_columns(root, namespace, {})] == ["Main › Sales[Year]"]

    def test_flags_a_dax_named_expression_no_field_reads(self, tmp_path):
        xml = _with_fields("PBIDATASET", 'EVALUATE SUMMARIZECOLUMNS(Sales[Region], "Total", SUM(Sales[Amount]))',
                           ["Sales[Region]"])
        root, namespace = parse(tmp_path, xml)

        assert [f["object"] for f in _check_ds06_orphan_query_columns(root, namespace, {})] == ["Main › Total"]

    def test_dax_filter_arguments_are_not_columns(self, tmp_path):
        xml = _with_fields(
            "PBIDATASET", "EVALUATE SUMMARIZECOLUMNS(Sales[Region], FILTER(VALUES(Sales[Year]), Sales[Year] > 2000))",
            ["Sales[Region]"],
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds06_orphan_query_columns(root, namespace, {}) == []

    def test_flags_a_sql_column_no_field_reads(self, tmp_path):
        xml = _with_fields(
            "SQL", "SELECT s.Region, SUM(s.Amount) AS Total, [Year] FROM dbo.Sales AS s GROUP BY s.Region, [Year]",
            ["Region", "Total"],
        )
        root, namespace = parse(tmp_path, xml)

        assert [f["object"] for f in _check_ds06_orphan_query_columns(root, namespace, {})] == ["Main › Year"]

    def test_a_subquery_from_does_not_end_the_select_list(self, tmp_path):
        xml = _with_fields(
            "SQL", "SELECT Region, (SELECT MAX(Amount) FROM dbo.Sales) AS Top FROM dbo.Regions", ["Region", "Top"]
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_ds06_orphan_query_columns(root, namespace, {}) == []

    def test_select_star_and_stored_procedures_are_not_judged(self, tmp_path):
        star = _with_fields("SQL", "SELECT * FROM dbo.Sales", ["Region"])
        proc = _with_fields("SQL", "dbo.GetSales", ["Region"], command_type="StoredProcedure")

        assert _check_ds06_orphan_query_columns(*parse(tmp_path, star), {}) == []
        assert _check_ds06_orphan_query_columns(*parse(tmp_path, proc), {}) == []

    def test_every_column_read_passes(self, tmp_path):
        xml = _with_fields("SQL", "SELECT Region, Amount FROM dbo.Sales", ["region", "Amount"])
        root, namespace = parse(tmp_path, xml)

        assert _check_ds06_orphan_query_columns(root, namespace, {}) == []


_QUERY = "SELECT Region, Amount FROM dbo.Sales WHERE Year = {year}"


def _two_regions(first: str, second: str, *, second_source: str = "DS1", second_region: bool = True) -> str:
    regions = '<Tablix Name="T1"><DataSetName>A</DataSetName></Tablix>'
    if second_region:
        regions += '<Chart Name="C1"><DataSetName>B</DataSetName></Chart>'
    return report(
        f"<DataSources>{data_source('DS1', 'SQL')}{data_source('DS2', 'SQL')}</DataSources>"
        f"<DataSets>{dataset('A', 'DS1', first)}{dataset('B', second_source, second)}</DataSets>"
        f"<Body><ReportItems>{regions}</ReportItems></Body>"
    )


class TestDs04ShareOneDataset:
    def test_flags_near_identical_queries_feeding_two_regions(self, tmp_path):
        root, namespace = parse(tmp_path, _two_regions(_QUERY.format(year=2024), _QUERY.format(year=2025)))

        findings = _check_ds04_share_one_dataset(root, namespace, {})

        assert [f["object"] for f in findings] == ["A ≈ B"]

    def test_different_queries_pass(self, tmp_path):
        root, namespace = parse(tmp_path, _two_regions(_QUERY.format(year=2024), "SELECT Name FROM dbo.Customers"))

        assert _check_ds04_share_one_dataset(root, namespace, {}) == []

    def test_the_same_query_on_another_source_passes(self, tmp_path):
        xml = _two_regions(_QUERY.format(year=2024), _QUERY.format(year=2024), second_source="DS2")
        root, namespace = parse(tmp_path, xml)

        assert _check_ds04_share_one_dataset(root, namespace, {}) == []

    def test_a_dataset_feeding_no_region_is_not_judged(self, tmp_path):
        xml = _two_regions(_QUERY.format(year=2024), _QUERY.format(year=2024), second_region=False)
        root, namespace = parse(tmp_path, xml)

        assert _check_ds04_share_one_dataset(root, namespace, {}) == []

    def test_the_threshold_comes_from_the_catalog(self, tmp_path):
        root, namespace = parse(tmp_path, _two_regions(_QUERY.format(year=2024), _QUERY.format(year=2025)))

        assert _check_ds04_share_one_dataset(root, namespace, {"min_similarity": 1.0}) == []
