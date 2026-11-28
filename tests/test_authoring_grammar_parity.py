"""Every authoring verb reads as its run does (aidd-command-grammar; Data Agent epic, Authoring Grammar Parity Test).

Driven by the parser, not by a list: each `fab-test <analyzer> <noun> <verb>` registered in it is checked
against its own run, so a third flow inherits every check without editing this file.

`_KNOWN_GAPS` is a ratchet, as in test_analyzer_contract_parity.py: a check's violations must equal its
recorded gaps exactly, so a new deviation fails and so does a fixed one still listed. Each gap is described
in .github/skills/aidd-command-grammar/references/known-gaps.md.

    pytest -m fab_test tests/test_authoring_grammar_parity.py
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from fab_test.scripts._authoring_output import run_flag
from fab_test.scripts._authoring_parser import _AUTHORING_NOUNS, authoring_verbs
from fab_test.scripts.fab_test_parser import _canonical_name, build_parser

pytestmark = pytest.mark.fab_test

_ROOT = Path(__file__).resolve().parent.parent
_SHARED_INPUTS = ("--artifact", "--artifact-dir", "--format", "--tests-dir")
_CONFIG_DEFAULTED = ("--artifact-dir", "--format")  # a literal default would skip fab-test.yml
_FILE_FLAG = {"contract": "--contract", "tests": "--tests"}  # --<noun> FILE overrides the pairing
_SKILL_FLAGS = (".github/skills/fab-test/references/flags.md", "src/fab_test/skill/references/flags.md")


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    return dict(action.choices) if action else {}


def _verbs() -> Iterator[tuple[str, str, str, argparse.ArgumentParser, argparse.ArgumentParser]]:
    """(analyzer word, noun, verb, the run's parser, the verb's parser) for every authoring verb."""
    analyzers = _subparsers(build_parser())
    for key, (noun, _suffix, _spellings) in sorted(_AUTHORING_NOUNS.items()):
        word = _canonical_name(key)
        run = analyzers[word]
        for verb, parser in sorted(_subparsers(_subparsers(run)[noun]).items()):
            yield word, noun, verb, run, parser


def _option(parser: argparse.ArgumentParser, flag: str) -> argparse.Action | None:
    return parser._option_string_actions.get(flag)


def _shared_inputs() -> set[str]:
    found = set()
    for word, noun, verb, run, parser in _verbs():
        target = next((a for a in parser._actions if a.dest == "target"), None)
        if target is None or target.metavar != "TARGET":
            found.add(f"{word} {noun} {verb}: TARGET")
        for flag in _SHARED_INPUTS:
            mine, theirs = _option(parser, flag), _option(run, flag)
            if mine is None or theirs is None or (mine.metavar, mine.help, mine.dest) != (
                    theirs.metavar, theirs.help, theirs.dest):
                found.add(f"{word} {noun} {verb}: {flag}")
    return found


def _config_defaults() -> set[str]:
    return {f"{word} {noun} {verb}: {flag}" for word, noun, verb, _run, parser in _verbs()
            for flag in _CONFIG_DEFAULTED
            if _option(parser, flag) is None or _option(parser, flag).default is not None}


def _file_flag() -> set[str]:
    found = set()
    for word, noun, verb, run, parser in _verbs():
        flag = _FILE_FLAG[noun]
        mine, theirs = _option(parser, flag), _option(run, flag)
        if mine is None or theirs is None or mine.help == argparse.SUPPRESS or (mine.metavar, mine.help) != (
                theirs.metavar, theirs.help):
            found.add(f"{word} {noun} {verb}: {flag}")
    return found


def _verbosity() -> set[str]:
    found = set()
    for word, noun, verb, _run, parser in _verbs():
        quiet, verbose = _option(parser, "-q"), _option(parser, "-v")
        exclusive = any({quiet, verbose} <= set(group._group_actions) for group in parser._mutually_exclusive_groups)
        if quiet is None or verbose is None or not exclusive:
            found.add(f"{word} {noun} {verb}: -q/-v")
    return found


def _run_only_refused() -> set[str]:
    """Each flag of the run the verb doesn't take is refused naming the run, never argparse's error."""
    found = set()
    top = build_parser()
    for word, noun, verb, run, parser in _verbs():
        for flag in sorted(set(run._option_string_actions) - set(parser._option_string_actions) - {"-h", "--help"}):
            try:
                args, unknown = top.parse_known_args([word, noun, verb, flag, "VALUE"])
            except SystemExit:
                found.add(f"{word} {noun} {verb}: {flag} is argparse's error")
                continue
            if run_flag(word, unknown) != flag and flag not in (getattr(args, "pbir_flags", None) or []):
                found.add(f"{word} {noun} {verb}: {flag} is not refused")
    return found


def _listed() -> set[str]:
    found = set()
    skills = [(_ROOT / path).read_text(encoding="utf-8") for path in _SKILL_FLAGS]
    for word, noun, verb, run, _parser in _verbs():
        key = next(k for k in _AUTHORING_NOUNS if _canonical_name(k) == word)
        if f"fab-test {word} {noun} {verb}" not in authoring_verbs(key, word):
            found.add(f"{word} {noun} {verb}: list/explain")
        if f"{noun} init|lint" not in (_subparsers(build_parser())[word].description or "") + _help_line(word):
            found.add(f"{word} {noun} {verb}: fab-test help")
        if any(f"{noun} {verb}" not in text for text in skills):
            found.add(f"{word} {noun} {verb}: flags.md")
    return found


def _help_line(word: str) -> str:
    action = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return next((choice.help or "" for choice in action._choices_actions if choice.dest == word), "")


_CHECKS: dict[str, Callable[[], set[str]]] = {
    "shared inputs": _shared_inputs,
    "config defaults": _config_defaults,
    "file flag": _file_flag,
    "verbosity": _verbosity,
    "run-only flags refused": _run_only_refused,
    "listed": _listed,
}

_KNOWN_GAPS: dict[str, set[str]] = {
    # contract init writes the contract that pairs with the report, in fab-tests/pbir/; --contract is refused
    # naming the run instead of naming a file to write (known-gaps.md, `pbir contract init`).
    "file flag": {"pbir contract init: --contract"},
}


def test_the_parser_registers_both_authoring_flows():
    """Not vacuous: the checks below see every verb of both flows."""
    assert {(word, noun, verb) for word, noun, verb, _run, _parser in _verbs()} == {
        ("pbir", "contract", "init"), ("pbir", "contract", "lint"),
        ("data-agent", "tests", "init"), ("data-agent", "tests", "lint")}


@pytest.mark.parametrize("check", sorted(_CHECKS))
def test_every_authoring_verb_reads_as_its_run(check, monkeypatch):
    """Given every authoring verb, should match its run at each grammar touch point except recorded gaps."""
    monkeypatch.setenv("FAB_TEST_ENABLE_DATA_AGENT", "1")
    actual = _CHECKS[check]()
    expected = _KNOWN_GAPS.get(check, set())
    assert actual == expected, (
        f"{check}: new deviations {sorted(actual - expected)}; "
        f"fixed but still listed in _KNOWN_GAPS {sorted(expected - actual)}"
    )
