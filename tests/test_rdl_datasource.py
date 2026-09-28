"""Contract tests for parsing a paginated report's own Power BI dataset
reference out of its local .rdl file (Paginated Report RDL Data Source
Resolution epic)."""

from __future__ import annotations

from pathlib import Path

from fab_test.scripts.playwright_validation.rdl_datasource import (
    RdlPowerBiDataSource,
    RdlReportParameter,
    parse_rdl_power_bi_datasource,
    parse_rdl_report_parameters,
    parse_rdl_report_parameters_text,
)

_PBI_DATASOURCE_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <DataSources>
    <DataSource Name="visualerrortesting_RDLSource">
      <rd:SecurityType>None</rd:SecurityType>
      <ConnectionProperties>
        <DataProvider>PBIDATASET</DataProvider>
        <ConnectString>Data Source=pbiazure://api.powerbi.com/;Identity Provider="..."
;Initial Catalog=sobe_wowvirtualserver-5bf5a7e1-65e5-4d74-944b-1ada5941a664
;Integrated Security=ClaimsToken</ConnectString>
      </ConnectionProperties>
      <rd:DataSourceID>da7cecf3-f0fa-4dc0-b5f2-da288663f04a</rd:DataSourceID>
      <rd:PowerBIWorkspaceName>visual-error-testing</rd:PowerBIWorkspaceName>
      <rd:PowerBIDatasetName>RDLSource</rd:PowerBIDatasetName>
    </DataSource>
  </DataSources>
</Report>
"""

_POWER_QUERY_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <DataSources>
    <DataSource Name="PowerQuery">
      <rd:SecurityType>None</rd:SecurityType>
      <ConnectionProperties>
        <DataProvider>PQO</DataProvider>
        <ConnectString />
      </ConnectionProperties>
      <rd:DataSourceID>4325d1d8-75ea-4f84-9ce9-da4a695ebafa</rd:DataSourceID>
    </DataSource>
  </DataSources>
</Report>
"""


def test_parses_the_dataset_id_and_workspace_name_from_a_pbidataset_source(
    tmp_path: Path,
) -> None:
    """A PBIDATASET data source's dataset ID and workspace name are extracted
    directly from the file already checked into the repository -- no GUID
    the caller has to already know and supply."""
    rdl_path = tmp_path / "PaginatedExample-BrokenRDL.rdl"
    rdl_path.write_text(_PBI_DATASOURCE_RDL, encoding="utf-8")

    result = parse_rdl_power_bi_datasource(rdl_path)

    assert result == RdlPowerBiDataSource(
        workspace_name="visual-error-testing",
        dataset_id="5bf5a7e1-65e5-4d74-944b-1ada5941a664",
    )


def test_returns_none_when_the_only_data_source_is_not_power_bi(
    tmp_path: Path,
) -> None:
    """A Power Query (PQO) data source has no Power BI dataset to resolve --
    not every paginated report is bound to a Power BI semantic model."""
    rdl_path = tmp_path / "PaginatedExample-LocalSemanticModel.rdl"
    rdl_path.write_text(_POWER_QUERY_RDL, encoding="utf-8")

    assert parse_rdl_power_bi_datasource(rdl_path) is None


def test_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    """No .rdl file at all -- nothing to parse, no exception."""
    assert parse_rdl_power_bi_datasource(tmp_path / "does-not-exist.rdl") is None


def test_returns_none_for_a_malformed_file(tmp_path: Path) -> None:
    """Invalid XML fails closed rather than raising into the caller."""
    rdl_path = tmp_path / "broken.rdl"
    rdl_path.write_text("<Report><Unclosed>", encoding="utf-8")

    assert parse_rdl_power_bi_datasource(rdl_path) is None


def test_returns_none_when_connect_string_has_no_recognizable_catalog(
    tmp_path: Path,
) -> None:
    """A PBIDATASET source whose ConnectString doesn't match the expected
    catalog pattern is not a match this parser can act on."""
    rdl_path = tmp_path / "odd.rdl"
    rdl_path.write_text(
        _PBI_DATASOURCE_RDL.replace(
            "Initial Catalog=sobe_wowvirtualserver-5bf5a7e1-65e5-4d74-944b-1ada5941a664",
            "Initial Catalog=something-else-entirely",
        ),
        encoding="utf-8",
    )

    assert parse_rdl_power_bi_datasource(rdl_path) is None


_MULTI_VALUE_PARAMETER_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <ReportParameters>
    <ReportParameter Name="ReportParameter1">
      <DataType>Integer</DataType>
      <MultiValue>true</MultiValue>
    </ReportParameter>
  </ReportParameters>
</Report>
"""

_SINGLE_VALUE_PARAMETER_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <ReportParameters>
    <ReportParameter Name="ReportParameter1">
      <DataType>Integer</DataType>
    </ReportParameter>
  </ReportParameters>
</Report>
"""

