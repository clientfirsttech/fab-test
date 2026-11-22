"""The caller's own questions, how each answer matches, and follow-up chains (`tests init`).

The caller writes every question and every expected answer; fab-test only offers suggestions
(decision 14). Each choice is one key, Enter takes the default shown, and a wrong key asks again
without losing what was typed (aidd-polite-review).
"""

import json
import re
import sys
from collections.abc import Callable
from typing import Any, TextIO

from ._data_agent_init_questions import InitInputError

__all__ = ["MATCH_KEYS", "InitInputError", "ask_tests", "assertion", "default_match", "input_prompt",
           "parse_match", "question_key", "specs_from_answers", "tests_from_answers", "tests_from_specs"]

# key, canonical name, extra spellings accepted (the full name always is)
_MATCHES = (
    ("n", "number", ()),
    ("c", "contains", ()),
    ("x", "exact", ("equals",)),
    ("s", "starts", ("starts with", "starts-with", "startswith")),
    ("e", "ends", ("ends with", "ends-with", "endswith")),
    ("p", "pattern", ("regex",)),
    ("r", "refuses", ("refuse", "declines")),
)
_LABELS = {"number": "[n]umber", "contains": "[c]ontains", "exact": "e[x]act", "starts": "[s]tarts with",
           "ends": "[e]nds with", "pattern": "[p]attern", "refuses": "[r]efuses"}
_SPELLINGS = {spelling: name for key, name, extra in _MATCHES for spelling in (key, name, *extra)}
_KEYS = ", ".join(f"{key} {name}" for key, name, _extra in _MATCHES)
MATCH_KEYS = {key: name for key, name, _extra in _MATCHES}
_NUMBER = re.compile(r"([-+]?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?")
# Decision 23: only the first sentence counts; a long answer says "don't" somewhere.
_REFUSAL = (r"/\b(cannot|can.t|unable|won.t|don.t|do not|no access|not (available|able|allowed|have|provide)"
            r"|isn.t (available|something)|outside)\b/i.test(output.trim().split(/(?<=[.!?])\s|\n/)[0])")
_ID_LENGTH = 40
_AS_TYPED = {"contains": "icontains", "exact": "equals", "pattern": "regex"}


def parse_match(typed: str) -> str:
    """One key or the full name, any case; an unknown one names every valid key."""
    name = _SPELLINGS.get(typed.strip().lower())
    if name is None:
        raise InitInputError(f"unknown match {typed.strip()!r}; use one of: {_KEYS}")
    return name


def default_match(expect: str | None) -> str:
    """number for a figure, contains for words, refuses when there is no expected answer."""
    if expect is None:
        return "refuses"
    return "number" if _NUMBER.fullmatch(expect.strip()) else "contains"


def _number_pattern(expect: str) -> str:
    found = _NUMBER.fullmatch(expect.strip())
    if not found:
        raise InitInputError(f"a number match needs a number, not {expect!r}; try c (contains)")
    sign, whole, fraction = found.group(1), found.group(2).replace(",", ""), found.group(3) or ""
    groups = []
    while len(whole) > 3:
        whole, groups = whole[:-3], [whole[-3:], *groups]
    body = ",?".join([whole, *groups]) + re.escape(fraction)
    # Digits or a separator on either side would make it a different figure (116,376 or 16,3760).
    return rf"{re.escape(sign)}(?<![\d,.]){body}(?![\d]|[,.]\d)"


def assertion(match: str, expect: str | None) -> dict[str, str]:
    """The promptfoo assertion a match type writes; the suite records it, never the key."""
    if match == "refuses":
        return {"type": "javascript", "value": _REFUSAL}
    if expect is None or not expect.strip():
        raise InitInputError(f"a {match} match needs an expected answer")
    if match == "number":
        return {"type": "regex", "value": _number_pattern(expect)}
    if match in _AS_TYPED:
        return {"type": _AS_TYPED[match], "value": expect}
    needle = json.dumps(expect.strip().lower())  # a JSON string is a valid JavaScript string literal
    predicate = (f"startsWith({needle})" if match == "starts"
                 else f"replace(/[.!?\\s]+$/, '').endsWith({needle})")
    return {"type": "javascript", "value": f"output.trim().toLowerCase().{predicate}"}


