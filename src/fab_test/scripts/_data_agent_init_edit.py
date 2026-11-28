"""`tests init` [e]dit: change a test's answer or delete it, picked by number.

A changed answer rewrites only the test's check, so its id, description and conversation stay.
Deleting a turn deletes the turns after it in the same conversation: they follow on from it.
"""

from __future__ import annotations

from typing import Any, TextIO

from ._data_agent_init_tests import Ask, InitInputError, _ask_one, assertion, parse_match


def _id(test: dict[str, Any]) -> str:
    return str((test.get("metadata") or {}).get("id", ""))


def _conversation(test: dict[str, Any]) -> str | None:
    return (test.get("vars") or {}).get("conversation")


def later_turns(tests: list[dict[str, Any]], test_id: str) -> list[str]:
    """The test and every turn after it in its conversation; a lone test is just itself."""
    index = next(i for i, test in enumerate(tests) if _id(test) == test_id)
    conversation = _conversation(tests[index])
    if conversation is None:
        return [test_id]
    return [test_id, *(_id(test) for test in tests[index + 1:] if _conversation(test) == conversation)]


def removal(tests: list[dict[str, Any]], remove: Any) -> set[str]:
    """``"remove"`` from --answers: ids the suite has, each with its later turns."""
    if not isinstance(remove, list) or any(not isinstance(value, str) for value in remove):
        raise InitInputError('--answers "remove" must be a list of test ids, e.g. ["tell-me-a-joke"]')
    known = {_id(test) for test in tests}
    if missing := [value for value in remove if value not in known]:
        raise InitInputError(f"--answers remove names {', '.join(missing)}, which the suite doesn't have; "
                             f"its ids: {', '.join(sorted(known))}")
    return {turn for value in remove for turn in later_turns(tests, value)}


def _listing(tests: list[dict[str, Any]]) -> str:
    lines = []
    for number, test in enumerate(tests, 1):
        follow_up = _conversation(test) and not (test.get("vars") or {}).get("reset")
        query = (test.get("vars") or {}).get("query", "")
        lines.append(f"  {number}. {'  ' if follow_up else ''}{_id(test)}: {query}\n")
    return "".join(lines)


def _changed(test: dict[str, Any], ask: Ask, err: TextIO) -> dict[str, Any]:
    spec = _ask_one(str((test.get("vars") or {}).get("query", "")), "    ", ask, err)
    return {**test, "assert": [assertion(parse_match(spec["match"]), spec["expect"])]}


def _delete(tests: list[dict[str, Any]], test_id: str, err: TextIO) -> set[str]:
    turns = later_turns(tests, test_id)
    after = len(turns) - 1
    tail = f" and its {after} later turn{'s' if after != 1 else ''} (they follow on from it)" if after else ""
    err.write(f"    → deletes {test_id}{tail}\n")
    return set(turns)


def edit_tests(tests: list[dict[str, Any]], ask: Ask, err: TextIO) -> tuple[list[dict[str, Any]], set[str]]:
    """Pick tests by number until Enter: [c]hange the answer (Enter) or [d]elete. Returns (changed, removed ids)."""
    err.write(_listing(tests))
    changed: dict[str, dict[str, Any]] = {}
    removed: set[str] = set()
    while typed := ask("Test to edit (number, Enter when done): ").strip():
        if not typed.isdigit() or not 1 <= int(typed) <= len(tests):
            err.write(f"  a number from 1 to {len(tests)}\n")
            continue
        test = tests[int(typed) - 1]
        if _id(test) in removed:
            err.write(f"  {_id(test)} is already deleted\n")
            continue
        while (action := ask(f"  {_id(test)}: [c]hange its answer (Enter) or [d]elete it? ").strip().lower()) \
                not in {"", "c", "change", "d", "delete"}:
            err.write("  c changes, d deletes\n")
        if action in {"d", "delete"}:
            removed |= _delete(tests, _id(test), err)
        else:
            changed[_id(test)] = _changed(test, ask, err)
    return [test for test_id, test in changed.items() if test_id not in removed], removed
