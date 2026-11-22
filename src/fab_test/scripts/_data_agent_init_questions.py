"""Build answer requests from the selected data in a Data Agent definition."""

import json
import re
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


def _id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _question(test_id: str, query: str, **variables: Any) -> dict[str, Any]:
    return {"id": test_id, "prompt": f"Expected answer for: {query}", "query": query,
            "suggested": None, "needs_human": True, "variables": variables}


def build_questions(item: Path) -> list[dict[str, Any]]:
    """Suggest questions for selected tables, a refusal, and a conversation."""
    draft = item / "Files" / "Config" / "draft"
    stage = _read(draft / "stage_config.json")
    sources = sorted(draft.rglob("datasource.json"))
    if not sources:
        raise InitInputError(f"{draft} contains no data source definitions.")
    questions = []
    for path in sources:
        source = _read(path)
        source_id = source.get("artifactId")
        elements = source.get("elements")
        if not isinstance(source_id, str) or not source_id or not isinstance(elements, list):
            raise InitInputError(f"{path} needs an artifactId and an elements list.")
        for element in elements:
            if not isinstance(element, dict):
                raise InitInputError(f"{path}: each data source element must be an object.")
            if element.get("is_selected") is not True or not str(element.get("type", "")).endswith(".table"):
                continue
            table, table_id = element.get("display_name"), element.get("id")
            if not isinstance(table, str) or not table or not isinstance(table_id, str) or not table_id:
                raise InitInputError(f"{path}: selected tables need display_name and id.")
            question = _question(f"table-{_id(source_id)}-{_id(table_id)}", f"How many rows are in the {table} table?")
            if stage.get("aiInstructions") or source.get("dataSourceInstructions"):
                question["prompt"] += " Review the agent and source instructions before answering."
            questions.append(question)
    if not questions:
        raise InitInputError(f"{draft} has no selected tables; select a source table before creating a suite.")
    first = questions[0]["query"]
    questions.extend([
        _question("out-of-scope", "What is the current balance of my private bank account?"),
        _question("conversation-first", first, conversation="starter-conversation", reset=True),
        _question("conversation-follow-up", "Is that number greater than 10,000? Answer yes or no.",
                  conversation="starter-conversation"),
    ])
    ids = [question["id"] for question in questions]
    if len(ids) != len(set(ids)) or any(not item_id for item_id in ids):
        raise InitInputError("Selected data source identities produce duplicate or empty question IDs.")
    return questions
