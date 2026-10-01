"""RDL static-analysis rule engine (RDL Static Analysis epic).

Pure functions only: XML parsing/namespace handling, the rule catalog
loader, and the check dispatch table. ``invoke_rdl_lint.py`` is the thin
CLI wrapper around this module -- the same split ``_rule_overlay.py``
already applies to BPA/PBIR's rule files.

See plan/rdl-rule-set.md for what each rule ID checks, and
metadata/rules/rdl-rules.json for the catalog itself.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

Finding = dict[str, Any]
# Every check gets the same three arguments -- the parsed (namespace-
# stripped) report root, the report's own original schema namespace URI,
# and its own catalog entry (so a rule with a configurable threshold, e.g.
# QRY-07's line count or SUB-02's subreport count, reads it from the
# catalog rather than a hardcoded constant) -- even though most checks
# ignore the second and third. One uniform shape is simpler than a
# dataclass wrapper for the few rules that need the extra context.
RdlCheck = Callable[[ET.Element, str, dict[str, Any]], list[Finding]]

CURRENT_RDL_NAMESPACE = "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition"

# DAX/Power Query providers a PBIDATASET-bound paginated report uses --
# never a value DS-01/05/07 treat as "relational", since there is no SQL
# text or shared-data-source alternative for either shape.
_NON_RELATIONAL_PROVIDERS = frozenset({"PBIDATASET", "PQO", ""})


class RdlParseError(Exception):
    """Raised when a .rdl file can't be read or parsed as XML."""


def parse_rdl(path: Path) -> tuple[ET.Element, str]:
    """Parse an ``.rdl`` file and return ``(root, namespace)``: the root
    element with tag names stripped of their namespace prefix, and the
    schema's original default-namespace URI (STR-01's own concern; every
    other check ignores it).

    RDL's default ``xmlns`` differs by schema version (2008/2010/2016), and
    report-designer tooling can emit any of them. Stripping ``{uri}`` from
    every element's tag once, here, means every check function can match
    elements (``Tablix``, ``Subreport``, ``ToolTip``, ...) by local name
    and never hard-code one xmlns.

    Namespace stripping also collapses ``rd:DesignerState``'s own nested
    design-time snapshot -- serialized under a *different* namespace
    (``.../AnalysisServices/QueryDefinition``) with its own ``Query`` and
    ``Statement`` elements, not a second ``CommandText`` -- so it is not
    mistaken for the dataset's real, executable query. Confirmed against a
    real Report Builder-authored .rdl: `Query.find("CommandText")` (a
    direct child) returns only the real one either way, so every DS/QRY
    check below matches direct children, never a recursive ``.//`` search,
    when it means "this dataset's own query" specifically.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise RdlParseError(f"{path.name} is not well-formed XML: {exc}") from exc
    except OSError as exc:
        raise RdlParseError(f"could not read {path.name}: {exc}") from exc

    root = tree.getroot()
    namespace = ""
    if isinstance(root.tag, str) and root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    return root, namespace


def load_rule_catalog(path: Path) -> list[dict[str, Any]]:
    """Load the RDL rule catalog's ``"rules"`` list from ``path``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("rules", [])


def _is_active(rule: dict[str, Any]) -> bool:
    """A rule runs and shows in results only once verified against a real fixture.

    "planned" rules stay in the catalog as the roadmap but are invisible to
    a run; a catalog entry with no status (a custom catalog) is active.
    """
    return rule.get("status", "active") == "active"


# Maps a rule ID to the function that checks it, given a parsed (namespace-
# stripped) report root. Empty until later RDL Static Analysis epic tasks
# register the STR/DS/QRY/PRM/LAY/SUB/ACC checks -- a catalog entry with no
# function here yet is reported as "skip", not "pass" (build_test_results).
CHECKS: dict[str, RdlCheck] = {}


