"""Parse a paginated (RDL) report's own Power BI dataset reference.

A paginated report's ``GenerateToken`` request needs a dataset ID whenever it
queries a Power BI semantic model, but the Fabric REST API's report-metadata
lookup does not reliably surface it (Paginated Report Testing epic). The
report's own local ``.rdl`` file already carries this in its
``<DataSources>`` block -- a ``PBIDATASET`` data source's ``ConnectString``
embeds the dataset's own ID (``Initial Catalog=sobe_wowvirtualserver-<GUID>``)
and ``rd:PowerBIWorkspaceName`` names the workspace it lives in, which may
differ from the report's own workspace. Parsing this is what lets
``fab-test playwright`` resolve a dataset without the caller supplying a GUID
by hand.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_DATASET_ID_PATTERN = re.compile(
    r"Initial Catalog=sobe_wowvirtualserver-"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


@dataclass(frozen=True)
class RdlPowerBiDataSource:
    """A paginated report's own reference to the Power BI dataset it queries."""

    workspace_name: str
    dataset_id: str


@dataclass(frozen=True)
class RdlReportParameter:
    """One report parameter declared in an ``.rdl`` file's ``ReportParameters``.

    Where its valid values come from, when it declares any: a dataset
    (``values_query`` is that dataset's DAX, ``value_column`` the result
    column its value field reads -- the key ``executeQueries`` returns each
    row under) or a static list (``static_values``). A free-text parameter
    has neither, so there is no value a test could pick for it.
    """

    name: str
    multi_value: bool
    values_query: str = ""
    value_column: str = ""
    static_values: tuple[str, ...] = ()


def _local_name(tag: str) -> str:
    """Strip an XML namespace from a tag: ``{ns}DataSource`` -> ``DataSource``."""
    return tag.rsplit("}", 1)[-1]


def parse_rdl_power_bi_datasource(rdl_path: Path) -> RdlPowerBiDataSource | None:
    """Return the first ``PBIDATASET`` data source's workspace/dataset reference.

    Returns ``None`` when the file cannot be read or parsed, or when no data
    source in it queries a Power BI dataset -- a paginated report can just as
    easily use Power Query or another provider that needs nothing resolved
    here.
    """
    try:
        # A repo-local .rdl file the caller already has checked out, not
        # attacker-controlled input fetched from the network.
        root = ET.parse(rdl_path).getroot()  # noqa: S314
    except (OSError, ET.ParseError):
        return None

    for data_source in root.iter():
        if _local_name(data_source.tag) != "DataSource":
            continue
        fields = {
            _local_name(child.tag): (child.text or "").strip()
            for child in data_source.iter()
        }
        if fields.get("DataProvider") != "PBIDATASET":
            continue
        workspace_name = fields.get("PowerBIWorkspaceName", "")
        match = _DATASET_ID_PATTERN.search(fields.get("ConnectString", ""))
        if not workspace_name or not match:
            continue
        return RdlPowerBiDataSource(
            workspace_name=workspace_name, dataset_id=match.group(1)
        )
    return None


def _child(element: ET.Element, name: str) -> ET.Element | None:
    """Return ``element``'s first direct child with local name ``name``."""
    return next((c for c in element if _local_name(c.tag) == name), None)


def _text(element: ET.Element | None, *path: str) -> str:
    """Follow ``path`` of local child names from ``element``; return its text."""
    for name in path:
        if element is None:
            return ""
        element = _child(element, name)
    return (element.text or "").strip() if element is not None else ""


def _dataset_queries(root: ET.Element) -> dict[str, tuple[str, dict[str, str]]]:
    """Map each dataset name to ``(its CommandText, {field name: data field})``."""
    datasets: dict[str, tuple[str, dict[str, str]]] = {}
    for dataset in root.iter():
        if _local_name(dataset.tag) != "DataSet" or not dataset.get("Name"):
            continue
        fields_element = _child(dataset, "Fields")
        fields = {
            field.get("Name", ""): _text(field, "DataField")
            for field in (fields_element if fields_element is not None else [])
            if _local_name(field.tag) == "Field"
        }
        datasets[dataset.get("Name", "")] = (_text(dataset, "Query", "CommandText"), fields)
    return datasets


def _parse_parameter(
    parameter: ET.Element, datasets: dict[str, tuple[str, dict[str, str]]]
) -> RdlReportParameter:
    """Build one ``RdlReportParameter``, resolving where its values come from."""
    multi_value = _text(parameter, "MultiValue").lower() == "true"
    valid_values = _child(parameter, "ValidValues")
    reference = _child(valid_values, "DataSetReference") if valid_values is not None else None
    if reference is not None:
        query, fields = datasets.get(_text(reference, "DataSetName"), ("", {}))
        value_field = _text(reference, "ValueField")
        return RdlReportParameter(
            name=parameter.get("Name", ""),
            multi_value=multi_value,
            values_query=query,
            value_column=fields.get(value_field, value_field),
        )
    static = _child(valid_values, "ParameterValues") if valid_values is not None else None
    if static is not None:
        return RdlReportParameter(
            name=parameter.get("Name", ""),
            multi_value=multi_value,
            static_values=tuple(
                _text(value, "Value")
                for value in static
                if _local_name(value.tag) == "ParameterValue"
            ),
        )
    return RdlReportParameter(name=parameter.get("Name", ""), multi_value=multi_value)


def parse_rdl_report_parameters_text(rdl_text: str) -> list[RdlReportParameter]:
    """Return the report parameters declared in RDL ``rdl_text``.

    The one parser behind both a local ``.rdl`` file and a paginated
    report's definition downloaded from the workspace -- the latter being
    the only source for a report that exists nowhere locally. Returns an
    empty list for a definition with no parameters, or one that cannot be
    parsed.
    """
    try:
        # A report definition from this repository or from the caller's own
        # workspace, never arbitrary third-party input.
        root = ET.fromstring(rdl_text)  # noqa: S314
    except ET.ParseError:
        return []

    datasets = _dataset_queries(root)
    return [
        _parse_parameter(parameter, datasets)
        for report_parameters in root.iter()
        if _local_name(report_parameters.tag) == "ReportParameters"
        for parameter in report_parameters
        if _local_name(parameter.tag) == "ReportParameter" and parameter.get("Name")
    ]


def parse_rdl_report_parameters(rdl_path: Path) -> list[RdlReportParameter]:
    """Return the report parameters declared in a local ``.rdl`` file.

    A paginated report's dropdown-driven filter errors (Paginated Report
    Parameter Testing epic) only surface once a real value is selected --
    something ``fab-test`` cannot do without first knowing which parameters
    the report declares, whether each accepts one value or several, and
    where its valid values come from. Returns an empty list for a file with
    no parameters, or one that cannot be read or parsed.
    """
    try:
        rdl_text = rdl_path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    return parse_rdl_report_parameters_text(rdl_text)
