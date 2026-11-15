"""Read a PBIR report's slicers and what each opens with (PBIR Slicer Default State epic).

The inverse of `_slicer_rules`: it decodes the selection shapes Power BI
Desktop writes (see fabric-artifacts/README.md) back into what the user
sees, in the contract's own vocabulary -- `selected` (`all` for "Select
all"), `contains`, `range` or `relative`. It reads exactly the shapes the compiled rules can check;
anything else ("all except" selections, several columns, a hierarchy, a
value that wouldn't round-trip) is `{"unsupported": reason}`, which
`fab-test pbir contract init` offers only to skip.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._slicer_contract import SELECT_ALL, dax_literal

SLICER_TYPES = ("slicer", "textSlicer", "listSlicer", "advancedSlicerVisual")
RELATIVE_MODES = ("'Relative'", "'RelativeDatePicker'")
INVERTED = "isInvertedSelectionMode"  # "Select all" ticked; any filter then lists what is unticked
_DATETIME = re.compile(r"^datetime'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})'$")
_NOT_PLAIN = "a selection that isn't a plain list of values (for example 'all except', or several columns)"


@dataclass(frozen=True)
class Slicer:
    page: str
    table: str
    column: str
    current: dict[str, Any]  # {check: expected}, e.g. {"selected": ["Bad"]}, or {"unsupported": reason}


def decode_literal(literal: str) -> Any:
    """What the user sees for a DAX literal Desktop wrote: 'Bad', 1940L, 2.5D, datetime'...', null."""
    match = _DATETIME.match(literal)
    if match:
        day = datetime.date.fromisoformat(match.group(1))
        return day if match.group(2) == "00:00:00" else datetime.datetime.fromisoformat(f"{match[1]}T{match[2]}")
    if literal in _CONSTANTS:
        return _CONSTANTS[literal]
    if len(literal) >= 2 and literal[0] == literal[-1] == "'":
        return literal[1:-1].replace("''", "'")
    return _decode_number(literal)


_CONSTANTS = {"true": True, "false": False, "null": None}


def _decode_number(literal: str) -> Any:
    """1940L is a whole number, 2.5D a double; anything else (2.5M) stays as written."""
    if literal[-1:] == "L" and literal[:-1].lstrip("-").isdigit():
        return int(literal[:-1])
    if literal[-1:] == "D":
        try:
            return float(literal[:-1])
        except ValueError:
            pass
    return literal


def read_slicers(report: Path) -> list[Slicer]:
    """Every slicer, in page order, then top-to-bottom, left-to-right. Raises OSError/ValueError on bad JSON."""
    return [s for page, visuals in page_visuals(report) for s in (_slicer(page, v) for v in visuals) if s]


def page_visuals(report: Path):
    """(page display name, its visual containers top-to-bottom, left-to-right) in page order."""
    pages_dir = report / "definition" / "pages"
    for page_id in load_json(pages_dir / "pages.json").get("pageOrder", []):
        page = load_json(pages_dir / page_id / "page.json").get("displayName", page_id)
        visuals = [load_json(p) for p in sorted((pages_dir / page_id / "visuals").glob("*/visual.json"))]
        visuals.sort(key=lambda v: (v.get("position", {}).get("y", 0), v.get("position", {}).get("x", 0)))
        yield page, visuals


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}


def _slicer(page: str, container: dict) -> Slicer | None:
    visual = container.get("visual", {})
    if visual.get("visualType") not in SLICER_TYPES:
        return None
    projections = visual.get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
    column = projections[0].get("field", {}).get("Column") if projections else None
    if not column:
        return None
    table = column.get("Expression", {}).get("SourceRef", {}).get("Entity")
    current = {"unsupported": "a hierarchy or several fields"} if len(projections) > 1 else _current(visual)
    return Slicer(page, table, column.get("Property"), current)


def _current(visual: dict) -> dict[str, Any]:
    objects = visual.get("objects", {})
    general = (objects.get("general") or [{}])[0].get("properties", {})
    rows = general.get("filter", {}).get("filter", {}).get("Where", [])
    data = (objects.get("data") or [{}])[0].get("properties", {})
    if visual.get("visualType") == "textSlicer":
        values = [c["Right"]["Literal"]["Value"] for c in _find(rows, "Contains")]
        return _contains(values, rows)
    everything = _select_all(rows, data, general)
    if everything or not rows:
        return {"selected": SELECT_ALL if everything else []}
    if len(rows) > 1:
        return {"unsupported": _NOT_PLAIN}
    if _literal(data, "mode") in RELATIVE_MODES and "relativeRange" in data and list(_find(rows, "DateSpan")):
        return {"relative": {
            "range": decode_literal(_literal(data, "relativeRange")),
            "duration": int(float(_literal(data, "relativeDuration").rstrip("D"))),
            "period": decode_literal(_literal(data, "relativePeriod")),
        }}
    comparisons = list(_find(rows, "Comparison"))
    if comparisons:
        return _range(comparisons)
    return _selected(rows[0])


def _select_all(rows: list, data: dict, general: dict) -> bool:
    """"Select all" with nothing unticked: inverted mode, and no filter or "all except" nothing."""
    if "true" not in (_literal(data, INVERTED), _literal(general, INVERTED)):
        return False
    if not rows:
        return True
    inner = rows[0].get("Condition", {}).get("Not", {}).get("Expression", {}).get("In", {})
    return len(rows) == 1 and bool(inner) and not inner.get("Values")


def _contains(literals: list[str], rows: list) -> dict[str, Any]:
    if rows and not literals:
        return {"unsupported": "an input slicer filter other than Contains"}
    return _round_tripped("contains", literals)


def _range(comparisons: list[dict]) -> dict[str, Any]:
    if any(c.get("ComparisonKind") not in (2, 3) for c in comparisons) or len(comparisons) > 2:
        return {"unsupported": "a date range other than from/to"}
    bounds = {}
    for c in comparisons:
        day = decode_literal(c["Right"]["Literal"]["Value"])
        day = day.date() if isinstance(day, datetime.datetime) else day
        if not isinstance(day, datetime.date):
            return {"unsupported": "a range that isn't between dates"}
        bounds["from" if c["ComparisonKind"] == 2 else "to"] = (
            day if c["ComparisonKind"] == 2 else day - datetime.timedelta(days=1))
    return {"range": bounds}


def _selected(row: dict) -> dict[str, Any]:
    condition = row.get("Condition", {})
    if list(condition) != ["In"] or len(condition["In"].get("Expressions", [])) != 1:
        return {"unsupported": _NOT_PLAIN}
    names = [m["0"] for m in row.get("Annotations", {}).get("filterExpressionMetadata", {}).get("valueMap", [])]
    if names:  # a field parameter: Desktop filters the hidden Fields column; names are what the user sees
        return {"selected": names}
    return _round_tripped("selected", [r[0]["Literal"]["Value"] for r in condition["In"].get("Values", [])])


def _round_tripped(check: str, literals: list[str]) -> dict[str, Any]:
    values = [decode_literal(literal) for literal in literals]
    lost = [literal for literal, value in zip(literals, values, strict=True) if dax_literal(value) != literal]
    if lost:
        return {"unsupported": f"a value fab-test can't write back exactly ({', '.join(lost)})"}
    return {check: values}


def _literal(properties: dict, name: str) -> str:
    return properties.get(name, {}).get("expr", {}).get("Literal", {}).get("Value", "")


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
