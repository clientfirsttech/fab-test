"""Resolve calendar-driven slicer expectations (PBIR Slicer Default State epic).

An expected value such as "FY{fiscal_year_short}-S{fiscal_semester}" is a
format string over FIELDS, filled from an as-of date and the contract's
`fabTestCalendar` (fiscal_year_start_month 1-12, default 1; fiscal_year_named_by
start|end, default end). Nothing is evaluated: each placeholder must be a plain
field name, optionally with a format spec such as {month:02}; attribute or index
access, conversions and nested placeholders are refused.
"""

from __future__ import annotations

import dataclasses
import datetime
import string
from typing import Any

from ._slicer_contract import SlicerContract, SlicerExpectation

FIELDS = (
    "year", "year_short", "half", "quarter", "month",
    "fiscal_year", "fiscal_year_short", "fiscal_semester", "fiscal_quarter", "fiscal_month",
)
_CALENDAR_KEYS = ("fiscal_year_start_month", "fiscal_year_named_by")
_NAMINGS = ("start", "end")
_RESOLVED_CHECKS = ("selected", "contains")


class CalendarError(Exception):
    """A calendar setting or format string that can't be resolved; the message names each one."""


def calendar_fields(as_of: datetime.date, calendar: dict[str, Any] | None) -> dict[str, Any]:
    """Every format field for ``as_of`` under ``calendar`` (already validated)."""
    start = (calendar or {}).get("fiscal_year_start_month", 1)
    named_by = (calendar or {}).get("fiscal_year_named_by", "end")
    starts_in = as_of.year if as_of.month >= start else as_of.year - 1
    fiscal_year = starts_in + 1 if start != 1 and named_by == "end" else starts_in
    fiscal_month = (as_of.month - start) % 12 + 1
    return {
        "year": as_of.year,
        "year_short": f"{as_of.year % 100:02d}",
        "half": 1 if as_of.month <= 6 else 2,
        "quarter": (as_of.month - 1) // 3 + 1,
        "month": as_of.month,
        "fiscal_year": fiscal_year,
        "fiscal_year_short": f"{fiscal_year % 100:02d}",
        "fiscal_semester": 1 if fiscal_month <= 6 else 2,
        "fiscal_quarter": (fiscal_month - 1) // 3 + 1,
        "fiscal_month": fiscal_month,
    }


def resolve_contract(contract: SlicerContract, as_of: datetime.date) -> list[SlicerExpectation]:
    """The contract's expectations with every calendar format string filled in for ``as_of``."""
    _validate_calendar(contract.calendar)
    fields = calendar_fields(as_of, contract.calendar)
    errors: list[str] = []
    resolved = [_resolve_expectation(e, fields, errors) for e in contract.expectations]
    if errors:
        raise CalendarError(
            f"{contract.path}: calendar values could not be resolved:\n"
            + "\n".join(f"  {e}" for e in errors)
            + f"\n  valid fields: {', '.join(FIELDS)}"
        )
    return resolved


def _validate_calendar(calendar: Any) -> None:
    if calendar is None:
        return
    if not isinstance(calendar, dict):
        raise CalendarError(f"fabTestCalendar: must be a mapping of {', '.join(_CALENDAR_KEYS)}")
    errors = [f"fabTestCalendar.{key}: unknown setting; valid: {', '.join(_CALENDAR_KEYS)}"
              for key in calendar if key not in _CALENDAR_KEYS]
    start = calendar.get("fiscal_year_start_month", 1)
    if isinstance(start, bool) or not isinstance(start, int) or not 1 <= start <= 12:
        errors.append(f"fabTestCalendar.fiscal_year_start_month: must be a whole number 1-12, got {start!r}")
    if calendar.get("fiscal_year_named_by", "end") not in _NAMINGS:
        errors.append(f"fabTestCalendar.fiscal_year_named_by: must be start or end, "
                      f"got {calendar['fiscal_year_named_by']!r}")
    if errors:
        raise CalendarError("\n".join(errors))


def _resolve_expectation(expectation: SlicerExpectation, fields: dict, errors: list[str]) -> SlicerExpectation:
    if expectation.check not in _RESOLVED_CHECKS:
        return expectation
    values = [_format(v, fields, expectation.rule_id, errors) if isinstance(v, str) else v
              for v in expectation.expected]
    return dataclasses.replace(expectation, expected=values)


def _format(text: str, fields: dict, rule_id: str, errors: list[str]) -> str:
    try:
        parts = list(string.Formatter().parse(text))
    except ValueError as exc:
        errors.append(f"{rule_id}: {text!r} is not a valid format string ({exc})")
        return text
    out = []
    for literal, name, spec, conversion in parts:
        out.append(literal)
        if name is None:
            continue
        if conversion or (spec and "{" in spec) or name not in FIELDS:
            plain = name.isidentifier() and not conversion and not spec
            what = "unknown calendar field" if plain else "only a plain field name is allowed, not"
            errors.append(f"{rule_id}: {what} {name!r} in {text!r}")
            continue
        try:
            out.append(format(fields[name], spec or ""))
        except ValueError as exc:
            errors.append(f"{rule_id}: format spec {spec!r} doesn't fit {name!r} in {text!r} ({exc})")
    return "".join(out)
