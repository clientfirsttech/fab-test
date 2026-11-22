"""Create or extend a paired Data Agent suite with human-confirmed expectations."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ._authoring_output import can_ask, next_command, print_payload
from ._data_agent_init_questions import InitInputError, build_questions
from ._data_agent_lint_command import _named_item
from ._data_agent_suite import SuiteError, effective_config, item_identity, load_suite, suite_index
from ._scan import ScanError, find_artifact_dirs


def _existing(path: Path, logical_id: str, force: bool) -> dict[str, Any]:
    if not path.exists():
        return {"fabTestDataAgent": logical_id, "prompts": ["{{query}}"], "tests": []}
    try:
        content = path.read_text(encoding="utf-8-sig")
        document = load_suite(path)
    except (OSError, UnicodeError, SuiteError) as exc:
        raise InitInputError(f"Cannot read existing suite {path}; check that it is UTF-8 YAML.") from exc
    if "#" in content and not force:
        raise InitInputError(f"{path} contains comments; rewriting would remove them. Pass --force to continue.")
    if document.get("fabTestDataAgent") != logical_id:
        raise InitInputError(f"{path} does not pair with this item's .platform logicalId.")
    tests = document.get("tests")
    if not isinstance(tests, list) or any(not isinstance(test, dict) for test in tests):
        raise InitInputError(f"{path}: tests must be a list of inline mappings.")
    metadata = [test["metadata"] for test in tests if "metadata" in test]
    if any(not isinstance(value, dict) for value in metadata):
        raise InitInputError(f"{path}: test metadata must be a mapping.")
    ids = [value["id"] for value in metadata if "id" in value]
    if any(not isinstance(value, str) or not value.strip() for value in ids):
        raise InitInputError(f"{path}: test metadata.id must be a non-empty string.")
    if len(ids) != len(set(ids)):
        raise InitInputError(f"{path}: duplicate test ids must be fixed before init.")
    return document


def _answers(args: argparse.Namespace, questions: list[dict], existing_ids: set[str]) -> dict[str, str]:
    if args.answers:
        try:
            answers = json.loads(Path(args.answers).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise InitInputError(f"Cannot read --answers {args.answers}: {exc}") from exc
        if not isinstance(answers, dict):
            raise InitInputError("--answers must contain a JSON object of question id to expected answer.")
    else:
        answers = {}
    known = {question["id"] for question in questions}
    unknown = set(answers) - known
    if unknown:
        raise InitInputError(f"--answers has unknown question IDs: {', '.join(sorted(unknown))}.")
    needed = [q for q in questions if q["id"] not in existing_ids or args.force]
    missing = [q for q in needed if q["id"] not in answers]
    if missing and (args.output_format == "json" or os.getenv("CI") or not can_ask()):
        raise InitInputError("Expected answers need a person. Run --questions --format json, then pass --answers FILE.")
    for question in missing:
        print(f"{question['prompt']}\n  Expected answer: ", end="", file=sys.stderr)
        try:
            answers[question["id"]] = input().strip()
        except EOFError as exc:
            raise InitInputError("No answer supplied. Run --questions and pass --answers FILE.") from exc
    for key, value in answers.items():
        if not isinstance(value, str) or not value.strip():
            raise InitInputError(f"--answers {key}: provide a non-empty expected answer.")
    return answers


def _merge(document: dict, questions: list[dict], answers: dict[str, str], force: bool) -> dict[str, list[str]]:
    counts: dict[str, list[str]] = {key: [] for key in ("added", "replaced", "kept", "unchanged")}
    tests = document["tests"]
    for question in questions:
        test_id = question["id"]
        index = next((i for i, test in enumerate(tests) if test.get("metadata", {}).get("id") == test_id), None)
        if index is not None and not force:
            counts["kept"].append(test_id)
            continue
        test = {"description": question["query"], "metadata": {"id": test_id},
                "vars": {"query": question["query"], **question["variables"]},
                "assert": [{"type": "contains", "value": answers[test_id]}]}
        if index is None:
            tests.append(test)
            counts["added"].append(test_id)
        elif tests[index] == test:
            counts["unchanged"].append(test_id)
        else:
            tests[index] = test
            counts["replaced"].append(test_id)
    return counts


def _write(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _text(payload: dict) -> str:
    if "questions" in payload:
        return "\n".join(f"{q['id']}: {q['prompt']} [suggested: none; needs human]" for q in payload["questions"])
    line = _line(payload)
    if "document" in payload:
        return f"{line}\n{yaml.safe_dump(payload['document'], sort_keys=False, allow_unicode=True)}"
    return f"{line}\nNext: {payload['next']}" if payload["next"] else line


def _line(payload: dict) -> str:
    counts = " ".join(f"{key}={len(payload[key])}" for key in ("added", "replaced", "kept", "unchanged"))
    return f"tests {'written' if payload['added'] or payload['replaced'] else 'unchanged'} {counts} {payload['suite']}"


def init_main(args: argparse.Namespace) -> int:
    """Initialize a suite only after every required expected answer is supplied."""
    try:
        return _init(args)
    except (InitInputError, SuiteError, ScanError, OSError, ValueError) as exc:
        print(f"  ✗ fab-test data-agent tests init: {exc}", file=sys.stderr)
        return 2


def _init(args: argparse.Namespace) -> int:
    target = args.target or args.artifact
    if not target:
        raise InitInputError("Name the Data Agent item as TARGET or --artifact.")
    item = _named_item(find_artifact_dirs(Path(args.artifact_dir), [".DataAgent"]), target)
    logical_id, _ = item_identity(item)
    suite = (Path(args.tests) if args.tests else
             suite_index(Path(args.artifact_dir)).get(logical_id, item.parent / f"{item.name}.promptfoo.yaml"))
    document = _existing(suite, logical_id, args.force)
    questions = build_questions(item)
    if args.questions:
        print_payload(args, {"item": str(item), "suite": str(suite), "questions": questions}, _text, asked_for=True)
        return 0
    existing_ids = {test["metadata"]["id"] for test in document["tests"]
                    if isinstance(test.get("metadata"), dict) and isinstance(test["metadata"].get("id"), str)}
    answers = _answers(args, questions, existing_ids)
    counts = _merge(document, questions, answers, args.force)
    effective_config(document, "https://example.invalid/data-agent")
    content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if not args.dry_run and (not suite.exists() or counts["added"] or counts["replaced"]):
        _write(suite, content)
    payload = {"item": str(item), "suite": str(suite), **counts,
               "next": None if args.dry_run else next_command(args, "fab-test data-agent tests lint")}
    if args.dry_run:
        payload["document"] = document
    print_payload(args, payload, _text, asked_for=args.dry_run, as_line=_line)
    return 0
