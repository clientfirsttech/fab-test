"""Create or extend a paired Data Agent suite with human-confirmed expectations."""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ._authoring_output import can_ask, next_command, print_payload
from ._data_agent_init_questions import DECLINE_SUGGESTION, InitInputError, Suggestions, read_suggestions
from ._data_agent_init_tests import (
    MATCH_KEYS,
    ask_tests,
    input_prompt,
    numbered,
    question_key,
    specs_from_answers,
    tests_from_specs,
)
from ._data_agent_suite import SuiteError, effective_config, item_identity, load_suite, named_item, suite_index
from ._scan import ScanError, find_artifact_dirs
from ._tests_dir import flow_dir, search_roots


def _has_comments(content: str) -> bool:
    """A `#` that starts a YAML comment: at a line start or after whitespace, outside every scalar.

    A question like "What is the #1 eye color?" is quoted, so init can extend its own output.
    """
    spans = [(token.start_mark.index, token.end_mark.index)
             for token in yaml.scan(content, Loader=yaml.SafeLoader) if isinstance(token, yaml.ScalarToken)]
    return any(not any(start <= found.start() < end for start, end in spans)
               for found in re.finditer(r"(?:^|(?<=\s))#", content, re.MULTILINE))


def _existing(path: Path, logical_id: str, force: bool) -> dict[str, Any]:
    if not path.exists():
        return {"fabTestDataAgent": logical_id, "prompts": ["{{query}}"], "tests": []}
    try:
        content = path.read_text(encoding="utf-8-sig")
        document = load_suite(path)
    except (OSError, UnicodeError, SuiteError) as exc:
        raise InitInputError(f"Cannot read existing suite {path}; check that it is UTF-8 YAML.") from exc
    if not force and _has_comments(content):
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


def _existing_questions(document: dict) -> dict[str, dict[str, str]]:
    """The suite's questions by `question_key`: the id and check of each, to show when one is typed again."""
    existing = {}
    for test in document["tests"]:
        query, test_id = (test.get("vars") or {}).get("query"), (test.get("metadata") or {}).get("id")
        if isinstance(query, str) and isinstance(test_id, str):
            check = next(iter(test.get("assert") or []), {})
            summary = f"{check.get('type', 'no check')} {str(check.get('value', ''))[:60]}".strip()
            existing[question_key(query)] = {"id": test_id, "summary": summary, "query": query}
    return existing


def _announce(suite: Path, existing: dict[str, dict[str, str]]) -> None:
    """Where the questions go, and what is already there, before the first one is asked."""
    if not existing:
        print(f"Writing a new suite: {suite}", file=sys.stderr)
        return
    listed = "".join(f"  {known['id']}: {known['query']}\n" for known in existing.values())
    print(f"{suite} has {_count(len(existing))}:\n{listed.rstrip()}", file=sys.stderr)


def _count(number: int, noun: str = "test") -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _add_or_replace(existing: dict[str, dict[str, str]]) -> bool:
    """True to start the suite over. Enter adds, the reason init was run; r is one key away."""
    prompt = f"[a]dd to it (Enter) or [r]eplace all {_count(len(existing))}? "
    while True:
        typed = input_prompt(prompt).strip().lower()
        if typed in {"", "a", "add"}:
            print("Type one of them again to keep or replace it. For a separate suite, rerun with --tests FILE.",
                  file=sys.stderr)
            return False
        if typed in {"r", "replace"}:
            print(f"  → starting over: the {_count(len(existing))} go only once you've written new ones",
                  file=sys.stderr)
            return True
        print("  a adds, r replaces", file=sys.stderr)


