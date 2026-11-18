"""`contract init` and a contract that already exists (PBIR Slicer Default State epic).

Read once, before any question is asked, so nobody answers every slicer only
to be refused at the end: a comment that rewriting would drop, a file that
isn't a contract, an id two rules share, or, with no contract yet, a report
with no logicalId to pair by. The ids the contract gives each slicer rule and
bookmark navigator are returned with what they belong to, so init reuses a
rule's own id and never hands it to anything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ._navigator_contract import NAVIGATORS_PROPERTY
from ._slicer_contract import ENGINE
from ._slicer_contract_run import report_logical_id

Owner = tuple[Any, ...]  # ("slicer", page, table, column) or ("navigator", page)


class ExistingContractError(Exception):
    """Something about the contract (or, with none yet, the report) that init couldn't write past."""


def slicer_owner(page: Any, table: Any, column: Any) -> Owner:
    return ("slicer", page, table, column)


def navigator_owner(page: Any) -> Owner:
    return ("navigator", page)


def read_existing(path: Path, report: Path, force: bool) -> tuple[dict | None, dict[str, Owner]]:
    """(the contract at ``path``, or None when there is none yet; what each id in it belongs to).

    Raises ExistingContractError, saying how to fix it, for anything init couldn't write.
    """
    if not path.exists():
        if not report_logical_id(report):
            raise ExistingContractError(f"{report} has no .platform logicalId, which a contract pairs by; "
                                        "save the report from Power BI Desktop or Fabric to create it")
        return None, {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExistingContractError(f"{path} can't be read ({exc})") from exc
    if "#" in text and not force:
        raise ExistingContractError(f"{path} contains '#' (a comment), which rewriting would drop; edit it by "
                                    "hand, or pass --force to rewrite it (see the result first with --dry-run)")
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExistingContractError(f"{path} isn't valid YAML; fix it or move it aside:\n{exc}") from exc
    if not isinstance(document, dict):
        raise ExistingContractError(f"{path} isn't a contract (not a YAML mapping); move it aside or fix it")
    owners: dict[str, Owner] = {}
    for rule_id, owner in _ids(document):
        if rule_id in owners:
            raise ExistingContractError(f"{path}: id {rule_id!r} is used by more than one rule; give each its "
                                        "own id, then run init again")
        owners[rule_id] = owner
    return document, owners


def _ids(document: dict):
    """Every fab-test rule id in the contract, with what it checks. Shapes the reader rejects are skipped:
    the read-back before writing reports them."""
    for table in _dicts(document.get("schema")):
        for column in _dicts(table.get("properties")):
            for rule in _dicts(column.get("quality")):
                implementation = rule.get("implementation")
                if rule.get("engine") == ENGINE and isinstance(rule.get("id"), str):
                    page = implementation.get("page") if isinstance(implementation, dict) else None
                    yield rule["id"], slicer_owner(page, table.get("name"), column.get("name"))
    for prop in _dicts(document.get("customProperties")):
        if prop.get("property") == NAVIGATORS_PROPERTY:
            for entry in _dicts(prop.get("value")):
                if isinstance(entry.get("id"), str):
                    yield entry["id"], navigator_owner(entry.get("page"))


def _dicts(items: Any) -> list[dict]:
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
