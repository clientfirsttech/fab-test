"""Tier B RDL checks on datasets and fields (DS-03, DS-04, DS-06, STR-03, PRM-02).

One function per rule ID, registered in ``_rdl_lint.CHECKS``. See
plan/rdl-rule-set.md for what each rule ID checks.
"""

from __future__ import annotations

import difflib
import re
import xml.etree.ElementTree as ET
from typing import Any

from ._rdl_checks_query import _strip_sql_comments
from ._rdl_common import _RELATIONAL_PROVIDERS, Finding, _dataset_provider

_SQL_STRING = re.compile(r"'(?:[^']|'')*'")
_SQL_FROM = re.compile(r"(?i)\bfrom\b")
_DAX_LITERAL_TABLE = re.compile(r"(?is)^\s*evaluate\s+(?:datatable\s*\(|\{)")
_PQ_ENTERED_DATA = ("Table.FromRows(Json.Document(Binary.Decompress(", "#table(")


def _is_literal_query(provider: str, command_text: str) -> bool:
    """True when the query returns values typed into it rather than read from a source."""
    if provider.upper() in _RELATIONAL_PROVIDERS:
        return not _SQL_FROM.search(_strip_sql_comments(_SQL_STRING.sub("''", command_text)))
    if provider == "PBIDATASET":
        return bool(_DAX_LITERAL_TABLE.search(command_text))
    if provider == "PQO":
        return any(marker in command_text for marker in _PQ_ENTERED_DATA)
    return False


