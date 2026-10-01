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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ._rdl_checks_query import (
    _check_ds01_no_embedded_credentials,
    _check_ds02_unused_datasets,
    _check_ds05_no_select_star,
    _check_ds07_prefer_stored_procedures,
    _check_qry01_filter_in_query,
    _check_qry02_no_calculated_fields,
    _check_qry03_aggregate_in_query,
    _check_qry04_sort_in_query,
    _check_qry05_convert_types_in_query,
    _check_qry06_join_in_query,
    _check_qry07_move_complex_sql,
    _check_str01_current_schema,
)
from ._rdl_checks_report import (
    _check_acc01_alt_text,
    _check_acc02_chart_alt_text_quality,
    _check_acc03_table_caption,
    _check_acc08_html_link_alt_text,
    _check_lay01_body_fits_page,
    _check_lay02_avoid_total_pages,
    _check_lay03_sub01_subreport_in_tablix,
    _check_lay04_interactive_sort,
    _check_lay05_large_reports_page_breaks,
    _check_lay06_avoid_embedded_images,
    _check_prm01_default_value,
    _check_prm03_parameter_count,
    _check_prm04_multivalue_nullable,
    _check_prm05_show_parameter_values,
    _check_sub02_subreport_count,
)
from ._rdl_common import (
    CURRENT_RDL_NAMESPACE,  # noqa: F401 -- re-exported for callers and tests
    Finding,
    RdlCheck,
)


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
    rules = data.get("rules", []) if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise ValueError("a rules file is an object with a 'rules' list")  # noqa: TRY004 -- value validation
    seen: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            raise ValueError("every rule is an object with a string 'id'")  # noqa: TRY004 -- value validation
        rule_id = rule["id"]
        if rule_id in seen:
            raise ValueError(f"duplicate rule id {rule_id}")
        seen.add(rule_id)
        if rule.get("status", "active") not in ("active", "planned"):
            raise ValueError(f"rule {rule_id} has status {rule['status']!r}; use 'active' or 'planned'")
        if rule.get("severity", "error") not in ("error", "warning", "info"):
            raise ValueError(f"rule {rule_id} has severity {rule['severity']!r}; use 'error', 'warning' or 'info'")
    return rules


def _is_active(rule: dict[str, Any]) -> bool:
    """A rule runs and shows in results only once verified against a real fixture.

    "planned" rules stay in the catalog as the roadmap but are invisible to
    a run; a catalog entry with no status (a custom catalog) is active.
    """
    return rule.get("status", "active") == "active"


# Maps a rule ID to the function that checks it, given a parsed (namespace-
# stripped) report root; filled by CHECKS.update below. A catalog entry with
# no function here is reported as "skip", not "pass" (build_test_results).
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
            rows.extend(
                {**base, "object": h.get("object", ""), "message": h["message"], "status": h["severity"], **urls}
                for h in hits
            )
            continue
        status = "pass" if rule_id in implemented and not rule.get("disabled") else "skip"
        rows.append({**base, "object": "", "message": rule.get("description", ""), "status": status, **urls})
    return rows
