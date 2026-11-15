"""Read a slicer contract (PBIR Slicer Default State epic, Contract Format).

A contract is an ODCS v3 document. Its `type: custom`, `engine: fab-test`
quality rules sit on the column a slicer is bound to (schema object = table,
property = column) and state, under `implementation`, the page and what the
slicer opens with, as one of:

- `selected`: values or field-parameter display names; `[]` means nothing
  ticked, `all` means "Select all" ticked (the same rows, but not the same
  slicer on open, so each is checked as itself)
- `range`: `{from, to}` dates, `to` inclusive, either bound may be left open
- `relative`: `{range, duration, period}` as the Relative slicer shows it
- `contains`: the text an input slicer holds; `[]` means nothing typed

Bookmark navigators have no column, so they are listed in a custom property
instead (see `_navigator_contract`). Rules for other engines (pql-test's, ODCS
library metrics) are left alone. Every mistake is collected and reported at once, each named by its JSON path.
"""

from __future__ import annotations

import datetime
import decimal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ._navigator_contract import NAVIGATORS_PROPERTY, NavigatorExpectation, parse_navigators

ENGINE = "fab-test"
CHECKS = ("selected", "range", "relative", "contains")
SELECT_ALL = "all"  # `selected: all`: "Select all" ticked, nothing unticked
RESERVED_PREFIX = "page."  # the compiled page-existence rules use CONTRACT.page.<name>
_RELATIVE_RANGES = ("Last", "Next", "This")
_RELATIVE_PERIODS = ("Days", "Weeks", "Calendar Weeks", "Months", "Calendar Months", "Years", "Calendar Years")
_SEVERITIES = ("error", "warning")
_SCALARS = (str, int, float, bool, datetime.date, type(None))
_REPORT_PROPERTY = "fabTestReport"
_CALENDAR_PROPERTY = "fabTestCalendar"


class ContractError(Exception):
    """A contract that can't be read; the message lists every problem by JSON path."""


@dataclass(frozen=True)
class SlicerExpectation:
    rule_id: str
    page: str
    table: str
    column: str
    check: str
    expected: Any
    severity: str


@dataclass(frozen=True)
class SlicerContract:
    path: Path
    report_logical_id: str
    calendar: dict[str, Any] | None
    expectations: list[SlicerExpectation]
    navigators: list[NavigatorExpectation] = field(default_factory=list)


def dax_literal(value: Any) -> str:
    """The DAX literal Power BI Desktop writes for a value as the user sees it."""
    for kind, encode in _ENCODERS:  # order matters: bool is an int, datetime is a date
        if isinstance(value, kind):
            return encode(value)
    return "'" + str(value).replace("'", "''") + "'"


def _float_literal(value: float) -> str:
    return f"{int(value)}D" if value.is_integer() else f"{decimal.Decimal(repr(value)):f}D"


_ENCODERS: tuple = (
    (type(None), lambda _: "null"),
    (bool, lambda v: "true" if v else "false"),
    (int, lambda v: f"{v}L"),
    (float, _float_literal),
    (datetime.datetime, lambda v: f"datetime'{v.replace(microsecond=0).isoformat()}'"),
    (datetime.date, lambda v: f"datetime'{v.isoformat()}T00:00:00'"),
)


def load_contract(path: Path) -> SlicerContract:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"{path}: {exc}") from exc
    return parse_contract(document, Path(path))


def parse_contract(document: Any, path: Path) -> SlicerContract:
    """Validate an already-loaded contract document; ``path`` only names it in messages."""
    if not isinstance(document, dict):
        raise ContractError(f"{path}: an ODCS contract is a YAML mapping")
    errors: list[str] = []
    _check_envelope(document, errors)
    properties = _custom_properties(document)
    report = properties.get(_REPORT_PROPERTY)
    if not isinstance(report, str) or not report:
        errors.append(f"customProperties.{_REPORT_PROPERTY}: required, the report's .platform logicalId")
    expectations = list(_expectations(document, errors))
    navigators = parse_navigators(properties.get(NAVIGATORS_PROPERTY), _SEVERITIES, errors)
    _check_ids([*expectations, *navigators], errors)
    if errors:
        raise ContractError(f"{path} is not a valid slicer contract:\n" + "\n".join(f"  {e}" for e in errors))
    return SlicerContract(path, report, properties.get(_CALENDAR_PROPERTY), expectations, navigators)


def _check_envelope(document: dict, errors: list[str]) -> None:
    if not str(document.get("apiVersion", "")).startswith("v3."):
        errors.append(f"apiVersion: must be an ODCS v3 version such as v3.1.0, got {document.get('apiVersion')!r}")
    if document.get("kind") != "DataContract":
        errors.append(f"kind: must be DataContract, got {document.get('kind')!r}")
    errors.extend(f"{key}: required" for key in ("id", "version", "status") if not document.get(key))
    # `schema` is optional, as in ODCS: a navigator-only contract has none. _expectations reports a non-list.