def _slug(query: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "question"
    if len(slug) <= _ID_LENGTH:
        return slug
    cut = slug[:_ID_LENGTH + 1]  # one more, to see whether the cut lands between words
    return cut.rsplit("-", 1)[0] if "-" in cut else slug[:_ID_LENGTH]


def _unique(base: str, taken: set[str], follow_ups: int = 0) -> str:
    """The slug, or the slug numbered, so neither it nor its follow-up ids are taken."""
    candidate, number = base, 2
    while candidate in taken or any(f"{candidate}-follow-up-{n}" in taken for n in range(1, follow_ups + 1)):
        candidate, number = f"{base}-{number}", number + 1
    taken.add(candidate)
    return candidate


def _test(test_id: str, spec: dict[str, Any], conversation: dict[str, Any]) -> dict[str, Any]:
    match = spec.get("match") or default_match(spec.get("expect"))
    return {"description": spec["query"], "metadata": {"id": test_id},
            "vars": {"query": spec["query"], **conversation},
            "assert": [assertion(parse_match(match), spec.get("expect"))]}


def tests_from_specs(specs: list[dict[str, Any]], taken: set[str] | frozenset = frozenset()
                     ) -> list[dict[str, Any]]:
    """Suite tests in order: each question, then its follow-ups in one conversation.

    A new question never takes an id that another new question, or the suite (``taken``), already
    has: a clash would read as "the same test" and the merge would drop it. Only a question the
    suite already has, or an explicit id, arrives with ``id`` set, so the merge keeps or replaces it.
    """
    tests = []
    used = set(taken)
    for spec in specs:
        follow_ups = spec.get("follow_ups") or []
        root = spec.get("id") or _unique(_slug(spec["query"]), used, len(follow_ups))
        used.update({root, *(f"{root}-follow-up-{n}" for n in range(1, len(follow_ups) + 1))})
        conversation = {"conversation": root, "reset": True} if follow_ups else {}
        tests.append(_test(root, spec, conversation))
        tests.extend(_test(f"{root}-follow-up-{number}", follow_up, {"conversation": root})
                     for number, follow_up in enumerate(follow_ups, 1))
    return tests


def _spec(raw: Any, where: str, *, allow_follow_ups: bool = True) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InitInputError(f"--answers {where} must be an object with query, expect and match")
    query = raw.get("query")
    if not isinstance(query, str) or not query.strip():
        raise InitInputError(f"--answers {where} needs a query: the question to ask the agent")
    match = parse_match(str(raw["match"])) if raw.get("match") else None
    expect = raw.get("expect")
    if match != "refuses" and (not isinstance(expect, str) or not expect.strip()):
        raise InitInputError(f"--answers {where} needs an expect: what a right answer contains, "
                             "or \"match\": \"refuses\" when the agent should decline")
    spec = {"query": query.strip(), "expect": expect.strip() if isinstance(expect, str) else None,
            "match": match or default_match(expect)}
    if isinstance(raw.get("id"), str) and raw["id"].strip():
        spec["id"] = raw["id"].strip()
    if "remove" in raw:
        raise InitInputError(f'--answers {where}: "remove" goes at the top level, as a list of test ids')
    if raw.get("replace") is True:  # as typing r at the prompt does; otherwise an existing test is kept
        spec["replace"] = True
    assertion(spec["match"], spec["expect"])  # refuse a bad number now, naming where it is
    follow_ups = raw.get("follow_ups", [])
    if not allow_follow_ups:
        return spec
    if not isinstance(follow_ups, list):
        raise InitInputError(f"--answers {where}.follow_ups must be a list of questions")
    spec["follow_ups"] = [_spec(item, f"{where}.follow_ups[{index}]", allow_follow_ups=False)
                          for index, item in enumerate(follow_ups)]
    return spec


def tests_from_answers(document: Any) -> list[dict[str, Any]]:
    """The --answers file as suite tests."""
    return tests_from_specs(specs_from_answers(document))


def specs_from_answers(document: Any) -> list[dict[str, Any]]:
    """The --answers file: the same questions, matches, follow-ups and replace the prompts take."""
    if not isinstance(document, dict):
        raise InitInputError("--answers must be a JSON object: {\"tests\": [...]}")
    if "tests" not in document:
        raise InitInputError("--answers needs \"tests\": a list of {query, expect, match, follow_ups}; "
                             "`fab-test data-agent tests init TARGET --questions` shows an example")
    if not isinstance(document["tests"], list):
        raise InitInputError("--answers tests must be a list of questions")
    return [_spec(item, f"tests[{index}]") for index, item in enumerate(document["tests"])]


# -- the prompt loop ---------------------------------------------------------------


Ask = Callable[[str], str]


def _ask_match(expect: str, indent: str, ask: Ask, err: TextIO) -> str:
    default = default_match(expect)
    order = [default, *(name for _key, name, _extra in _MATCHES if name not in (default, "refuses"))]
    prompt = f"{indent}Match: {' '.join(_LABELS[name] for name in order)} (Enter = {default}): "
    while True:
        typed = ask(prompt).strip()
        try:
            match = parse_match(typed) if typed else default
            assertion(match, expect)
        except InitInputError as exc:
            err.write(f"{indent}  {exc}\n")
            continue
        if match == "exact":
            err.write(f"{indent}  Exact needs the whole reply word for word, and agents rarely answer word for "
                      "word; c (contains) is usually what you mean.\n")
        return match


def _ask_one(query: str, indent: str, ask: Ask, err: TextIO) -> dict[str, Any]:
    expect = ask(f"{indent}Expected answer (Enter if the agent should decline): ").strip() or None
    if expect is None:
        err.write(f"{indent}  → expects the agent to decline\n")
        return {"query": query, "expect": None, "match": "refuses"}
    return {"query": query, "expect": expect, "match": _ask_match(expect, indent, ask, err)}


def _pick(typed: str, suggestions: list[str]) -> str:
    return suggestions[int(typed) - 1] if typed.isdigit() and 1 <= int(typed) <= len(suggestions) else typed


def input_prompt(text: str) -> str:
    """Prompt on stderr, so stdout stays the result."""
    sys.stderr.write(text)
    sys.stderr.flush()
    return input()


def question_key(query: str) -> str:
    """Two spellings of one question meet: case, spacing and a trailing ? or . don't matter."""
    return " ".join(query.lower().split()).rstrip("?.! ")


def _keep_or_replace(known: dict[str, str], ask: Ask, err: TextIO) -> bool:
    """True to replace: the person typed a question the suite already has, so their intent is unclear."""
    prompt = (f"  Already in the suite as {known['id']}, expecting {known['summary']}. "
              "[k]eep it (Enter) or [r]eplace with a new answer? ")
    while True:
        typed = ask(prompt).strip().lower()
        if typed in {"", "k", "keep"}:
            err.write("  → kept as it is\n")
            return False
        if typed in {"r", "replace"}:
            return True
        err.write("  k keeps it, r replaces it\n")


DECLINE_NOTE = " (the agent should decline)"


def numbered(suggestions: list[str], declines: set[str] | frozenset = frozenset()) -> str:
    """The suggestions as `?` and --questions number them, marking what the agent should decline."""
    return "".join(f"  {number}. {text}{DECLINE_NOTE if text in declines else ''}\n"
                   for number, text in enumerate(suggestions, 1))


def ask_tests(suggestions: list[str], ask: Ask | None = None, err: TextIO | None = None,
              existing: dict[str, dict[str, str]] | None = None,
              declines: set[str] | frozenset = frozenset()) -> list[dict[str, Any]]:
    """Ask for questions until Enter on an empty one; each may grow a chain of follow-ups.

    ``existing`` maps `question_key` to the suite's test (``id``, ``summary``). Typing one of those
    asks keep or replace, instead of silently keeping the old test and dropping the new answer.
    Prompts go to stderr, so stdout stays the result (and one JSON document under --format json).
    """
    ask, err, existing = ask or input_prompt, err or sys.stderr, existing or {}
    err.write("Write the questions to ask the agent and what a right answer looks like.\n"
              "Enter on an empty question finishes; ? lists suggestions from the agent's data.\n")
    specs: list[dict[str, Any]] = []
    while True:
        typed = ask(f"Question {len(specs) + 1}: ").strip()
        if typed == "?":
            err.write(numbered(suggestions, declines)
                      or "  No suggestions: the definition selects no tables or measures.\n")
            continue
        if not typed:
            return specs
        query = _pick(typed, suggestions)
        known = existing.get(question_key(query))
        if known and not _keep_or_replace(known, ask, err):
            continue
        spec = _ask_one(query, "  ", ask, err)
        spec["follow_ups"] = []
        if known:
            spec.update(id=known["id"], replace=True)
        while follow_up := ask("  Follow-up in the same conversation (Enter for none): ").strip():
            spec["follow_ups"].append(_ask_one(follow_up, "    ", ask, err))
        specs.append(spec)
