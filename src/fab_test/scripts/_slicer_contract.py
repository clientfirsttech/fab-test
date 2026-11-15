"""Read a slicer contract (PBIR Slicer Default State epic, Contract Format).

A contract is an ODCS v3 document. Its `type: custom`, `engine: fab-test`
quality rules sit on the column a slicer is bound to (schema object = table,
property = column) and state, under `implementation`, the page and what the
slicer opens with, as one of:

- `selected`: values or field-parameter display names; `[]` means no selection
- `range`: `{from, to}` dates, `to` inclusive, either bound may be left open
- `relative`: `{range, duration, period}` as the Relative slicer shows it
- `contains`: the text an input slicer holds

Rules for other engines (pql-test's, ODCS library metrics) are left alone.
Every mistake is collected and reported at once, each named by its JSON path.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ENGINE = "fab-test"
CHECKS = ("selected", "range", "relative", "contains")
_RELATIVE_RANGES = ("Last", "Next", "This")
_RELATIVE_PERIODS = ("Days", "Weeks", "Calendar Weeks", "Months", "Calendar Months", "Years", "Calendar Years")
_SEVERITIES = ("error", "warning")
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


def dax_literal(value: Any) -> str:
    """The DAX literal Power BI Desktop writes for a value as the user sees it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value}L"
    if isinstance(value, float):
        return f"{value}D"
    if isinstance(value, datetime.datetime):
        return f"datetime'{value.replace(microsecond=0).isoformat()}'"
    if isinstance(value, datetime.date):
        return f"datetime'{value.isoformat()}T00:00:00'"
    return "'" + str(value).replace("'", "''") + "'"


def load_contract(path: Path) -> SlicerContract:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"{path}: {exc}") from exc
    errors: list[str] = []
    if not isinstance(document, dict):
        raise ContractError(f"{path}: an ODCS contract is a YAML mapping")
    _check_envelope(document, errors)
    properties = _custom_properties(document)
    report = properties.get(_REPORT_PROPERTY)
    if not isinstance(report, str) or not report:
        errors.append(f"customProperties.{_REPORT_PROPERTY}: required, the report's .platform logicalId")
    expectations = list(_expectations(document, errors))
    if errors:
        raise ContractError(f"{path} is not a valid slicer contract:\n" + "\n".join(f"  {e}" for e in errors))
    return SlicerContract(Path(path), report, properties.get(_CALENDAR_PROPERTY), expectations)


def _check_envelope(document: dict, errors: list[str]) -> None:
    if not str(document.get("apiVersion", "")).startswith("v3."):
        errors.append(f"apiVersion: must be an ODCS v3 version such as v3.1.0, got {document.get('apiVersion')!r}")
    if document.get("kind") != "DataContract":
        errors.append(f"kind: must be DataContract, got {document.get('kind')!r}")
    errors.extend(f"{key}: required" for key in ("id", "version", "status") if not document.get(key))
    if not isinstance(document.get("schema"), list):
        errors.append("schema: required, a list of tables")


def _custom_properties(element: dict) -> dict[str, Any]:
    return {p.get("property"): p.get("value") for p in element.get("customProperties") or [] if isinstance(p, dict)}


def _expectations(document: dict, errors: list[str]):
    for t, table in enumerate(document.get("schema") or []):
        for c, column in enumerate(table.get("properties") or []):
            for q, rule in enumerate(column.get("quality") or []):
                if rule.get("type") == "custom" and str(rule.get("engine", "")).lower() == ENGINE:
                    where = f"schema[{t}].properties[{c}].quality[{q}]"
                    expectation = _expectation(rule, table.get("name"), column.get("name"), where, errors)
                    if expectation:
                        yield expectation


def _expectation(rule: dict, table: str, column: str, where: str, errors: list[str]) -> SlicerExpectation | None:
    before = len(errors)
    if not rule.get("id"):
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
    if not isinstance(value, list):
        errors.append(f"{where}: must be a list of values; [] means no selection")


def _validate_contains(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        errors.append(f"{where}: must be a non-empty list of text")


def _validate_range(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or not value.keys() & {"from", "to"} or value.keys() - {"from", "to"}:
        errors.append(f"{where}: must have from, to or both")
        return
    errors.extend(f"{where}.{key}: must be a date such as 2026-10-28, got {bound!r}"
                  for key, bound in value.items() if not isinstance(bound, datetime.date))


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
