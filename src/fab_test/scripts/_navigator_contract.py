"""Read a contract's bookmark navigator entries (PBIR Bookmark Navigator Default epic).

A navigator has no table or column, and ODCS quality rules sit only on schema
objects and properties, so a contract lists navigators in its own custom
property beside `fabTestReport`:

    customProperties:
      - property: fabTestBookmarkNavigators
        value:
          - {id: overview-navigator, page: Overview, selected: Home}   # null: nothing preselected

`selected` is the bookmark's display name. No imports from the slicer modules,
so `_slicer_contract` can read these without a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NAVIGATORS_PROPERTY = "fabTestBookmarkNavigators"
_KEYS = ("id", "page", "selected", "severity")


@dataclass(frozen=True)
class NavigatorExpectation:
    rule_id: str
    page: str
    selected: str | None  # a bookmark display name; None means nothing preselected
    severity: str


def parse_navigators(value: Any, severities: tuple[str, ...], errors: list[str]) -> list[NavigatorExpectation]:
    """The entries of a `fabTestBookmarkNavigators` value, each mistake added to ``errors`` by path."""
    where = f"customProperties.{NAVIGATORS_PROPERTY}"
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{where}: must be a list of navigator entries (id, page, selected)")
        return []
    result = []
    for i, entry in enumerate(value):
        expectation = _entry(entry, f"{where}[{i}]", severities, errors)
        if expectation:
            result.append(expectation)
    return result


def _entry(entry: Any, where: str, severities: tuple[str, ...], errors: list[str]) -> NavigatorExpectation | None:
    if not isinstance(entry, dict):
        errors.append(f"{where}: must be a mapping with id, page and selected, got {entry!r}")
        return None
    before = len(errors)
    errors.extend(f"{where}.{key}: unknown key; a navigator is named by its page" for key in entry if key not in _KEYS)
    for key, meaning in (("id", "findings are named by it"), ("page", "the page's display name")):
        if not isinstance(entry.get(key), str) or not entry[key]:
            errors.append(f"{where}.{key}: required, {meaning}")
    selected = entry.get("selected", "")
    if selected is not None and (not isinstance(selected, str) or not selected):
        errors.append(f"{where}.selected: required, a bookmark's display name (quoted if it looks like a number), "
                      "or null for nothing preselected")
    severity = entry.get("severity", "error")
    if severity not in severities:
        errors.append(f"{where}.severity: must be one of {', '.join(severities)}, got {severity!r}")
    if len(errors) > before:
        return None
    return NavigatorExpectation(entry["id"], entry["page"], selected, severity)
