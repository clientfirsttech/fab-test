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
from ._data_agent_init_questions import DECLINE_SUGGESTION, InitInputError, build_suggestions
from ._data_agent_init_tests import MATCH_KEYS, ask_tests, tests_from_answers, tests_from_specs
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


_ANSWERS_EXAMPLE = {"tests": [
    {"query": "How many characters are in the data?", "expect": "16,376", "match": "n",
     "follow_ups": [{"query": "Is that more than 10,000?", "expect": "yes", "match": "s"}]},
    {"query": DECLINE_SUGGESTION, "match": "r"},
]}


def _new_tests(args: argparse.Namespace, suggestions: list[str]) -> list[dict[str, Any]]:
    """The caller's questions: from --answers, or asked one at a time when a person is there."""
    if args.answers:
        try:
            document = json.loads(Path(args.answers).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise InitInputError(f"Cannot read --answers {args.answers}: {exc}") from exc
        return tests_from_answers(document)
    if args.output_format == "json" or os.getenv("CI") or not can_ask():
        raise InitInputError("Writing tests needs your questions and expected answers, and nobody is here to "
                             "ask. Run --questions to see suggestions and the file shape, then pass --answers FILE.")
    try:
        return tests_from_specs(ask_tests(suggestions))
    except EOFError as exc:
        raise InitInputError("Input ended before the questions did; nothing was written. "
                             "Pass --answers FILE instead.") from exc


def _merge(document: dict, new_tests: list[dict], force: bool) -> dict[str, list[str]]:
    counts: dict[str, list[str]] = {key: [] for key in ("added", "replaced", "kept", "unchanged")}
    tests = document["tests"]
    for test in new_tests:
        test_id = test["metadata"]["id"]
        index = next((i for i, old in enumerate(tests) if old.get("metadata", {}).get("id") == test_id), None)
        if index is not None and not force:
            counts["kept"].append(test_id)
            continue
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


def _questions_text(payload: dict) -> str:
    suggestions = "".join(f"  {number}. {text}\n" for number, text in enumerate(payload["suggestions"], 1))
    keys = "  ".join(f"{key} {name}" for key, name in payload["matches"].items())
    return (f"Suggested questions from the agent's data (you write the expected answers):\n{suggestions}"
            f"Match keys: {keys}\n"
            "Run without --questions to be asked, or pass --answers FILE shaped like:\n"
            f"{json.dumps(payload['answers_example'], indent=2)}")


def _text(payload: dict) -> str:
    if "suggestions" in payload:
        return _questions_text(payload)
    line = _line(payload)
    if "document" in payload:
        return f"{line}\n{yaml.safe_dump(payload['document'], sort_keys=False, allow_unicode=True)}"
    return f"{line}\nNext: {payload['next']}" if payload["next"] else line


def _line(payload: dict) -> str:
    if "document" in payload:  # --dry-run: say what would happen, never "written"
        would = " ".join(f"{verb}={len(payload[key])}" for verb, key in
                         (("add", "added"), ("replace", "replaced"), ("keep", "kept"), ("unchanged", "unchanged")))
        return f"tests dry run, nothing written: would {would} {payload['suite']}"
    counts = " ".join(f"{key}={len(payload[key])}" for key in ("added", "replaced", "kept", "unchanged"))
    return f"tests {'written' if payload['added'] or payload['replaced'] else 'unchanged'} {counts} {payload['suite']}"


def init_main(args: argparse.Namespace) -> int:
    """Write the caller's questions and expected answers into the item's paired suite."""
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
    suggestions = build_suggestions(item)
    if args.questions:
        print_payload(args, {"item": str(item), "suite": str(suite), "suggestions": suggestions,
                             "matches": MATCH_KEYS, "answers_example": _ANSWERS_EXAMPLE}, _text, asked_for=True)
        return 0
    counts = _merge(document, _new_tests(args, suggestions), args.force)
    effective_config(document, "https://example.invalid/data-agent")
    content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if not args.dry_run and (counts["added"] or counts["replaced"]):  # no questions: no file, not an empty one
        _write(suite, content)
    payload = {"item": str(item), "suite": str(suite), **counts,
               "next": None if args.dry_run else next_command(args, "fab-test data-agent tests lint")}
    if args.dry_run:
        payload["document"] = document
    print_payload(args, payload, _text, asked_for=args.dry_run, as_line=_line)
    return 0
