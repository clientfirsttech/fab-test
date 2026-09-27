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
from collections.abc import Callable
from pathlib import Path
from typing import Any

Finding = dict[str, Any]
RdlCheck = Callable[[ET.Element], list[Finding]]


class RdlParseError(Exception):
    """Raised when a .rdl file can't be read or parsed as XML."""


def parse_rdl(path: Path) -> ET.Element:
    """Parse an ``.rdl`` file and return its root element, tag names stripped
    of their namespace prefix.

    RDL's default ``xmlns`` differs by schema version (2008/2010/2016), and
    report-designer tooling can emit any of them. Stripping ``{uri}`` from
    every element's tag once, here, means every check function below can
    match elements (``Tablix``, ``Subreport``, ``ToolTip``, ...) by local
    name and never hard-code one xmlns.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise RdlParseError(f"{path.name} is not well-formed XML: {exc}") from exc
    except OSError as exc:
        raise RdlParseError(f"could not read {path.name}: {exc}") from exc

    root = tree.getroot()
    for element in root.iter():
        if isinstance(element.tag, str) and "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]
    return root


def load_rule_catalog(path: Path) -> list[dict[str, Any]]:
    """Load the RDL rule catalog's ``"rules"`` list from ``path``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("rules", [])


# Maps a rule ID to the function that checks it, given a parsed (namespace-
# stripped) report root. Empty until later RDL Static Analysis epic tasks
# register the STR/DS/QRY/PRM/LAY/SUB/ACC checks -- a catalog entry with no
# function here yet is reported as "skip", not "pass" (build_test_results).
CHECKS: dict[str, RdlCheck] = {}


def run_checks(root: ET.Element, catalog: list[dict[str, Any]]) -> list[Finding]:
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
            for finding in check(root)
        )
    return findings


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