def _new_tests(args: argparse.Namespace, suggestions: Suggestions, suite: Path, document: dict
               ) -> list[dict[str, Any]]:
    """The caller's questions: from --answers, or asked one at a time when a person is there.

    A question the suite already has takes that test's id, so the merge keeps it, or replaces it
    when the person chose r (or the answers file says "replace": true), never adds a near-duplicate.
    """
    existing = _existing_questions(document)
    if args.answers:
        try:
            answers = json.loads(Path(args.answers).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise InitInputError(f"Cannot read --answers {args.answers}: {exc}") from exc
        specs = specs_from_answers(answers)
        args.replace_all = isinstance(answers, dict) and answers.get("replace_all") is True
    elif args.output_format == "json" or os.getenv("CI") or not can_ask():
        target = args.target or args.artifact
        raise InitInputError("Writing tests needs your questions and expected answers, and nobody is here to ask. "
                             f"Run `fab-test data-agent tests init {target} --questions` to see suggestions and the "
                             "file shape, then pass --answers FILE.")
    else:
        _announce(suite, existing)
        try:
            args.replace_all = bool(existing) and _add_or_replace(existing)
            specs = ask_tests(suggestions.all(), existing={} if args.replace_all else existing,
                              declines=set(suggestions.decline))
        except EOFError as exc:
            raise InitInputError("Input ended before the questions did; nothing was written. "
                                 "Pass --answers FILE instead.") from exc
        args.asked_in_person = True  # typed work: a dry run offers to keep it rather than discard it
    for spec in specs if not args.replace_all else []:  # starting over: nothing to match against
        known = existing.get(question_key(spec["query"]))
        if known and "id" not in spec:
            spec["id"] = known["id"]
    args.replace_ids = {spec["id"] for spec in specs if spec.get("replace")}
    taken = set() if args.replace_all else {(test.get("metadata") or {}).get("id") for test in document["tests"]}
    return tests_from_specs(specs, taken - {None})


def _merge(document: dict, new_tests: list[dict], force: bool, replace: set[str] | frozenset = frozenset()
           ) -> dict[str, list[str]]:
    counts: dict[str, list[str]] = {key: [] for key in ("added", "replaced", "kept", "unchanged")}
    tests = document["tests"]
    for test in new_tests:
        test_id = test["metadata"]["id"]
        index = next((i for i, old in enumerate(tests) if old.get("metadata", {}).get("id") == test_id), None)
        if index is None:
            tests.append(test)
            counts["added"].append(test_id)
        elif tests[index] == test:
            counts["unchanged"].append(test_id)
        elif not force and test_id not in replace:
            counts["kept"].append(test_id)  # a different answer, not applied
        else:
            tests[index] = test
            counts["replaced"].append(test_id)
    return counts


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)  # fab-tests/data-agent/ on the first suite
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
    suggestions = numbered(payload["suggestions"], set(payload["decline"]))
    keys = "  ".join(f"{key} {name}" for key, name in payload["matches"].items())
    told = "".join(f"  {text}\n" for text in payload["instructions"])
    instructions = f"The agent's instructions, to write questions against:\n{told}" if told else ""
    return (f"{instructions}Suggested questions from the agent's data (you write the expected answers):\n"
            f"{suggestions}"
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
                         (("add", "added"), ("replace", "replaced"), ("keep", "kept"), ("unchanged", "unchanged"),
                          ("remove", "removed")))
        return f"tests dry run, nothing written: would {would} {payload['suite']}"
    counts = " ".join(f"{key}={len(payload[key])}" for key in ("added", "replaced", "kept", "unchanged", "removed"))
    return f"tests {'written' if payload['added'] or payload['replaced'] else 'unchanged'} {counts} {payload['suite']}"


def init_main(args: argparse.Namespace) -> int:
    """Write the caller's questions and expected answers into the item's paired suite."""
    try:
        return _init(args)
    except (InitInputError, SuiteError, ScanError, OSError, ValueError) as exc:
        print(f"  ✗ fab-test data-agent tests init: {exc}", file=sys.stderr)
        return 2


def _suite_path(args: argparse.Namespace, item: Path, logical_id: str) -> Path:
    """The suite already pairing with the item, wherever it lives; else a new one in fab-tests/data-agent/."""
    existing = suite_index(search_roots(args, item)).get(logical_id)
    if existing is not None:
        return existing
    home = flow_dir(args, "data-agent", item)
    return (home or item.parent) / f"{item.name}.promptfoo.yaml"


def _init(args: argparse.Namespace) -> int:
    target = args.target or args.artifact
    items = find_artifact_dirs(Path(args.artifact_dir), [".DataAgent"])
    if not target:
        found = ", ".join(item.name.removesuffix(".DataAgent") for item in items) or f"none under {args.artifact_dir}"
        raise InitInputError(f"Name the Data Agent item as TARGET or --artifact (found: {found}).")
    item = named_item(items, target)
    logical_id, _ = item_identity(item)
    suite = Path(args.tests) if args.tests else _suite_path(args, item, logical_id)
    document = _existing(suite, logical_id, args.force)
    suggestions = read_suggestions(item)
    if args.questions:
        print_payload(args, {"item": str(item), "suite": str(suite), "suggestions": suggestions.all(),
                             "decline": suggestions.decline, "instructions": suggestions.instructions,
                             "matches": MATCH_KEYS, "answers_example": _ANSWERS_EXAMPLE}, _text, asked_for=True)
        return 0
    new_tests = _new_tests(args, suggestions, suite, document)
    removed = [test.get("metadata", {}).get("id") for test in document["tests"]]
    if getattr(args, "replace_all", False) and new_tests:  # no new questions: nothing goes
        document["tests"] = []
    else:
        removed = []
    counts = _merge(document, new_tests, args.force, getattr(args, "replace_ids", set()))
    counts["removed"] = removed
    effective_config(document, "https://example.invalid/data-agent")
    content = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if not args.dry_run and (counts["added"] or counts["replaced"]):  # no questions: no file, not an empty one
        _write(suite, content)
    payload = {"item": str(item), "suite": str(suite), **counts,
               "next": None if args.dry_run else next_command(args, "fab-test data-agent tests lint")}
    if args.dry_run:
        payload["document"] = document
    print_payload(args, payload, _text, as_line=_line)  # -q is one line, even for a dry run
    if args.dry_run and getattr(args, "asked_in_person", False) and _keep(counts, suite):
        _write(suite, content)
        written = {key: value for key, value in payload.items() if key != "document"}
        print_payload(args, {**written, "next": next_command(args, "fab-test data-agent tests lint")},
                      _text, as_line=_line)
    return 0


def _keep(counts: dict[str, list[str]], suite: Path) -> bool:
    """After a console dry run: write what the person typed, or let it go (Enter = no, as --dry-run asked)."""
    changed = len(counts["added"]) + len(counts["replaced"])
    if not changed:
        return False
    question = (f"Replace the {_count(len(counts['removed']))} in {suite} with {_count(changed, 'new one')}? [y/N] "
                if counts["removed"] else f"Write {_count(changed, 'new test')} to {suite}? [y/N] ")
    try:
        reply = input_prompt(question)
    except EOFError:
        return False
    return reply.strip().lower() in {"y", "yes"}
