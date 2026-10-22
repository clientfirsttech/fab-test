"""Every analyzer is registered at every touch point the analyzer contract names.

The contract (.github/skills/aidd-analyzer-contract) spreads one analyzer
over about twenty registration points, and nothing checked them against
each other: an analyzer could pass its own tests and still be missing from
`fab-test local` or the marker maps. Each check below compares one touch
point with `ANALYZER_REGISTRY`.

`_KNOWN_GAPS` is a ratchet, not an allowlist. A check's violations must
equal its recorded gaps exactly: a new deviation fails, and so does a
fixed one still listed, so the list can only shrink. Each gap is also
described in the skill's references/known-gaps.md.

    pytest -m fab_test tests/test_analyzer_contract_parity.py
"""

from __future__ import annotations

import argparse
import configparser
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from fab_test.scripts._command_builders import _COMMAND_BUILDERS
from fab_test.scripts.fab_test_admin import _TOOL_DISPLAY_NAMES
from fab_test.scripts.fab_test_local import _LOCAL_ANALYZERS
from fab_test.scripts.fab_test_parser import build_parser
from fab_test.scripts.fab_test_registry import (
    _BOOTSTRAP_REGISTRY_NAME,
    ANALYZER_REGISTRY,
    ANALYZER_SCOPES,
    HIDDEN_ANALYZERS,
)

from .conftest import _ANALYZER_MARKERS, _MARKER_SUFFIX

_ROOT = Path(__file__).resolve().parent.parent
_ANALYZERS_JSON = json.loads((_ROOT / "src" / "fab_test" / "metadata" / "analyzers.json").read_text(encoding="utf-8"))

# Registry keys whose analyzers.json entry has a different name. The
# envelope's `analyzer` field uses the JSON name (a known gap of its own).
_JSON_NAME = {**_BOOTSTRAP_REGISTRY_NAME, "pql_lint": "pqlint"}

# The Fabric item type each artifact glob reads, as artifact_analyzers keys it.
_GLOB_TYPE = {"*.SemanticModel": "SemanticModel", "*.Report": "Report", "*.rdl": "PaginatedReport"}


def _json_entry(name: str) -> dict | None:
    return _ANALYZERS_JSON["analyzer_registry"].get(_JSON_NAME.get(name, name))


def _is_static(name: str) -> bool:
    entry = _json_entry(name)
    return entry is not None and entry["type"] in {"static", "both"}


def _subcommands() -> set[str]:
    actions = (a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return {choice for action in actions for choice in action.choices}


def _pytest_markers() -> set[str]:
    ini = configparser.ConfigParser()
    ini.read(_ROOT / "pytest.ini", encoding="utf-8")
    lines = ini["pytest"]["markers"].strip().splitlines()
    return {line.split(":", 1)[0].strip() for line in lines}


def _missing_from(names: set[str]) -> set[str]:
    return set(ANALYZER_REGISTRY) - names


def _not_in_artifact_analyzers() -> set[str]:
    by_type = _ANALYZERS_JSON["artifact_analyzers"]
    return {
        name
        for name, (glob, _) in ANALYZER_REGISTRY.items()
        if _is_static(name)
        and _JSON_NAME.get(name, name) not in by_type.get(_GLOB_TYPE.get(glob, ""), {}).get("static", [])
    }


def _static_not_local() -> set[str]:
    visible_static = {name for name in ANALYZER_REGISTRY if _is_static(name) and name not in HIDDEN_ANALYZERS}
    return visible_static - set(_LOCAL_ANALYZERS)


def _marker_glob_mismatch() -> set[str]:
    return {name for name, glob in _MARKER_SUFFIX.items() if ANALYZER_REGISTRY.get(name, ("",))[0] != glob}


def _unregistered(names: set[str]) -> set[str]:
    return names - set(ANALYZER_REGISTRY)


_CHECKS: dict[str, Callable[[], set[str]]] = {
    "scopes": lambda: _missing_from(set(ANALYZER_SCOPES)),
    "command builder": lambda: _missing_from(set(_COMMAND_BUILDERS)),
    "subcommand": lambda: _missing_from(_subcommands()),
    "analyzers.json entry": lambda: {name for name in ANALYZER_REGISTRY if _json_entry(name) is None},
    "artifact_analyzers static": _not_in_artifact_analyzers,
    "local bundle": _static_not_local,
    "pytest.ini marker": lambda: _missing_from(_pytest_markers()),
    "conftest marker maps": lambda: (
        {name for name in ANALYZER_REGISTRY if _is_static(name)} - (_ANALYZER_MARKERS & set(_MARKER_SUFFIX))
    ),
    "marker glob": _marker_glob_mismatch,
    "tool display name": lambda: set(_BOOTSTRAP_REGISTRY_NAME) - set(_TOOL_DISPLAY_NAMES),
    "unregistered name": lambda: _unregistered(
        set(_LOCAL_ANALYZERS) | set(_ANALYZERS_JSON["fab_test_all"]) | set(_TOOL_DISPLAY_NAMES) | _ANALYZER_MARKERS
    ),
}

_KNOWN_GAPS: dict[str, set[str]] = {
    # Repository-scoped and in-house: no analyzers.json entry, no marker.
    "analyzers.json entry": {"dependencies"},
    "pytest.ini marker": {"dependencies"},
    "artifact_analyzers static": {"a11y", "pql_lint"},
    "local bundle": {"a11y"},
    "conftest marker maps": {"a11y"},
}


@pytest.mark.fab_test
@pytest.mark.parametrize("check", sorted(_CHECKS))
def test_analyzer_touch_points_match_the_registry(check):
    """Given every registered analyzer, should appear at each touch point except its recorded gaps."""
    actual = _CHECKS[check]()
    expected = _KNOWN_GAPS.get(check, set())
    assert actual == expected, (
        f"{check}: new deviations {sorted(actual - expected)}; "
        f"fixed but still listed in _KNOWN_GAPS {sorted(expected - actual)}"
    )
