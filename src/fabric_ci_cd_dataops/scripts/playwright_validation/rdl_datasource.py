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
    """One report parameter declared in an ``.rdl`` file's ``ReportParameters``."""

    name: str
    multi_value: bool


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


def parse_rdl_report_parameters(rdl_path: Path) -> list[RdlReportParameter]:
    """Return the report parameters declared in an ``.rdl`` file's own
    ``<ReportParameters>`` block.

    A paginated report's dropdown-driven filter errors (Paginated Report
    Parameter Testing epic) only surface once a real value is selected --
    something ``fab-test`` cannot do without first knowing which parameters
    the report declares and whether each accepts one value or several.
    Returns an empty list for a file with no parameters, or one that cannot
    be read or parsed.
    """
    try:
        # A repo-local .rdl file the caller already has checked out, not
        # attacker-controlled input fetched from the network.
        root = ET.parse(rdl_path).getroot()  # noqa: S314
    except (OSError, ET.ParseError):
        return []

    parameters: list[RdlReportParameter] = []
    for report_parameters in root.iter():
        if _local_name(report_parameters.tag) != "ReportParameters":
            continue
        for parameter in report_parameters:
            if _local_name(parameter.tag) != "ReportParameter":
                continue
            name = parameter.get("Name", "")
            if not name:
                continue
            multi_value = any(
                _local_name(child.tag) == "MultiValue"
                and (child.text or "").strip().lower() == "true"
                for child in parameter
            )
            parameters.append(RdlReportParameter(name=name, multi_value=multi_value))
    return parameters
