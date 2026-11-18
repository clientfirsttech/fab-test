"""`contract init`'s current-period suggestions and fiscal-year questions (PBIR Slicer Default State epic).

A slicer whose value is today's period ("FY27-S1", "2026 H2") can follow the
current period. Calendar fields need nothing more; fiscal fields need the
company's fiscal year, which nothing in a report states. So the fiscal
questions are asked only when an answer uses a fiscal field, have no default
unless the contract already holds a `fabTestCalendar`, and an answer under
which a slicer isn't on today's period is refused rather than written.
"""

from __future__ import annotations

import calendar
import datetime
import string
from pathlib import Path
from typing import Any

import yaml

from ._slicer_calendar import FIELDS, calendar_fields

START = "calendar.fiscal_year_start_month"
NAMED_BY = "calendar.fiscal_year_named_by"
CALENDAR_PROPERTY = "fabTestCalendar"
FISCAL_FIELDS = frozenset(f for f in FIELDS if f.startswith("fiscal_"))
_NAMINGS = ("end", "start")
FORMATS = (
    "FY{fiscal_year_short}-S{fiscal_semester}", "FY{fiscal_year_short} S{fiscal_semester}",
    "FY{fiscal_year_short}-Q{fiscal_quarter}", "FY{fiscal_year_short} Q{fiscal_quarter}",
    "FY{fiscal_year}", "FY{fiscal_year_short}", "{year} H{half}", "{year}-H{half}", "H{half} {year}",
    "{year} Q{quarter}", "{year}-Q{quarter}", "Q{quarter} {year}", "{year}-{month:02}",
    "{year}", "{fiscal_year}",
)

Fit = tuple[int, str]  # (fiscal_year_start_month, fiscal_year_named_by)


def uses_fiscal(text: str) -> bool:
    """Whether a format names a fiscal field, so it needs the company's fiscal year."""
    try:
        return any(name in FISCAL_FIELDS for _, name, _, _ in string.Formatter().parse(text) if name)
    except ValueError:
        return False


def renders(text: str, as_of: datetime.date, fiscal: dict | None) -> Any:
    """What ``text`` resolves to on ``as_of``; a value that is one bare field keeps its type."""
    fields = calendar_fields(as_of, fiscal)
    bare = text[1:-1] if text.startswith("{") and text.endswith("}") and text.count("{") == 1 else None
    return fields[bare] if bare in FIELDS else text.format_map(fields)


def suggestion(current: dict, as_of: datetime.date) -> tuple[str, list[Fit] | None] | None:
    """The first format that renders a single current value today: with the fiscal years under which it
    does (start month and naming), or None for a calendar-only format. None when nothing does."""
    values = current.get("selected")
    values = values if isinstance(values, list) else []  # `all` names no value
    if len(values) != 1 or not isinstance(values[0], (str, int)) or isinstance(values[0], bool):
        return None
    for text in FORMATS:
        if not uses_fiscal(text):
            if renders(text, as_of, None) == values[0]:
                return text, None
            continue
        fits = [(start, named) for start in range(1, 13) for named in _NAMINGS
                if renders(text, as_of, {"fiscal_year_start_month": start, "fiscal_year_named_by": named})
                == values[0]]
        if fits:
            return text, fits
    return None


def existing_calendar(path: Path) -> dict | None:
    """The contract's `fabTestCalendar`, if it has a readable one: a person's earlier answer."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    properties = document.get("customProperties") if isinstance(document, dict) else None
    value = next((p.get("value") for p in properties or [] if isinstance(p, dict)
                  and p.get("property") == CALENDAR_PROPERTY), None)
    return value if isinstance(value, dict) else None


def fiscal_questions(questions: list[dict], existing: dict | None) -> list[dict]:
    """The two fiscal-year questions, or none when no suggested format names a fiscal field."""
    fitted = [q for q in questions if q.get("_fits")]
    if not fitted:
        return []
    fits = set.intersection(*(set(q["_fits"]) for q in fitted))
    months = sorted({start for start, _ in fits})
    applies_to = [q["id"] for q in fitted]
    existing = existing or {}
    if len(months) > 1:
        fit = ", ".join(map(str, months[:-1])) + f" or {months[-1]}"
    else:
        fit = str(months[0]) if months else "no single fiscal year"
    return [
        {"id": START,
         "prompt": f"Which month does your company's fiscal year start in (1-12)? Today's values fit {fit}.",
         "suggested": existing.get("fiscal_year_start_month"), "reproduces": months, "applies_to": applies_to,
         "needs_human": True},
        {"id": NAMED_BY, "prompt": "Is a fiscal year named by the calendar year it ends in (end) or starts in (start)?",
         "choices": list(_NAMINGS), "suggested": existing.get("fiscal_year_named_by"), "applies_to": applies_to,
         "needs_human": True},
    ]


def naming_prompt(start: int, as_of: datetime.date) -> str:
    """The naming question for the fiscal year around ``as_of``, in real months and years."""
    first = as_of.year if as_of.month >= start else as_of.year - 1
    last_month = calendar.month_name[(start - 2) % 12 + 1]
    return (f"Is {calendar.month_name[start]} {first} to {last_month} {first + 1} called FY{(first + 1) % 100:02d} "
            f"(the year it ends in) or FY{first % 100:02d} (the year it starts in)?")


def fiscal_calendar(answers: dict, needed_by: list[str]) -> dict | None:
    """The `fabTestCalendar` to write, or None when no rule needs one. Raises ValueError naming what's missing."""
    if not needed_by:
        return None
    start = answers.get(START)
    because = f"because {', '.join(needed_by)} {'follows' if len(needed_by) == 1 else 'follow'} the fiscal year"
    if start is None:
        raise ValueError(f"{START}: required, {because}; which month does your company's fiscal year start in?")
    named_by = answers.get(NAMED_BY) or ("end" if start == 1 else None)  # a January year is named the same either way
    if named_by is None:
        raise ValueError(f"{NAMED_BY}: required, {because}; "
                         "is a fiscal year named by the year it ends in or starts in?")
    return {"fiscal_year_start_month": start, "fiscal_year_named_by": named_by}


def merge_calendar(document: dict, calendar: dict | None, force: bool) -> str | None:
    """Add, keep or (with ``force``) replace the contract's `fabTestCalendar`."""
    if not calendar:
        return None
    properties = document.setdefault("customProperties", [])
    existing = next((p for p in properties if isinstance(p, dict) and p.get("property") == CALENDAR_PROPERTY), None)
    if existing is None:
        properties.append({"property": CALENDAR_PROPERTY, "value": calendar})
        return "added"
    if existing.get("value") == calendar:
        return "unchanged"
    if force:
        existing["value"] = calendar
        return "replaced"
    return "kept"


def mismatch(rule_id: str, field: str, expected: Any, opens_with: Any, fiscal: dict | None, fiscal_rule: bool) -> str:
    """Why a current-period rule can't be written: the report isn't on today's period under these answers."""
    under = ""
    if fiscal_rule and fiscal:
        month = calendar.month_name[fiscal["fiscal_year_start_month"]]
        under = f" with a fiscal year starting in {month}, named by the year it {fiscal['fiscal_year_named_by']}s in,"
    return (f"{rule_id}:{under} today is {expected}, but {field} opens with {opens_with}; either the report is out "
            "of date (fix the slicer in Desktop and run init again, or answer keep) or the fiscal year is wrong")
