"""Shared, stateless XML-builder helpers for the RDL rule engine's tests.

Split out of test_rdl_lint.py (Test Module Split precedent, this project's
own aidd-module-budgets skill) once that file crossed the test-module hard
budget -- one rule family per test module, all sharing these builders
rather than each re-deriving them. Pure construction only: no fixtures that
carry state between tests, matching aidd-tdd's locality constraint.

Fixture shape mirrors a real Report Builder-authored .rdl
(.fabric/artifacts/PaginatedExample-WithFilter.rdl), confirmed live:
DataSet/Query has direct children DataSourceName, then CommandText --
CommandType/CommandText also appear nested inside rd:DesignerState under a
*different* namespace, which parse_rdl's stripping collapses to the same
local names, so a real check must never findall(".//CommandText") to mean
"this dataset's own query" -- see _dataset()'s decoy DesignerState below.
"""

from pathlib import Path

from fab_test.scripts._rdl_lint import CURRENT_RDL_NAMESPACE, parse_rdl


def write_rdl(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def parse(tmp_path: Path, xml: str):
    return parse_rdl(write_rdl(tmp_path, "r.rdl", xml))


def report(body: str, *, namespace: str = CURRENT_RDL_NAMESPACE) -> str:
    # rd: is declared because dataset()'s DesignerState fixture uses it,
    # matching a real Report Builder-authored .rdl's own root attributes.
    return (
        f'<Report xmlns="{namespace}" '
        'xmlns:rd="http://schemas.microsoft.com/SQLServer/reporting/reportdesigner">'
        f"{body}</Report>"
    )


def data_source(name: str, provider: str, *, connect_string: str = "", reference: str = "") -> str:
    if reference:
        return f'<DataSource Name="{name}"><DataSourceReference>{reference}</DataSourceReference></DataSource>'
    return (
        f'<DataSource Name="{name}"><ConnectionProperties>'
        f"<DataProvider>{provider}</DataProvider><ConnectString>{connect_string}</ConnectString>"
        f"</ConnectionProperties></DataSource>"
    )


def dataset(name: str, data_source_name: str, command_text: str, *, command_type: str = "") -> str:
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


def report_parameter(
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


def report_section(
    width: str,
    *,
    page_width: str | None = None,
    left_margin: str = "1in",
    right_margin: str = "1in",
    body: str = "<Body />",
) -> str:
    page_width_xml = f"<PageWidth>{page_width}</PageWidth>" if page_width else ""
    return (
        f"<ReportSection>{body}<Width>{width}</Width>"
        f"<Page>{page_width_xml}<LeftMargin>{left_margin}</LeftMargin>"
        f"<RightMargin>{right_margin}</RightMargin></Page></ReportSection>"
    )
