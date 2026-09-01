"""Contract tests for build_playwright_command's --pages/--roles passthrough.

Playwright Test Matrix Discovery epic: `fab-test playwright` discovers pages,
bookmarks, and roles by default, and the top-level `--pages none`/`--roles
none` overrides must reach the `invoke_playwright` subprocess command line.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fab_test.scripts.fab_test_registry import build_playwright_command


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "playwright_env_file": None,
        "environment": "",
        "workspace_id": "",
        "impact_manifest": None,
        "dataset_id": "",
        "pages": "auto",
        "roles": "auto",
        "report_type": "",
        "report_parameters": "",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_default_pages_and_roles_are_not_passed_through(tmp_path: Path) -> None:
    """The 'auto' default is invoke_playwright's own default, so it is left
    off the command line rather than repeated on every invocation."""
    cmd = build_playwright_command(Path("ThinReport"), _args(), tmp_path)

    assert "--pages" not in cmd
    assert "--roles" not in cmd


def test_pages_none_is_forwarded_to_invoke_playwright(tmp_path: Path) -> None:
    """--pages none reaches the wrapper so discovery can be turned off."""
    cmd = build_playwright_command(Path("ThinReport"), _args(pages="none"), tmp_path)

    assert "--pages" in cmd
    assert cmd[cmd.index("--pages") + 1] == "none"


def test_roles_none_is_forwarded_to_invoke_playwright(tmp_path: Path) -> None:
    """--roles none reaches the wrapper so role discovery can be turned off."""
    cmd = build_playwright_command(Path("ThinReport"), _args(roles="none"), tmp_path)

    assert "--roles" in cmd
    assert cmd[cmd.index("--roles") + 1] == "none"


def test_report_type_is_derived_from_a_local_report_folders_own_suffix(
    tmp_path: Path,
) -> None:
    """A discovered *.Report folder tells the subprocess its type directly --
    no need to make it ask Fabric something the outer CLI already knows."""
    cmd = build_playwright_command(Path("ThinReport.Report"), _args(), tmp_path)

    assert "--report-type" in cmd
    assert cmd[cmd.index("--report-type") + 1] == "report"


def test_report_type_is_derived_from_a_local_rdl_files_suffix(
    tmp_path: Path,
) -> None:
    """A discovered .rdl file (a paginated report's real local artifact
    shape -- a flat file, not a *.PaginatedReport folder) is told its type
    too."""
    cmd = build_playwright_command(Path("Invoice RDL.rdl"), _args(), tmp_path)

    assert "--report-type" in cmd
    assert cmd[cmd.index("--report-type") + 1] == "paginated"


def test_report_type_is_left_unset_for_a_synthetic_remote_target(
    tmp_path: Path,
) -> None:
    """A synthetic remote target (no local folder matched) has no suffix to
    derive a type from -- left for the subprocess to auto-detect, exactly
    like a bare --artifact NAME always has."""
    cmd = build_playwright_command(Path("Invoice RDL"), _args(), tmp_path)

    assert "--report-type" not in cmd


_PBI_DATASOURCE_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <DataSources>
    <DataSource Name="visualerrortesting_RDLSource">
      <ConnectionProperties>
        <DataProvider>PBIDATASET</DataProvider>
        <ConnectString>Data Source=pbiazure://api.powerbi.com/;
Initial Catalog=sobe_wowvirtualserver-5bf5a7e1-65e5-4d74-944b-1ada5941a664</ConnectString>
      </ConnectionProperties>
      <rd:PowerBIWorkspaceName>visual-error-testing</rd:PowerBIWorkspaceName>
    </DataSource>
  </DataSources>
</Report>
"""


def test_dataset_id_and_workspace_are_derived_from_a_local_rdl_files_own_datasource(
    tmp_path: Path,
) -> None:
    """A discovered .rdl file's own PBIDATASET data source names its dataset
    and workspace directly -- the caller never has to already know and
    supply those GUIDs by hand."""
    rdl = tmp_path / "Invoice RDL.rdl"
    rdl.write_text(_PBI_DATASOURCE_RDL, encoding="utf-8")

    cmd = build_playwright_command(rdl, _args(), tmp_path)

    assert cmd[cmd.index("--dataset-id") + 1] == "5bf5a7e1-65e5-4d74-944b-1ada5941a664"
    assert cmd[cmd.index("--dataset-workspace-id") + 1] == "visual-error-testing"


