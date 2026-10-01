"""RDL checks for schema, data sources, datasets and query pushdown (STR, DS, QRY).

One function per rule ID, registered in ``_rdl_lint.CHECKS``. See
plan/rdl-rule-set.md for what each rule ID checks.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from ._rdl_common import (
    CURRENT_RDL_NAMESPACE,
    Finding,
    _RELATIONAL_PROVIDERS,
    _dataset_provider,
    _location,
    _parents,
    _snippet,
)


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
                if re.search(rf'"{re.escape(name)}"|DataSets!{re.escape(name)}\b', text):
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


_SQL_SELECT_STAR = re.compile(r"(?i)\bselect\s+(?:(?:distinct|all)\s+)?(?:top\s*\(?\s*\d+\s*\)?\s*(?:percent\s+)?)?\*")


_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


def _strip_sql_comments(sql: str) -> str:
    return _SQL_COMMENT.sub(" ", sql)


# A DAX statement that is nothing but EVALUATE of a bare table reference --
# no SUMMARIZECOLUMNS/column projection/filter -- fetches every column,
# the DAX equivalent of SELECT *.
_DAX_BARE_EVALUATE_TABLE = re.compile(r"(?is)^\s*evaluate\s+(?:'[^']+'|[A-Za-z_]\w*)\s*$")


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
        elif provider.upper() in _RELATIONAL_PROVIDERS and _SQL_SELECT_STAR.search(_strip_sql_comments(command_text)):
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
        if provider.upper() not in _RELATIONAL_PROVIDERS:
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


_AGGREGATE_CALL = re.compile(
    r"(?i)\b(sum|count|countdistinct|avg|min|max|first|last|stdev|stdevp|var|varp|aggregate|runningvalue)\s*\("
)


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
        if _AGGREGATE_CALL.search(expressions):
            continue  # ranking groups by a total is a report-side calculation, not a plain ORDER BY
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
        if provider.upper() not in _RELATIONAL_PROVIDERS:
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
