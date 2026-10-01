"""Shared types and helpers for the RDL rule checks.

Split out of ``_rdl_lint.py`` (aidd-module-budgets: one module per rule family
once the engine crossed the hard budget) so the check modules and the engine
can both import them without importing each other.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

CURRENT_RDL_NAMESPACE = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"

Finding = dict[str, Any]


# Every check gets the same three arguments -- the parsed (namespace-
# stripped) report root, the report's own original schema namespace URI,
# and its own catalog entry (so a rule with a configurable threshold, e.g.
# QRY-07's line count or SUB-02's subreport count, reads it from the
# catalog rather than a hardcoded constant) -- even though most checks
# ignore the second and third. One uniform shape is simpler than a
# dataclass wrapper for the few rules that need the extra context.
RdlCheck = Callable[[ET.Element, str, dict[str, Any]], list[Finding]]


# Providers whose CommandText is SQL. DS-05, DS-07 and QRY-07 ask only these
# to avoid SELECT * / inline text / long queries; MDX (OLEDB-MD, ESSBASE,
# SAPBW), XML, SharePoint, DAX (PBIDATASET) and Power Query (PQO) are not SQL.
_RELATIONAL_PROVIDERS = frozenset({"SQL", "SQLAZURE", "SQLDW", "OLEDB", "ODBC", "ORACLE", "TERADATA"})


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _dataset_provider(root: ET.Element, query: ET.Element) -> str:
    """Return the DataProvider (e.g. "PBIDATASET", "SQL") for a dataset's
    Query, resolved by following its DataSourceName to the matching
    DataSource. Empty when either end can't be resolved.
    """
    ds_name = query.findtext("DataSourceName")
    if not ds_name:
        return ""
    for source in root.findall(".//DataSources/DataSource"):
        if source.get("Name") == ds_name:
            return (source.findtext("ConnectionProperties/DataProvider") or "").strip()
    return ""


_SIZE_PATTERN = re.compile(r"(?i)^\s*([\d.]+)\s*(in|cm|mm|pt)\s*$")


_UNIT_TO_INCHES = {"in": 1.0, "cm": 1 / 2.54, "mm": 1 / 25.4, "pt": 1 / 72.0}


def _snippet(text: str, width: int = 60) -> str:
    """Collapse whitespace and cut ``text`` so a message can quote the offender."""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 3] + "..."


_NAMED_ITEMS = frozenset({
    "Tablix", "Textbox", "Chart", "Image", "Subreport", "Rectangle", "GaugePanel", "Map", "Group",
})


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _location(parents: dict[ET.Element, ET.Element], element: ET.Element) -> str:
    """Outer > Inner path of the named report items the element sits in or is.

    A top-level item is just its name; one inside a Tablix is "T1 > Tb1".
    An item with no name anywhere on its path falls back to its element
    name rather than a bare "?".
    """
    names = []
    node: ET.Element | None = element
    while node is not None:
        if node.tag in _NAMED_ITEMS and node.get("Name"):
            names.append(node.get("Name"))
        node = parents.get(node)
    return " › ".join(reversed(names)) or element.tag


def _size_in_inches(value: str | None) -> float | None:
    """Parse an RDL size string ("6in", "21cm", "210mm", "72pt") into
    inches, or None if it's absent or not one of those four units.
    """
    if not value:
        return None
    match = _SIZE_PATTERN.match(value)
    if match is None:
        return None
    number, unit = match.groups()
    return float(number) * _UNIT_TO_INCHES[unit.lower()]