def _check_ds03_static_parameter_lists(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    datasets = {ds.get("Name"): ds for ds in root.findall(".//DataSets/DataSet")}
    findings: list[Finding] = []
    for parameter in root.findall(".//ReportParameters/ReportParameter"):
        for kind, label in (("ValidValues", "available values"), ("DefaultValue", "default values")):
            name = (parameter.findtext(f"{kind}/DataSetReference/DataSetName") or "").strip()
            query = datasets[name].find("Query") if name in datasets else None
            if query is None:
                continue
            if _is_literal_query(_dataset_provider(root, query), query.findtext("CommandText") or ""):
                findings.append({
                    "object": f"{parameter.get('Name') or '?'} › {name}",
                    "message": (
                        f"{label} come from dataset '{name}', which only lists typed-in values -- "
                        "type them into the parameter instead and drop the query"
                    ),
                })
    return findings


def _split_top_level(text: str, start: int, end: int) -> list[str]:
    """Comma-separated items of text[start:end] at paren depth 0, quotes respected."""
    items, depth, quote, item_start = [], 0, "", start
    for i in range(start, end):
        char = text[i]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(text[item_start:i].strip())
            item_start = i + 1
    items.append(text[item_start:end].strip())
    return items


def _closing_paren(text: str, open_paren: int) -> int | None:
    depth, quote = 0, ""
    for i in range(open_paren, len(text)):
        char = text[i]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


_SUMMARIZECOLUMNS = re.compile(r"(?i)\bsummarizecolumns\s*\(")
_DAX_COLUMN = re.compile(r"^'?([^'\[]+?)'?\[([^\]]+)\]$")
_DAX_NAME = re.compile(r'^"([^"]+)"$')


def _dax_columns(command_text: str) -> list[tuple[str, str]]:
    """(label, DataField) for each column SUMMARIZECOLUMNS returns."""
    match = _SUMMARIZECOLUMNS.search(command_text)
    close = _closing_paren(command_text, match.end() - 1) if match else None
    if close is None:
        return []
    args = _split_top_level(command_text, match.end(), close)
    columns, skip_next = [], False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        column, name = _DAX_COLUMN.match(arg), _DAX_NAME.match(arg)
        if column:
            columns.append((f"{column.group(1).strip()}[{column.group(2)}]",) * 2)
        elif name and index + 1 < len(args):
            columns.append((name.group(1), f"[{name.group(1)}]"))
            skip_next = True
    return columns


_SQL_SELECT_HEAD = re.compile(r"(?is)^\s*select\s+(?:distinct\s+|all\s+)?(?:top\s*\(?\s*\d+\s*\)?\s*(?:percent\s+)?)?")
_SQL_FROM_OR_PAREN = re.compile(r"(?i)\bfrom\b|[()]")
_SQL_ALIAS = re.compile(r'(?is)\bas\s+[\["]?([^\]"]+?)[\]"]?\s*$')
_SQL_BARE_COLUMN = re.compile(r'^(?:[\w\["\]]+\.)*[\["]?([\w ]+?)[\]"]?$')
_SQL_IMPLICIT_ALIAS = re.compile(r'\)\s+[\["]?(\w+)[\]"]?$')


def _outer_from(sql: str, start: int) -> int:
    """Index of the select list's own FROM (not one inside a subquery), or the end."""
    depth = 0
    for match in _SQL_FROM_OR_PAREN.finditer(sql, start):
        found = match.group()
        if found == "(":
            depth += 1
        elif found == ")":
            depth -= 1
        elif depth == 0:
            return match.start()
    return len(sql)


def _sql_columns(command_text: str) -> list[tuple[str, str]] | None:
    """(label, DataField) for each select-list column, or None when it can't be judged."""
    sql = _strip_sql_comments(_SQL_STRING.sub(lambda m: "'" + "x" * (len(m.group()) - 2) + "'", command_text))
    head = _SQL_SELECT_HEAD.match(sql)
    if head is None:
        return None
    columns = []
    for item in _split_top_level(sql, head.end(), _outer_from(sql, head.end())):
        if item == "*" or item.endswith(".*"):
            return None
        name = _SQL_ALIAS.search(item) or _SQL_BARE_COLUMN.match(item) or _SQL_IMPLICIT_ALIAS.search(item)
        if name:
            columns.append((name.group(1).strip(),) * 2)
    return columns


def _check_ds06_orphan_query_columns(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for dataset in root.findall(".//DataSets/DataSet"):
        query = dataset.find("Query")
        if query is None or (query.findtext("CommandType") or "").strip().lower() == "storedprocedure":
            continue
        provider = _dataset_provider(root, query)
        command_text = query.findtext("CommandText") or ""
        if provider == "PBIDATASET":
            columns = _dax_columns(command_text)
        elif provider.upper() in _RELATIONAL_PROVIDERS:
            columns = _sql_columns(command_text) or []
        else:
            continue
        read = {(f.findtext("DataField") or "").strip().lower() for f in dataset.findall("Fields/Field")}
        findings.extend(
            {
                "object": f"{dataset.get('Name') or '?'} › {label}",
                "message": f"the query returns {label} but no field reads it -- drop it from the query",
            }
            for label, data_field in columns
            if data_field.lower() not in read
        )
    return findings


_DATA_REGIONS = ("Tablix", "Chart", "GaugePanel", "Map")
_DEFAULT_DS04_MIN_SIMILARITY = 0.9


def _check_ds04_share_one_dataset(root: ET.Element, _namespace: str, rule: dict[str, Any]) -> list[Finding]:
    min_similarity = rule.get("min_similarity", _DEFAULT_DS04_MIN_SIMILARITY)
    feeding = {(region.findtext("DataSetName") or "").strip() for tag in _DATA_REGIONS for region in root.iter(tag)}
    queries = []
    for dataset in root.findall(".//DataSets/DataSet"):
        query = dataset.find("Query")
        if query is None or dataset.get("Name") not in feeding:
            continue
        text = " ".join((query.findtext("CommandText") or "").lower().split())
        queries.append((dataset.get("Name"), (query.findtext("DataSourceName") or "").strip(), text))
    findings: list[Finding] = []
    for i, (name, source, text) in enumerate(queries):
        for other, other_source, other_text in queries[i + 1 :]:
            if not text or source != other_source:
                continue
            similarity = difflib.SequenceMatcher(None, text, other_text).ratio()
            if similarity >= min_similarity:
                findings.append({
                    "object": f"{name} ≈ {other}",
                    "message": (
                        f"datasets '{name}' and '{other}' run {similarity:.0%}-identical queries on the same "
                        "source -- share one dataset and filter each region, or pass a parameter"
                    ),
                })
    return findings
