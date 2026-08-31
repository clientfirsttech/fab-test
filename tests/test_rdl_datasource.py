"""Contract tests for parsing a paginated report's own Power BI dataset
reference out of its local .rdl file (Paginated Report RDL Data Source
Resolution epic)."""

from __future__ import annotations

from pathlib import Path

from fabric_ci_cd_dataops.scripts.playwright_validation.rdl_datasource import (
    RdlPowerBiDataSource,
    parse_rdl_power_bi_datasource,
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