def run_checks(root: ET.Element, namespace: str, catalog: list[dict[str, Any]]) -> list[Finding]:
    """Run every enabled catalog rule that has a registered check.

    A catalog entry that is disabled, or has no function in CHECKS yet, is
    silently skipped here -- build_test_results is what records *why* a
    rule produced nothing, for the report and for telemetry.

    A finding's own "rule" wins over the catalog entry being iterated, if
    it set one -- LAY-03/SUB-01's shared check is the one case that does:
    a Subreport nested in a Tablix is one finding, not two, so it's
    dispatched only from LAY-03's catalog entry but tags itself with both
    IDs rather than letting this loop stamp "LAY-03" over that.
    """
    findings: list[Finding] = []
    for rule in catalog:
        if rule.get("disabled") or not _is_active(rule):
            continue
        check = CHECKS.get(rule["id"])
        if check is None:
            continue
        findings.extend(
            {
                **finding,
                "rule": finding.get("rule", rule["id"]),
                "severity": finding.get("severity", rule.get("severity", "warning")),
                **({"source_urls": rule["source_urls"]} if "source_urls" in rule else {}),
            }
            for finding in check(root, namespace, rule)
        )
    return findings


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


# --------------------------------------------------------------------------- #
# Structure and data source rules (STR-01, DS-01, DS-02, DS-05, DS-07)
# --------------------------------------------------------------------------- #


