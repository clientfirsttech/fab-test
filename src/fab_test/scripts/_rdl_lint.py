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
# Every check gets the same two arguments -- the parsed (namespace-stripped)
# report root, and the report's own original schema namespace URI -- even
# though only STR-01 reads the second one. One dataset name shape is
# simpler than a dataclass wrapper for the one rule that needs it.
RdlCheck = Callable[[ET.Element, str], list[Finding]]

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
    """
    findings: list[Finding] = []
    for rule in catalog:
        if rule.get("disabled"):
            continue
        check = CHECKS.get(rule["id"])
        if check is None:
            continue
        findings.extend(
            {**finding, "rule": rule["id"], "severity": finding.get("severity", rule.get("severity", "warning"))}
            for finding in check(root, namespace)
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


# --------------------------------------------------------------------------- #
# Structure and data source rules (STR-01, DS-01, DS-02, DS-05, DS-07)
# --------------------------------------------------------------------------- #


def _check_str01_current_schema(_root: ET.Element, namespace: str) -> list[Finding]:
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


def _check_ds01_shared_data_source(root: ET.Element, _namespace: str) -> list[Finding]:
    findings: list[Finding] = []
    for source in root.findall(".//DataSources/DataSource"):
        name = source.get("Name") or "?"
        conn_props = source.find("ConnectionProperties")
        if conn_props is None:
            continue
        provider = (conn_props.findtext("DataProvider") or "").strip()
        connect_string = conn_props.findtext("ConnectString") or ""
        if _CREDENTIAL_PATTERN.search(connect_string):
            # Never echo the matched text itself -- only that something
            # password-shaped is there, so the finding can't leak it.
            findings.append({
                "object": name,
                "message": (
                    "connect string appears to embed a password; use a shared "
                    "data source or a secure credential store instead"
                ),
            })
        # PBIDATASET (a bound semantic model) and PQO (Power Query) are
        # Power BI's own required embedded-connection shape -- Fabric has
        # no shared "DataSourceReference" alternative for either, unlike a
        # classic SSRS SQL/OLEDB connection, so only other providers are
        # asked to use one.
        if provider not in _NON_RELATIONAL_PROVIDERS and source.find("DataSourceReference") is None:
            findings.append({
                "object": name,
                "message": "embeds its connection instead of referencing a shared data source (DataSourceReference)",
            })
    return findings


def _check_ds02_unused_datasets(root: ET.Element, _namespace: str) -> list[Finding]:
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


def _check_ds05_no_select_star(root: ET.Element, _namespace: str) -> list[Finding]:
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
                        "EVALUATE of a whole table with no column projection is the "
                        "DAX equivalent of SELECT * -- project only the columns the report uses"
                    ),
                })
        elif provider not in _NON_RELATIONAL_PROVIDERS and _SQL_SELECT_STAR.search(command_text):
            findings.append({
                "object": name,
                "message": "SELECT * fetches every column -- list only the columns the report uses",
            })
    return findings


def _check_ds07_prefer_stored_procedures(root: ET.Element, _namespace: str) -> list[Finding]:
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
                    "uses inline SQL text; a stored procedure gets a cached plan, "
                    "reuse, and fixes without republishing"
                ),
            })
    return findings


CHECKS.update({
    "STR-01": _check_str01_current_schema,
    "DS-01": _check_ds01_shared_data_source,
    "DS-02": _check_ds02_unused_datasets,
    "DS-05": _check_ds05_no_select_star,
    "DS-07": _check_ds07_prefer_stored_procedures,
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
    fires on more than one element, only the first hit's object/message is
    shown here; `findings` itself carries all of them. A row's message is
    the finding's own text when it fired, or the catalog's rule
    description otherwise -- readable either way, never a bare status word.
    """
    hits_by_rule: dict[str, list[Finding]] = {}
    for finding in findings:
        hits_by_rule.setdefault(finding["rule"], []).append(finding)

    rows = []
    for rule in catalog:
        rule_id = rule["id"]
        hits = hits_by_rule.get(rule_id)
        if rule.get("disabled"):
            status = "skip"
        elif hits:
            status = hits[0]["severity"]
        elif rule_id in implemented:
            status = "pass"
        else:
            status = "skip"
        rows.append({
            "rule": rule_id,
            "severity": rule.get("severity", "warning"),
            "object": hits[0].get("object", "") if hits else "",
            "message": hits[0]["message"] if hits else rule.get("description", ""),
            "status": status,
        })
    return rows