_NO_PARAMETERS_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <DataSources />
</Report>
"""


def test_parses_a_multi_value_report_parameter(tmp_path: Path) -> None:
    """<MultiValue>true</MultiValue> marks a parameter as multi-select."""
    rdl_path = tmp_path / "WithMultiFilter.rdl"
    rdl_path.write_text(_MULTI_VALUE_PARAMETER_RDL, encoding="utf-8")

    assert parse_rdl_report_parameters(rdl_path) == [
        RdlReportParameter(name="ReportParameter1", multi_value=True)
    ]


def test_parses_a_single_value_report_parameter(tmp_path: Path) -> None:
    """No <MultiValue> element means single-select."""
    rdl_path = tmp_path / "WithFilter.rdl"
    rdl_path.write_text(_SINGLE_VALUE_PARAMETER_RDL, encoding="utf-8")

    assert parse_rdl_report_parameters(rdl_path) == [
        RdlReportParameter(name="ReportParameter1", multi_value=False)
    ]


def test_returns_empty_list_when_no_parameters_declared(tmp_path: Path) -> None:
    """A report with no <ReportParameters> block has nothing to apply."""
    rdl_path = tmp_path / "LocalSemanticModel.rdl"
    rdl_path.write_text(_NO_PARAMETERS_RDL, encoding="utf-8")

    assert parse_rdl_report_parameters(rdl_path) == []


def test_report_parameters_returns_empty_list_for_a_missing_file(
    tmp_path: Path,
) -> None:
    """No .rdl file at all -- nothing to parse, no exception."""
    assert parse_rdl_report_parameters(tmp_path / "does-not-exist.rdl") == []


def test_report_parameters_returns_empty_list_for_a_malformed_file(
    tmp_path: Path,
) -> None:
    """Invalid XML fails closed rather than raising into the caller."""
    rdl_path = tmp_path / "broken.rdl"
    rdl_path.write_text("<Report><Unclosed>", encoding="utf-8")

    assert parse_rdl_report_parameters(rdl_path) == []


_QUERY_VALID_VALUES_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <DataSets>
    <DataSet Name="DefaultValues">
      <Query>
        <DataSourceName>Source</DataSourceName>
        <CommandText>EVALUATE SUMMARIZECOLUMNS('Table'[Column B])</CommandText>
      </Query>
      <Fields>
        <Field Name="Column_B">
          <DataField>Table[Column B]</DataField>
        </Field>
      </Fields>
    </DataSet>
  </DataSets>
  <ReportParameters>
    <ReportParameter Name="Single">
      <DataType>Integer</DataType>
      <ValidValues>
        <DataSetReference>
          <DataSetName>DefaultValues</DataSetName>
          <ValueField>Column_B</ValueField>
          <LabelField>Column_B</LabelField>
        </DataSetReference>
      </ValidValues>
    </ReportParameter>
    <ReportParameter Name="Static">
      <DataType>String</DataType>
      <ValidValues>
        <ParameterValues>
          <ParameterValue><Value>East</Value><Label>East</Label></ParameterValue>
          <ParameterValue><Value>West</Value><Label>West</Label></ParameterValue>
        </ParameterValues>
      </ValidValues>
      <MultiValue>true</MultiValue>
    </ReportParameter>
    <ReportParameter Name="FreeText">
      <DataType>String</DataType>
    </ReportParameter>
  </ReportParameters>
</Report>
"""


def test_report_parameters_from_text_resolve_a_query_valid_values_source() -> None:
    """Given a parameter whose valid values come from a dataset, should name
    that dataset's query and the column its value field reads -- the key the
    query's own result rows are returned under."""
    parameters = parse_rdl_report_parameters_text(_QUERY_VALID_VALUES_RDL)

    single = parameters[0]
    assert single == RdlReportParameter(
        name="Single",
        multi_value=False,
        values_query="EVALUATE SUMMARIZECOLUMNS('Table'[Column B])",
        value_column="Table[Column B]",
    )


def test_report_parameters_from_text_read_a_static_valid_values_list() -> None:
    """Given a static valid-values list, should carry the values themselves --
    nothing needs to be queried to know them."""
    parameters = parse_rdl_report_parameters_text(_QUERY_VALID_VALUES_RDL)

    assert parameters[1] == RdlReportParameter(
        name="Static", multi_value=True, static_values=("East", "West")
    )


def test_report_parameters_from_text_leave_a_free_text_parameter_unsourced() -> None:
    """Given a parameter with no valid values at all, should report it with no
    source, so the caller knows there is no value it can pick."""
    parameters = parse_rdl_report_parameters_text(_QUERY_VALID_VALUES_RDL)

    assert parameters[2] == RdlReportParameter(name="FreeText", multi_value=False)


def test_report_parameters_from_text_is_empty_for_malformed_xml() -> None:
    """A definition that cannot be parsed yields no parameters, not a crash."""
    assert parse_rdl_report_parameters_text("<Report") == []


def test_report_parameters_from_a_file_and_its_text_agree(tmp_path: Path) -> None:
    """The local-file path and the downloaded-definition path are one parser."""
    rdl = tmp_path / "Report.rdl"
    rdl.write_text(_QUERY_VALID_VALUES_RDL, encoding="utf-8")

    assert parse_rdl_report_parameters(rdl) == parse_rdl_report_parameters_text(
        _QUERY_VALID_VALUES_RDL
    )
