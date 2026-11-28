"""Suggest questions from the selected data in a Data Agent definition."""

import json
from pathlib import Path
from typing import Any, NamedTuple


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


def _selected(element: Any, kind: str, selected: bool = True) -> bool:
    return (isinstance(element, dict) and element.get("is_selected") is selected
            and str(element.get("type", "")).endswith(f".{kind}") and bool(element.get("display_name")))


# A figure is a question someone asks an agent; a text or date measure is usually a label or a filter helper.
_NOT_A_FIGURE = frozenset({"string", "text", "datetime", "date", "time", "boolean"})


def _figure(measure: dict[str, Any]) -> bool:
    return str(measure.get("data_type") or "").lower() not in _NOT_A_FIGURE


def _table_suggestions(table: dict[str, Any]) -> tuple[list[str], list[str]]:
    """A figure measure is a question someone would ask; a row count only for a table that has columns."""
    children = table.get("children") or []
    measures = [f"What is the {child['display_name']}?" for child in children
                if _selected(child, "measure") and _figure(child)]
    has_columns = any(_selected(child, "column") for child in children) or not children
    counts = [f"How many rows are in the {table['display_name']} table?"] if has_columns else []
    return measures, counts


class Suggestions(NamedTuple):
    """What init offers: questions to ask, questions the agent should decline, and the agent's own instructions."""

    questions: list[str]
    decline: list[str]
    instructions: list[str]

    def all(self) -> list[str]:
        """Every suggestion in the order `?` numbers them."""
        return [*self.questions, *self.decline]


def _instructions(draft: Path, sources: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    stage = draft / "stage_config.json"
    agent = _read(stage).get("aiInstructions") if stage.is_file() else None
    found = [str(agent).strip()] if isinstance(agent, str) and agent.strip() else []
    for _path, source in sources:
        text = source.get("dataSourceInstructions")
        if isinstance(text, str) and text.strip():
            found.append(f"{source.get('displayName') or 'source'}: {text.strip()}")
    return found


def read_suggestions(item: Path) -> Suggestions:
    """Suggestions from the definition (decision 14), never an answer.

    Selected figure measures and tables become questions. A table the source has but the agent leaves
    unselected becomes a question it should decline, then the generic out-of-scope one. The agent's
    instructions are shown so the person can write questions against them.
    """
    draft = item / "Files" / "Config" / "draft"
    paths = sorted(draft.rglob("datasource.json"))
    if not paths:
        raise InitInputError(f"{draft} contains no data source definitions.")
    sources = [(path, _read(path)) for path in paths]
    measures: list[str] = []
    counts: list[str] = []
    decline: list[str] = []
    for path, source in sources:
        elements = source.get("elements")
        if not isinstance(elements, list):
            raise InitInputError(f"{path} needs an elements list.")
        for table in (element for element in elements if _selected(element, "table")):
            table_measures, table_counts = _table_suggestions(table)
            measures += table_measures
            counts += table_counts
        decline += [f"How many rows are in the {element['display_name']} table?"
                    for element in elements if _selected(element, "table", selected=False)]
    if not measures and not counts:
        raise InitInputError(f"{draft} selects no tables; select a source table in the agent before writing tests.")
    questions = list(dict.fromkeys([*measures, *counts]))
    declines = [text for text in dict.fromkeys([*decline, DECLINE_SUGGESTION]) if text not in questions]
    return Suggestions(questions, declines, _instructions(draft, sources))


def build_suggestions(item: Path) -> list[str]:
    """Every suggestion, in the order `?` numbers them."""
    return read_suggestions(item).all()
