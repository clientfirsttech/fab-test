"""Read a PBIR report's slicers and what each opens with (PBIR Slicer Default State epic).

The inverse of `_slicer_rules`: it decodes the selection shapes Power BI
Desktop writes (see fabric-artifacts/README.md) back into what the user
sees, in the contract's own vocabulary -- `selected`, `contains`, `range`
or `relative` -- so `fab-test pbir contract init` can offer each one.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SLICER_TYPES = ("slicer", "textSlicer", "listSlicer", "advancedSlicerVisual")
_RELATIVE_MODES = ("'Relative'", "'RelativeDatePicker'")
_DATETIME = re.compile(r"^datetime'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})'$")


@dataclass(frozen=True)
class Slicer:
    page: str
    table: str
    column: str
    current: dict[str, Any]  # {check: expected}, e.g. {"selected": ["Bad"]}


def decode_literal(literal: str) -> Any:
    """What the user sees for a DAX literal Desktop wrote: 'Bad', 1940L, 2.5D, datetime'...'."""
    match = _DATETIME.match(literal)
    if match:
        day = datetime.date.fromisoformat(match.group(1))
        return day if match.group(2) == "00:00:00" else datetime.datetime.fromisoformat(f"{match[1]}T{match[2]}")
    if literal in ("true", "false"):
        return literal == "true"
    if len(literal) >= 2 and literal[0] == literal[-1] == "'":
        return literal[1:-1].replace("''", "'")
    if literal[-1:] == "L" and literal[:-1].lstrip("-").isdigit():
        return int(literal[:-1])
    if literal[-1:] == "D":
        return float(literal[:-1])
    return literal


def read_slicers(report: Path) -> list[Slicer]:
    """Every slicer bound to one column, in page order, then top-to-bottom, left-to-right."""
    pages_dir = report / "definition" / "pages"
    order = _load(pages_dir / "pages.json").get("pageOrder", [])
    slicers = []
    for page_id in order:
        page = _load(pages_dir / page_id / "page.json").get("displayName", page_id)
        visuals = [_load(p) for p in (pages_dir / page_id / "visuals").glob("*/visual.json")]
        visuals.sort(key=lambda v: (v.get("position", {}).get("y", 0), v.get("position", {}).get("x", 0)))
        slicers.extend(s for s in (_slicer(page, v) for v in visuals) if s)
    return slicers


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}


def _slicer(page: str, container: dict) -> Slicer | None:
    visual = container.get("visual", {})
    projections = visual.get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
    column = projections[0].get("field", {}).get("Column") if projections else None
    if visual.get("visualType") not in SLICER_TYPES or not column:
        return None
    table = column.get("Expression", {}).get("SourceRef", {}).get("Entity")
    return Slicer(page, table, column.get("Property"), _current(visual))


def _current(visual: dict) -> dict[str, Any]:
    objects = visual.get("objects", {})
    where = (objects.get("general") or [{}])[0].get("properties", {}).get("filter", {}).get("filter", {})
    data = (objects.get("data") or [{}])[0].get("properties", {})
    if visual.get("visualType") == "textSlicer":
        return {"contains": [decode_literal(c["Right"]["Literal"]["Value"]) for c in _find(where, "Contains")]}
    if _literal(data, "mode") in _RELATIVE_MODES and "relativeRange" in data:
        return {"relative": {
            "range": decode_literal(_literal(data, "relativeRange")),
            "duration": int(float(_literal(data, "relativeDuration").rstrip("D"))),
            "period": decode_literal(_literal(data, "relativePeriod")),
        }}
    comparisons = list(_find(where, "Comparison"))
    if comparisons:
        return {"range": dict(_bound(c) for c in comparisons)}
    names = [m["0"] for w in where.get("Where", []) for m in
             w.get("Annotations", {}).get("filterExpressionMetadata", {}).get("valueMap", [])]
    if names:  # a field parameter: Desktop filters the hidden Fields column; names are what the user sees
        return {"selected": names}
    return {"selected": [decode_literal(row[0]["Literal"]["Value"])
                         for c in _find(where, "In") for row in c.get("Values", [])]}


def _literal(properties: dict, name: str) -> str:
    return properties.get(name, {}).get("expr", {}).get("Literal", {}).get("Value", "")


def _bound(comparison: dict) -> tuple[str, datetime.date]:
    day = decode_literal(comparison["Right"]["Literal"]["Value"])
    day = day.date() if isinstance(day, datetime.datetime) else day
    kind = comparison["ComparisonKind"]
    if kind in (1, 2):
        return "from", day + datetime.timedelta(days=1) if kind == 1 else day
    return "to", day - datetime.timedelta(days=1) if kind == 3 else day


def _find(node: Any, key: str):
    """Every value under ``key`` anywhere in ``node``."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            else:
                yield from _find(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from _find(item, key)