def _custom_properties(element: dict) -> dict[str, Any]:
    items = element.get("customProperties")
    return {p.get("property"): p.get("value") for p in items if isinstance(p, dict)} if isinstance(items, list) else {}


def _mappings(items: Any, where: str, errors: list[str]):
    """(index, item) for each mapping in a list, reporting anything else by path."""
    if items is None:
        return
    if not isinstance(items, list):
        errors.append(f"{where}: must be a list")
        return
    for i, item in enumerate(items):
        if isinstance(item, dict):
            yield i, item
        else:
            errors.append(f"{where}[{i}]: must be a mapping, got {item!r}")


def _expectations(document: dict, errors: list[str]):
    for t, table in _mappings(document.get("schema"), "schema", errors):
        for c, column in _mappings(table.get("properties"), f"schema[{t}].properties", errors):
            where = f"schema[{t}].properties[{c}].quality"
            for q, rule in _mappings(column.get("quality"), where, errors):
                if str(rule.get("engine", "")).lower() != ENGINE:
                    continue
                if rule.get("type") != "custom":
                    errors.append(f"{where}[{q}].type: an engine: {ENGINE} rule must be type: custom, "
                                  f"got {rule.get('type')!r}")
                    continue
                expectation = _expectation(rule, table.get("name"), column.get("name"), f"{where}[{q}]", errors)
                if expectation:
                    yield expectation


def _check_ids(expectations: list[SlicerExpectation | NavigatorExpectation], errors: list[str]) -> None:
    seen: set[str] = set()
    for e in expectations:
        if e.rule_id in seen:
            errors.append(f"id {e.rule_id!r}: used by more than one rule; findings are named by it")
        if e.rule_id.startswith(RESERVED_PREFIX):
            errors.append(f"id {e.rule_id!r}: ids starting {RESERVED_PREFIX!r} are reserved for page checks")
        seen.add(e.rule_id)


def _expectation(rule: dict, table: str, column: str, where: str, errors: list[str]) -> SlicerExpectation | None:
    before = len(errors)
    if not isinstance(rule.get("id"), str) or not rule["id"]:
        errors.append(f"{where}.id: required; findings are named by it")
    severity = rule.get("severity", "error")
    if severity not in _SEVERITIES:
        errors.append(f"{where}.severity: must be one of {', '.join(_SEVERITIES)}, got {severity!r}")
    implementation = rule.get("implementation")
    if not isinstance(implementation, dict):
        errors.append(f"{where}.implementation: required, a mapping")
        return None
    check = _check_implementation(implementation, f"{where}.implementation", errors)
    if len(errors) > before or check is None:
        return None
    return SlicerExpectation(rule["id"], implementation["page"], table, column, check, implementation[check], severity)


def _check_implementation(implementation: dict, where: str, errors: list[str]) -> str | None:
    if not isinstance(implementation.get("page"), str) or not implementation["page"]:
        errors.append(f"{where}.page: required, the page's display name")
    errors.extend(f"{where}.{key}: unknown key; a slicer is named by page and bound field"
                  for key in implementation if key not in ("page", *CHECKS))
    checks = [key for key in CHECKS if key in implementation]
    if len(checks) != 1:
        errors.append(f"{where}: needs exactly one of {', '.join(CHECKS)}, got {checks or 'none'}")
        return None
    _VALIDATORS[checks[0]](implementation[checks[0]], f"{where}.{checks[0]}", errors)
    return checks[0]


def _validate_selected(value: Any, where: str, errors: list[str]) -> None:
    if value != SELECT_ALL and (not isinstance(value, list) or not all(isinstance(v, _SCALARS) for v in value)):
        errors.append(f"{where}: must be a list of plain values ([] means nothing selected), "
                      f"or {SELECT_ALL} for Select all")


def _validate_contains(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        errors.append(f"{where}: must be a list of text; [] means nothing typed")


def _validate_range(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or not value.keys() & {"from", "to"} or value.keys() - {"from", "to"}:
        errors.append(f"{where}: must have from, to or both")
        return
    bad = [key for key, bound in value.items() if not isinstance(bound, datetime.date)]
    errors.extend(f"{where}.{key}: must be a date such as 2026-10-28, got {value[key]!r}" for key in bad)
    if not bad and "from" in value and "to" in value and value["from"] > value["to"]:
        errors.append(f"{where}: from {value['from']} is after to {value['to']}")


def _validate_relative(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{where}: must have range, duration and period")
        return
    if value.get("range") not in _RELATIVE_RANGES:
        errors.append(f"{where}.range: must be one of {', '.join(_RELATIVE_RANGES)}, got {value.get('range')!r}")
    duration = value.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
        errors.append(f"{where}.duration: must be a whole number of at least 1, got {duration!r}")
    if value.get("period") not in _RELATIVE_PERIODS:
        errors.append(f"{where}.period: must be one of {', '.join(_RELATIVE_PERIODS)}, got {value.get('period')!r}")


_VALIDATORS = {
    "selected": _validate_selected,
    "range": _validate_range,
    "relative": _validate_relative,
    "contains": _validate_contains,
}
