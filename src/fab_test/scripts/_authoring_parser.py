"""Resolve the ambiguity between an analyzer's optional TARGET and its authoring noun."""

import argparse
import copy
import sys
from pathlib import Path

# analyzer -> (noun, item folder suffix, the noun's near-miss spellings)
_AUTHORING_NOUNS = {
    "pbir": ("contract", ".Report", frozenset({"contracts"})),
    "data_agent": ("tests", ".DataAgent", frozenset({"test"})),
}
_VERBS = frozenset({"init", "lint"})


def _item_exists(name: str, args: argparse.Namespace, suffix: str) -> bool:
    """An item folder: named with the analyzer's suffix, or holding a `.platform`.

    A plain `lint` or `test` folder in the working directory is not an item (Review 2).
    """
    root = Path(getattr(args, "artifact_dir", None) or ".")
    return any(base.joinpath(f"{name}{suffix}").exists() or base.joinpath(name, ".platform").is_file()
               for base in (Path(), root))


def _shown(word: str) -> str:
    return f'"{word}"' if not word or any(ch.isspace() for ch in word) else word


def near_miss(args: argparse.Namespace, words: list[str]) -> str | None:
    """``did you mean: <the exact command>`` for a verb out of place or a misspelt noun (decision 15).

    ``fab-test pbir lint`` used to run a TARGET named ``lint``, find nothing and pass. An item
    really named ``init``, ``lint`` or ``contracts`` still runs as a TARGET.
    """
    from .fab_test_parser import _SUBCOMMAND_ALIASES

    analyzer = _SUBCOMMAND_ALIASES.get(args.analyzer, args.analyzer)
    noun, suffix, spellings = _AUTHORING_NOUNS.get(analyzer, (None, "", frozenset()))
    word = getattr(args, "target", None)
    if noun is None or getattr(args, "authoring_noun", None) or not word:
        return None
    if word in _VERBS:
        replacement = [noun, word]
    elif word in spellings:
        replacement = [noun]
    else:
        return None
    if _item_exists(word, args, suffix):
        return None
    try:
        at = words.index(word, words.index(args.analyzer) + 1)
    except ValueError:  # argv no longer holds the words as typed: say less rather than guess
        return f"did you mean: fab-test {args.analyzer} {' '.join(replacement)} ..."
    meant = [*words[:at], *replacement, *words[at + 1:]]
    return "did you mean: fab-test " + " ".join(_shown(part) for part in meant)


def parse_authoring_analyzer(parser: argparse.ArgumentParser, args, namespace):
    """Parse with either TARGET or the registered noun, without mutating the shared parser."""
    words = list(sys.argv[1:] if args is None else args)
    noun_action = parser._authoring_noun_action
    authoring = bool(words and words[0] in noun_action.choices)
    active = copy.copy(parser)
    active._actions = [
        action for action in parser._actions
        if action is not (parser._authoring_target_action if authoring else noun_action)
    ]
    return argparse.ArgumentParser.parse_known_args(active, words, namespace)


def add_authoring_noun(parser: argparse.ArgumentParser, name: str, parent: argparse.ArgumentParser) -> None:
    """Register a real noun subparser beside the analyzer's existing run grammar."""
    parser._authoring_target_action = next(action for action in parser._actions if action.dest == "target")
    nouns = parser.add_subparsers(dest="authoring_noun", metavar=f"{{{name}}}")
    parser._authoring_noun_action = nouns
    nouns.add_parser(name, parents=[parent], add_help=False, help=f"Author or check {name} files")
