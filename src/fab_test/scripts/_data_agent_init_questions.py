"""Suggest questions from the selected data in a Data Agent definition."""

import json
from pathlib import Path
from typing import Any


class InitInputError(ValueError):
    """A definition or answer that cannot safely produce a suite."""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise InitInputError(f"Cannot read Data Agent definition {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InitInputError(f"{path} must contain a JSON object.")
    return value


DECLINE_SUGGESTION = "What is the current balance of my private bank account?"


def _selected(element: Any, kind: str) -> bool:
    return (isinstance(element, dict) and element.get("is_selected") is True
            and str(element.get("type", "")).endswith(f".{kind}") and bool(element.get("display_name")))


def _table_suggestions(table: dict[str, Any]) -> tuple[list[str], list[str]]:
    """A measure is a question someone would ask; a row count only for a table that has columns."""
    children = table.get("children") or []
    measures = [f"What is the {child['display_name']}?" for child in children if _selected(child, "measure")]
    has_columns = any(_selected(child, "column") for child in children) or not children
    counts = [f"How many rows are in the {table['display_name']} table?"] if has_columns else []
    return measures, counts


def build_suggestions(item: Path) -> list[str]:
    """Questions to offer from the selected measures and tables, then one the agent should decline.

    Suggestions only: the caller writes or picks each question and gives every expected answer.
    """
    draft = item / "Files" / "Config" / "draft"
    sources = sorted(draft.rglob("datasource.json"))
    if not sources:
        raise InitInputError(f"{draft} contains no data source definitions.")
    measures: list[str] = []
    counts: list[str] = []
    for path in sources:
        elements = _read(path).get("elements")
        if not isinstance(elements, list):
            raise InitInputError(f"{path} needs an elements list.")
        for table in (element for element in elements if _selected(element, "table")):
            table_measures, table_counts = _table_suggestions(table)
            measures += table_measures
            counts += table_counts
    if not measures and not counts:
        raise InitInputError(f"{draft} selects no tables; select a source table in the agent before writing tests.")
    return list(dict.fromkeys([*measures, *counts, DECLINE_SUGGESTION]))