def test_explicit_dataset_id_flag_overrides_the_rdl_files_own_datasource(
    tmp_path: Path,
) -> None:
    """An explicit --dataset-id wins even when the .rdl file also names one
    -- mirrors --report-type's override precedence."""
    rdl = tmp_path / "Invoice RDL.rdl"
    rdl.write_text(_PBI_DATASOURCE_RDL, encoding="utf-8")

    cmd = build_playwright_command(
        rdl, _args(dataset_id="explicit-dataset-id"), tmp_path
    )

    assert cmd[cmd.index("--dataset-id") + 1] == "explicit-dataset-id"
    assert "--dataset-workspace-id" not in cmd


def test_dataset_override_is_not_derived_for_a_non_rdl_artifact(tmp_path: Path) -> None:
    """A .Report folder is never parsed for an RDL data source."""
    cmd = build_playwright_command(Path("ThinReport.Report"), _args(), tmp_path)

    assert "--dataset-id" not in cmd
    assert "--dataset-workspace-id" not in cmd


def test_dataset_override_is_empty_when_the_rdl_has_no_power_bi_datasource(
    tmp_path: Path,
) -> None:
    """An .rdl file with no PBIDATASET source (e.g. Power Query) has nothing
    to derive -- not every paginated report is bound to a Power BI dataset."""
    rdl = tmp_path / "Invoice RDL.rdl"
    rdl.write_text("<Report><DataSources /></Report>", encoding="utf-8")

    cmd = build_playwright_command(rdl, _args(), tmp_path)

    assert "--dataset-id" not in cmd
    assert "--dataset-workspace-id" not in cmd


def test_explicit_report_type_flag_overrides_the_folder_suffix(tmp_path: Path) -> None:
    """An explicit --report-type wins even against a folder whose own suffix
    disagrees -- mirrors --dataset-id's override pattern."""
    cmd = build_playwright_command(
        Path("ThinReport.Report"), _args(report_type="paginated"), tmp_path
    )

    assert cmd[cmd.index("--report-type") + 1] == "paginated"


_PARAMETERIZED_RDL = """<?xml version="1.0" encoding="utf-8"?>
<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition" xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">
  <ReportParameters>
    <ReportParameter Name="ReportParameter1">
      <DataType>Integer</DataType>
      <MultiValue>true</MultiValue>
    </ReportParameter>
  </ReportParameters>
</Report>
"""


def test_report_parameters_are_derived_from_a_local_rdl_files_own_declarations(
    tmp_path: Path,
) -> None:
    """A discovered .rdl file's own <ReportParameters> block is passed
    through as JSON -- the caller never has to already know what a report
    prompts for."""
    rdl = tmp_path / "Invoice RDL.rdl"
    rdl.write_text(_PARAMETERIZED_RDL, encoding="utf-8")

    cmd = build_playwright_command(rdl, _args(), tmp_path)

    assert "--report-parameters" in cmd
    payload = json.loads(cmd[cmd.index("--report-parameters") + 1])
    assert payload == [{"name": "ReportParameter1", "multi_value": True}]


def test_report_parameters_are_absent_for_a_non_rdl_artifact(tmp_path: Path) -> None:
    """A .Report folder is never parsed for RDL report parameters."""
    cmd = build_playwright_command(Path("ThinReport.Report"), _args(), tmp_path)

    assert "--report-parameters" not in cmd


def test_report_parameters_are_absent_when_the_rdl_declares_none(
    tmp_path: Path,
) -> None:
    """An .rdl file with no <ReportParameters> block has nothing to pass."""
    rdl = tmp_path / "Invoice RDL.rdl"
    rdl.write_text("<Report><DataSources /></Report>", encoding="utf-8")

    cmd = build_playwright_command(rdl, _args(), tmp_path)

    assert "--report-parameters" not in cmd