def _check_str01_current_schema(_root: ET.Element, namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    if namespace and namespace != CURRENT_RDL_NAMESPACE:
        return [{
            "object": "Report",
            "message": (
                f"report uses schema '{namespace}', older than the current "
                f"{CURRENT_RDL_NAMESPACE} -- open and save in Report Builder to upgrade"
            ),
        }]
    return []


_CREDENTIAL_PATTERN = re.compile(r"(?i)\b(password|pwd)\s*=")


def _check_ds01_no_embedded_credentials(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    # Deliberately does NOT ask for a shared data source (DataSourceReference):
    # Power BI paginated reports don't support SSRS-style shared data sources
    # (.rds), so an embedded connection is the normal shape there, not a smell.
    findings: list[Finding] = []
    for source in root.findall(".//DataSources/DataSource"):
        name = source.get("Name") or "?"
        conn_props = source.find("ConnectionProperties")
        if conn_props is None:
            continue
        connect_string = conn_props.findtext("ConnectString") or ""
        if _CREDENTIAL_PATTERN.search(connect_string):
            # Never echo the matched text itself -- only that something
            # password-shaped is there, so the finding can't leak it.
            findings.append({
                "object": name,
                "message": (
                    "connect string appears to embed a password; use a Power BI "
                    "cloud connection or the service's credential store instead"
                ),
            })
    return findings


def _check_ds02_unused_datasets(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    dataset_names = {ds.get("Name") for ds in root.findall(".//DataSets/DataSet") if ds.get("Name")}
    if not dataset_names:
        return []
    used = {el.text.strip() for el in root.iter("DataSetName") if el.text and el.text.strip()}
    unresolved = dataset_names - used
    if unresolved:
        for element in root.iter():
            text = (element.text or "").strip()
            if not text.startswith("="):
                continue
            for name in list(unresolved):
                if re.search(rf"\b{re.escape(name)}\b", text):
                    used.add(name)
                    unresolved.discard(name)
            if not unresolved:
                break
    return [
        {
            "object": name,
            "message": (
                f"dataset '{name}' is never referenced by a data region, parameter, "
                "or expression -- it still runs on every render"
            ),
        }
        for name in sorted(dataset_names - used)
    ]


_SQL_SELECT_STAR = re.compile(r"(?i)select\s+\*")
# A DAX statement that is nothing but EVALUATE of a bare table reference --
# no SUMMARIZECOLUMNS/column projection/filter -- fetches every column,
# the DAX equivalent of SELECT *.
_DAX_BARE_EVALUATE_TABLE = re.compile(r"(?is)^\s*evaluate\s+'[^']+'\s*$")


def _check_ds05_no_select_star(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for dataset in root.findall(".//DataSets/DataSet"):
        name = dataset.get("Name") or "?"
        query = dataset.find("Query")
        if query is None:
            continue
        command_text = query.findtext("CommandText") or ""
        provider = _dataset_provider(root, query)
        if provider == "PBIDATASET":
            if _DAX_BARE_EVALUATE_TABLE.search(command_text):
                findings.append({
                    "object": name,
                    "message": (
                        f"{_snippet(command_text)}: EVALUATE of a whole table with no column "
                        "projection is the DAX equivalent of SELECT * -- project only the "
                        "columns the report uses"
                    ),
                })
        elif provider not in _NON_RELATIONAL_PROVIDERS and _SQL_SELECT_STAR.search(command_text):
            findings.append({
                "object": name,
                "message": (
                    f"{_snippet(command_text)}: SELECT * fetches every column -- "
                    "list only the columns the report uses"
                ),
            })
    return findings


def _check_ds07_prefer_stored_procedures(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for dataset in root.findall(".//DataSets/DataSet"):
        name = dataset.get("Name") or "?"
        query = dataset.find("Query")
        if query is None:
            continue
        provider = _dataset_provider(root, query)
        if provider in _NON_RELATIONAL_PROVIDERS:
            continue
        command_text = (query.findtext("CommandText") or "").strip()
        command_type = (query.findtext("CommandType") or "").strip()
        if command_text and command_type.lower() != "storedprocedure":
            findings.append({
                "object": name,
                "message": (
                    f"{_snippet(command_text)}: inline SQL text; a stored procedure gets a "
                    "cached plan, reuse, and fixes without republishing"
                ),
            })
    return findings


# --------------------------------------------------------------------------- #
# Query pushdown rules (QRY-01 .. QRY-07)
# --------------------------------------------------------------------------- #


def _filter_text(filters: ET.Element) -> str:
    """The filter expressions, quoted, so the message names what is filtered."""
    return _snippet(", ".join(e.text or "" for e in filters.iter("FilterExpression")))


def _check_qry01_filter_in_query(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for dataset in root.findall(".//DataSets/DataSet"):
        filters = dataset.find("Filters")
        if filters is not None and filters.findall("Filter"):
            findings.append({
                "object": dataset.get("Name") or "?",
                "message": (
                    f"DataSet/Filters present ({_filter_text(filters)}) -- prefer a WHERE "
                    "clause or query parameter; a report filter fetches everything first"
                ),
            })
    for tablix in root.iter("Tablix"):
        filters = tablix.find("Filters")
        if filters is not None and filters.findall("Filter"):
            findings.append({
                "object": tablix.get("Name") or "?",
                "message": (
                    f"Tablix/Filters present ({_filter_text(filters)}) -- prefer a WHERE "
                    "clause or query parameter; a report filter fetches everything first"
                ),
            })
    return findings


def _check_qry02_no_calculated_fields(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for dataset in root.findall(".//DataSets/DataSet"):
        fields = dataset.find("Fields")
        if fields is None:
            continue
        findings.extend(
            {
                "object": f"{dataset.get('Name') or '?'} › {field.get('Name') or '?'}",
                "message": (
                    f"calculated field {_snippet(field.findtext('Value') or '')} -- "
                    "move the expression into the query"
                ),
            }
            for field in fields.findall("Field")
            if field.find("Value") is not None
        )
    return findings


# QRY-03 is deliberately scoped to an aggregate called with an explicit
# dataset-scope argument (e.g. =Sum(Fields!X.Value, "Sales")) -- the shape
# that aggregates an entire named dataset from inside a report expression,
# not a plain =Sum(Fields!X.Value) in a tablix group/total footer,  which
# is the normal, correct way RDL shows a total and would otherwise flood
# every ordinary report with false positives.
_AGGREGATE_WITH_DATASET_SCOPE = re.compile(r'(?i)\b(sum|count|countdistinct|avg|max|min)\s*\([^()]*,\s*"([^"]+)"\s*\)')


def _check_qry03_aggregate_in_query(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for element in root.iter():
        text = (element.text or "").strip()
        if not text.startswith("="):
            continue
        for match in _AGGREGATE_WITH_DATASET_SCOPE.finditer(text):
            func, dataset_name = match.group(1), match.group(2)
            key = (func.lower(), dataset_name)
            if key in seen:
                continue
            seen.add(key)
            findings.append({
                "object": dataset_name,
                "message": (
                    f"{func}(...) aggregates dataset '{dataset_name}' entirely in a "
                    "report expression -- use GROUP BY in the query for a large detail dataset"
                ),
            })
    return findings


def _check_qry04_sort_in_query(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    # Report Builder writes SortExpressions as a sibling of Group inside
    # TablixMember, and at the Tablix level -- never inside Group.
    parents = _parents(root)
    findings: list[Finding] = []
    for owner in [*root.iter("TablixMember"), *root.iter("Tablix")]:
        sort_expressions = owner.find("SortExpressions")
        if sort_expressions is None or not sort_expressions.findall("SortExpression"):
            continue
        group = owner.find("Group") if owner.tag == "TablixMember" else None
        where = _location(parents, group if group is not None else owner)
        expressions = ", ".join(e.findtext("Value") or "" for e in sort_expressions.iter("SortExpression"))
        findings.append({
            "object": where,
            "message": (
                f"sorts by {_snippet(expressions)} in the report -- an order the query "
                "could already provide via ORDER BY"
            ),
        })
    return findings


_TYPE_CONVERSION = re.compile(r"(?i)\b(CDate|CInt|CDec|CStr)\s*\(\s*([^()]+?)\s*\)")


def _check_qry05_convert_types_in_query(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    # Given a type-conversion function applied to the same field in more
    # than one expression, reports once per (function, field) pair, not
    # once per occurrence -- counted first, findings built after.
    counts: dict[tuple[str, str], int] = {}
    for element in root.iter():
        text = (element.text or "").strip()
        if not text.startswith("="):
            continue
        for match in _TYPE_CONVERSION.finditer(text):
            key = (match.group(1), match.group(2).strip())
            counts[key] = counts.get(key, 0) + 1
    return [
        {
            "object": field,
            "message": f"{func}({field}) is repeated {count} times across expressions -- cast once in the query",
        }
        for (func, field), count in sorted(counts.items())
        if count >= 2
    ]


_LOOKUP_CALL = re.compile(r"(?i)\b(Lookup|LookupSet|MultiLookup)\s*\(")


def _check_qry06_join_in_query(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for element in root.iter():
        text = (element.text or "").strip()
        if not text.startswith("="):
            continue
        match = _LOOKUP_CALL.search(text)
        if match is None:
            continue
        findings.append({
            "object": _location(parents, element),
            "message": (
                f"{_snippet(text)}: {match.group(1)}(...) in an expression -- replace with a "
                "SQL join, or a Power BI semantic model when sources differ"
            ),
        })
    return findings


_DEFAULT_QRY07_MAX_LINES = 50


def _check_qry07_move_complex_sql(root: ET.Element, _namespace: str, rule: dict[str, Any]) -> list[Finding]:
    max_lines = rule.get("max_lines", _DEFAULT_QRY07_MAX_LINES)
    findings: list[Finding] = []
    for dataset in root.findall(".//DataSets/DataSet"):
        query = dataset.find("Query")
        if query is None:
            continue
        provider = _dataset_provider(root, query)
        if provider in _NON_RELATIONAL_PROVIDERS:
            continue
        command_text = query.findtext("CommandText") or ""
        line_count = len(command_text.splitlines())
        if line_count > max_lines:
            findings.append({
                "object": dataset.get("Name") or "?",
                "message": (
                    f"CommandText is {line_count} line(s), over the {max_lines}-line "
                    "threshold -- move complex SQL into a view or stored procedure"
                ),
            })
    return findings


# --------------------------------------------------------------------------- #
# Parameter rules (PRM-01, PRM-03, PRM-04, PRM-05)
# --------------------------------------------------------------------------- #


def _check_prm01_default_value(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    return [
        {
            "object": parameter.get("Name") or "?",
            "message": "no DefaultValue -- the report won't run on open without a manual selection",
        }
        for parameter in root.findall(".//ReportParameters/ReportParameter")
        if parameter.find("DefaultValue") is None
    ]


_DEFAULT_PRM03_MAX_PARAMETERS = 5
# Matches a parameter named after a single date part -- "Year"/"Month"/"Day"
# as a whole word, so "Yearly" or "PayDay" don't count.
_DATE_PART_NAME = re.compile(r"(?i)\b(year|month|day)\b")


def _check_prm03_parameter_count(root: ET.Element, _namespace: str, rule: dict[str, Any]) -> list[Finding]:
    max_parameters = rule.get("max_parameters", _DEFAULT_PRM03_MAX_PARAMETERS)
    parameters = root.findall(".//ReportParameters/ReportParameter")
    names = [parameter.get("Name") or "" for parameter in parameters]
    findings: list[Finding] = []

    # Fires regardless of the total count -- three narrow date-part
    # parameters are the anti-pattern this rule names explicitly, not a
    # symptom of the report simply having "too many" parameters.
    date_part_names = [name for name in names if _DATE_PART_NAME.search(name)]
    date_parts_seen = {match.lower() for name in date_part_names for match in _DATE_PART_NAME.findall(name)}
    if len(date_parts_seen) >= 2:
        findings.append({
            "object": ", ".join(date_part_names),
            "message": "separate Year/Month/Day parameters should usually be one DateTime picker",
        })

    if len(parameters) > max_parameters:
        findings.append({
            "object": f"{len(parameters)} parameters",
            "message": (
                f"{len(parameters)} parameters is over the {max_parameters}-parameter "
                "threshold -- keep the parameter count low"
            ),
        })
    return findings


def _check_prm04_multivalue_nullable(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for parameter in root.findall(".//ReportParameters/ReportParameter"):
        multi_value = (parameter.findtext("MultiValue") or "").strip().lower() == "true"
        nullable = (parameter.findtext("Nullable") or "").strip().lower() == "true"
        if multi_value and nullable:
            findings.append({
                "object": parameter.get("Name") or "?",
                "message": "MultiValue=true with Nullable=true isn't supported -- MultiValue + AllowBlank is fine",
            })
    return findings


_PARAMETER_REFERENCE = re.compile(r"Parameters!(\w+)\.(?:Value|Label)")


def _check_prm05_show_parameter_values(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parameters = root.findall(".//ReportParameters/ReportParameter")
    if not parameters:
        return []
    displayed: set[str] = set()
    for element in root.iter():
        text = (element.text or "").strip()
        if not text.startswith("="):
            continue
        displayed.update(_PARAMETER_REFERENCE.findall(text))
    return [
        {
            "object": name,
            "message": (
                f"parameter '{name}' isn't shown anywhere on the report "
                f"(Parameters!{name}.Value or .Label) -- exported copies won't be self-explanatory"
            ),
        }
        for name in (parameter.get("Name") or "" for parameter in parameters)
        if name and name not in displayed
    ]


# --------------------------------------------------------------------------- #
# Layout and subreport rules (LAY-01 .. LAY-06, SUB-01, SUB-02)
# --------------------------------------------------------------------------- #

# RDL's own schema default when Page/PageWidth is omitted (Letter width).
_DEFAULT_PAGE_WIDTH_INCHES = 8.5


def _check_lay01_body_fits_page(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    report_section = root.find(".//ReportSection")
    if report_section is None:
        return []
    body_width = _size_in_inches(report_section.findtext("Width"))
    if body_width is None:
        return []
    page = report_section.find("Page")
    left_margin = _size_in_inches(page.findtext("LeftMargin")) if page is not None else None
    right_margin = _size_in_inches(page.findtext("RightMargin")) if page is not None else None
    page_width = _size_in_inches(page.findtext("PageWidth")) if page is not None else None
    total = body_width + (left_margin or 0.0) + (right_margin or 0.0)
    effective_page_width = page_width if page_width is not None else _DEFAULT_PAGE_WIDTH_INCHES
    if total > effective_page_width:
        return [{
            "object": "ReportSection",
            "message": (
                f"body width + margins ({total:.2f}in) exceeds the page width "
                f"({effective_page_width:.2f}in) -- PDF/print will add blank overflow pages"
            ),
        }]
    return []


def _check_lay02_avoid_total_pages(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for element in root.iter():
        text = (element.text or "").strip()
        if text.startswith("=") and "Globals!TotalPages" in text:
            findings.append({
                "object": _location(parents, element),
                "message": f"{_snippet(text)}: Globals!TotalPages slows PDF and image rendering",
            })
    return findings


def _check_lay03_sub01_subreport_in_tablix(
    root: ET.Element, _namespace: str, _rule: dict[str, Any]
) -> list[Finding]:
    """Registered only under LAY-03's catalog entry -- SUB-01 detects the
    exact same thing, so this produces one finding per offending
    Subreport, tagged with both IDs, rather than being dispatched twice.
    """
    parents = _parents(root)
    return [
        {
            "rule": "LAY-03/SUB-01",
            "object": _location(parents, subreport),
            "message": (
                "Subreport nested inside a Tablix runs once per row -- use a "
                "nested data region, or a drillthrough link when rows are many"
            ),
        }
        for tablix in root.iter("Tablix")
        for subreport in tablix.iter("Subreport")
    ]


def _check_lay04_interactive_sort(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    return [
        {
            "object": _location(parents, textbox),
            "message": "UserSort on a textbox enables interactive sort -- use only when actually wanted",
        }
        for textbox in root.iter("Textbox")
        if textbox.find("UserSort") is not None
    ]


def _check_lay05_large_reports_page_breaks(
    root: ET.Element, _namespace: str, _rule: dict[str, Any]
) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for tablix in root.iter("Tablix"):
        groups = list(tablix.iter("Group"))
        if not groups:
            continue
        has_page_break = any(group.find("PageBreak/BreakLocation") is not None for group in groups)
        if not has_page_break:
            findings.append({
                "object": _location(parents, tablix),
                "message": (
                    "no Group/PageBreak/BreakLocation configured -- nothing shows "
                    "until the whole report renders on a large dataset"
                ),
            })
    return findings


def _check_lay06_avoid_embedded_images(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    embedded_message = (
        "EmbeddedImages/EmbeddedImage bloats the file and is hard to update -- prefer External or Database"
    )
    inline_message = "Image/Source=Embedded bloats the file and is hard to update -- prefer External or Database"
    findings: list[Finding] = [
        {"object": embedded.get("Name") or "?", "message": embedded_message}
        for embedded in root.findall(".//EmbeddedImages/EmbeddedImage")
    ]
    parents = _parents(root)
    findings.extend(
        {"object": _location(parents, image), "message": inline_message}
        for image in root.iter("Image")
        if (image.findtext("Source") or "").strip().lower() == "embedded"
    )
    return findings


_DEFAULT_SUB02_MAX_SUBREPORTS = 49  # "50 or more" fails; 49 is the highest passing count


def _check_sub02_subreport_count(root: ET.Element, _namespace: str, rule: dict[str, Any]) -> list[Finding]:
    max_subreports = rule.get("max_subreports", _DEFAULT_SUB02_MAX_SUBREPORTS)
    count = len(root.findall(".//Subreport"))
    if count > max_subreports:
        return [{
            "object": f"{count} subreports",
            "message": f"{count} Subreport elements -- 50 or more fail to render in the service",
        }]
    return []


# --------------------------------------------------------------------------- #
# Accessibility rules (ACC-01, ACC-02, ACC-03, ACC-08)
# --------------------------------------------------------------------------- #

# Tablix is excluded here even though it's a report item like the rest --
# ACC-03 already covers a missing Tablix/ToolTip specifically, and a
# Tablix with none should be one finding (ACC-03), not two.
_ALT_TEXT_ELEMENTS = ("Image", "Chart", "GaugePanel", "Map")


def _check_acc01_alt_text(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    return [
        {
            "object": _location(parents, element),
            "message": f"{tag} has no ToolTip -- screen readers get nothing in the service or Accessible PDF",
        }
        for tag in _ALT_TEXT_ELEMENTS
        for element in root.iter(tag)
        if not (element.findtext("ToolTip") or "").strip()
    ]


_PLACEHOLDER_CHART_NAME = re.compile(r"(?i)^chart\d*$")


def _check_acc02_chart_alt_text_quality(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for chart in root.iter("Chart"):
        tooltip = (chart.findtext("ToolTip") or "").strip()
        if not tooltip:
            continue  # missing entirely is ACC-01's concern, not ACC-02's
        if tooltip.startswith("="):
            continue  # an expression's wording can't be judged statically
        name = chart.get("Name") or ""
        if tooltip == name or _PLACEHOLDER_CHART_NAME.match(tooltip):
            findings.append({
                "object": _location(parents, chart),
                "message": f"ToolTip '{tooltip}' looks like a placeholder, not a description of what the chart shows",
            })
    return findings


def _check_acc03_table_caption(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    return [
        {
            "object": _location(parents, tablix),
            "message": "Tablix has no ToolTip -- add a caption summarising what the table conveys",
        }
        for tablix in root.iter("Tablix")
        if not (tablix.findtext("ToolTip") or "").strip()
    ]


def _check_acc08_html_link_alt_text(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for textbox in root.iter("Textbox"):
        has_html_run = any(
            (run.findtext("MarkupType") or "").strip().lower() == "html" for run in textbox.iter("TextRun")
        )
        if not has_html_run:
            continue
        if not (textbox.findtext("ToolTip") or "").strip():
            findings.append({
                "object": _location(parents, textbox),
                "message": "renders an HTML TextRun (a hyperlink) but has no ToolTip",
            })
    return findings


CHECKS.update({
    "STR-01": _check_str01_current_schema,
    "DS-01": _check_ds01_no_embedded_credentials,
    "DS-02": _check_ds02_unused_datasets,
    "DS-05": _check_ds05_no_select_star,
    "DS-07": _check_ds07_prefer_stored_procedures,
    "QRY-01": _check_qry01_filter_in_query,
    "QRY-02": _check_qry02_no_calculated_fields,
    "QRY-03": _check_qry03_aggregate_in_query,
    "QRY-04": _check_qry04_sort_in_query,
    "QRY-05": _check_qry05_convert_types_in_query,
    "QRY-06": _check_qry06_join_in_query,
    "QRY-07": _check_qry07_move_complex_sql,
    "PRM-01": _check_prm01_default_value,
    "PRM-03": _check_prm03_parameter_count,
    "PRM-04": _check_prm04_multivalue_nullable,
    "PRM-05": _check_prm05_show_parameter_values,
    "LAY-01": _check_lay01_body_fits_page,
    "LAY-02": _check_lay02_avoid_total_pages,
    "LAY-03": _check_lay03_sub01_subreport_in_tablix,
    "LAY-04": _check_lay04_interactive_sort,
    "LAY-05": _check_lay05_large_reports_page_breaks,
    "LAY-06": _check_lay06_avoid_embedded_images,
    "SUB-02": _check_sub02_subreport_count,
    "ACC-01": _check_acc01_alt_text,
    "ACC-02": _check_acc02_chart_alt_text_quality,
    "ACC-03": _check_acc03_table_caption,
    "ACC-08": _check_acc08_html_link_alt_text,
})


def build_test_results(
    catalog: list[dict[str, Any]], findings: list[Finding], implemented: set[str]
) -> list[dict[str, Any]]:
    """Return one row per catalog rule for the shared HTML report table.

    ``implemented`` is the set of rule IDs with a registered check --
    normally ``set(CHECKS)``, passed explicitly rather than read from that
    global here so this stays a pure function of its arguments. Every rule
    fab-test knows about gets a row: "pass" when its check ran clean, its
    own severity as status when it fired, "skip" when it is disabled or
    not yet implemented -- so `normalize_test_results` shows the whole
    catalog, not only whatever happened to produce a finding. When a rule
    fires on more than one element, each hit gets its own row. A row's message is
    the finding's own text when it fired, or the catalog's rule
    description otherwise -- readable either way, never a bare status word.

    A finding's own "rule" can name more than one ID, "/"-separated
    (LAY-03/SUB-01's shared check) -- indexed under each of them here, so
    both catalog rows show the one real finding rather than one showing
    it and the other showing an unrelated "skip".
    """
    hits_by_rule: dict[str, list[Finding]] = {}
    for finding in findings:
        for rule_id in finding["rule"].split("/"):
            hits_by_rule.setdefault(rule_id, []).append(finding)

    rows = []
    for rule in filter(_is_active, catalog):
        rule_id = rule["id"]
        hits = [] if rule.get("disabled") else hits_by_rule.get(rule_id, [])
        urls = {"source_urls": rule["source_urls"]} if "source_urls" in rule else {}
        base = {"rule": rule_id, "severity": rule.get("severity", "warning")}
        if hits:
            rows.extend({**base, "object": h.get("object", ""), "message": h["message"], "status": h["severity"], **urls} for h in hits)
            continue
        status = "pass" if rule_id in implemented and not rule.get("disabled") else "skip"
        rows.append({**base, "object": "", "message": rule.get("description", ""), "status": status, **urls})
    return rows
