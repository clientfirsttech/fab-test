"""Check which bookmark a bookmark navigator opens with (PBIR Bookmark Navigator Default epic).

Desktop stores a navigator's preselection as the bookmark's internal name, a
DAX string in `visual.objects.bookmarks[0].properties.selectedBookmark`, and
leaves it out when nothing is preselected. A contract names the bookmark the
way the report shows it (its display name), so fab-test looks names up in
`definition/bookmarks/*.bookmark.json` when it reads or compiles:

- `read_navigators`: what each page's navigator opens with, for `contract init`
- `compile_navigator_rules`: one page-scoped PBIR Inspector rule per entry,
  which fails on another bookmark, on nothing, on a deleted bookmark, on a
  page with no navigator, and on a bookmark the report doesn't have
- `navigator_questions` / `navigator_entry` / `merge_navigators`: the `init` side
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._navigator_contract import NAVIGATORS_PROPERTY, NavigatorExpectation
from ._pbir_slicers import decode_literal, load_json, page_visuals
from ._slicer_contract import dax_literal
from ._slicer_rules import RULE_PREFIX

__all__ = ["NavigatorExpectation", "compile_navigator_rules", "read_bookmarks", "read_navigators"]

NAVIGATOR_TYPE = "bookmarkNavigator"
_SELECTED = "visual.objects.bookmarks.0.properties.selectedBookmark.expr.Literal.Value"
_NOTHING = "no bookmark"
_DELETED = "a bookmark the report no longer has"
_UNKNOWN = " (the report has no bookmark by that name)"


@dataclass(frozen=True)
class Navigator:
    page: str
    current: dict[str, Any]  # {"selected": display name or None}, or {"unsupported": reason}


def read_bookmarks(report: Path) -> dict[str, str]:
    """{internal name: display name} for every bookmark, grouped or not."""
    files = sorted((report / "definition" / "bookmarks").glob("*.bookmark.json"))
    bookmarks = {}
    for path in files:
        data = load_json(path)
        name = data.get("name") or path.name.removesuffix(".bookmark.json")
        bookmarks[name] = data.get("displayName", name)
    return bookmarks


def read_navigators(report: Path) -> list[Navigator]:
    """One per page that has a navigator, in page order. Raises OSError/ValueError on bad JSON."""
    bookmarks = read_bookmarks(report)
    navigators = []
    for page, visuals in page_visuals(report):
        found = [_current(v, bookmarks) for v in visuals if v.get("visual", {}).get("visualType") == NAVIGATOR_TYPE]
        if found:
            same = all(c == found[0] for c in found)
            reason = f"{len(found)} bookmark navigators on this page preselect different bookmarks"
            navigators.append(Navigator(page, found[0] if same else {"unsupported": reason}))
    return navigators


def _current(container: dict, bookmarks: dict[str, str]) -> dict[str, Any]:
    objects = container.get("visual", {}).get("objects", {})
    literal = (objects.get("bookmarks") or [{}])[0].get("properties", {}).get("selectedBookmark", {}) \
        .get("expr", {}).get("Literal", {}).get("Value")
    if literal is None:
        return {"selected": None}
    name = decode_literal(literal)
    if name not in bookmarks:
        return {"unsupported": f"{_DELETED} ({name})"}
    return {"selected": bookmarks[name]}


def compile_navigator_rules(expectations: list[NavigatorExpectation], bookmarks: dict[str, str]) -> list[dict]:
    """The PBIR Inspector rules for a contract's navigator entries, against this report's bookmarks."""
    return [_rule(e, bookmarks) for e in expectations]


def _rule(e: NavigatorExpectation, bookmarks: dict[str, str]) -> dict[str, Any]:
    navigators = {"filter": [{"part": "Visuals"}, {"==": [{"var": "visual.visualType"}, NAVIGATOR_TYPE]}]}
    selected = {"var": _SELECTED}
    names = [branch for name, shown in bookmarks.items() for branch in ({"==": [selected, dax_literal(name)]}, shown)]
    shown = {"if": [{"!": [selected]}, _NOTHING, *names, {"cat": [f"{_DELETED} (", selected, ")"]}]}
    if e.selected is None:
        matches, expected = {"!": [selected]}, _NOTHING
    else:
        ids = [dax_literal(name) for name, shown_as in bookmarks.items() if shown_as == e.selected]
        matches, expected = {"in": [selected, ids]}, e.selected + ("" if ids else _UNKNOWN)
    mismatches = {"map": [{"filter": [navigators, {"!": [matches]}]},
                          {"cat": ["the bookmark navigator opens with [", shown,
                                   f"]; the contract expects {expected}"]}]}
    return {
        "id": f"{RULE_PREFIX}{e.rule_id}",
        "name": f"{e.page}: the bookmark navigator opens with {e.selected or _NOTHING}",
        "description": f"Bookmark navigator default from the contract entry {e.rule_id}.",
        "logType": e.severity,
        "disabled": False,
        "part": "Pages",
        "test": [
            {"if": [
                {"!=": [{"var": "displayName"}, e.page]}, [],
                {"==": [{"count": [navigators]}, 0]}, [f"no bookmark navigator on page '{e.page}'"],
                mismatches,
            ]},
            {},
            [],
        ],
    }


def navigator_questions(report: Path, rule_id: Callable[[str], str]) -> list[dict[str, Any]]:
    """`contract init` questions, one per page with a navigator; ``rule_id`` makes ids unique across the contract."""
    questions = []
    for n in read_navigators(report):
        question = {"id": rule_id(f"{n.page} bookmark navigator"), "kind": "navigator", "page": n.page,
                    "current": n.current, "needs_human": False}
        if "unsupported" in n.current:
            question.update(prompt=f"{n.page}: the bookmark navigator opens with {n.current['unsupported']}, "
                                   "which a contract can't check. Skip it?", choices=["skip"], suggested="skip")
        else:
            question.update(prompt=f"{n.page}: the bookmark navigator opens with "
                                   f"{n.current['selected'] or _NOTHING}. Keep checking that or skip it?",
                            choices=["keep", "skip"], suggested="keep")
        questions.append(question)
    return questions


def navigator_entry(question: dict, answer: Any) -> dict[str, Any] | None:
    """The contract entry for an answer, or None to skip. Raises ValueError on an answer it can't apply."""
    if answer == "skip":
        return None
    if answer != "keep" or "unsupported" in question["current"]:
        allowed = " or ".join(question["choices"])
        raise ValueError(f"{question['id']}: answer must be {allowed}, got {answer!r}")
    return {"id": question["id"], "page": question["page"], "selected": question["current"]["selected"]}


def merge_navigators(document: dict, entries: list[dict], force: bool, summary: dict[str, list]) -> None:
    """Append new entries; change an existing one's page or selection only with ``force``."""
    if not entries:
        return
    properties = document.setdefault("customProperties", [])
    existing = next((p for p in properties if isinstance(p, dict) and p.get("property") == NAVIGATORS_PROPERTY), None)
    if existing is None:
        existing = {"property": NAVIGATORS_PROPERTY, "value": []}
        properties.append(existing)
    listed = existing.setdefault("value", [])
    for entry in entries:
        current = next((n for n in listed if isinstance(n, dict) and n.get("id") == entry["id"]), None)
        if current is None:
            listed.append(entry)
            summary["added"].append(entry["id"])
        elif (current.get("page"), current.get("selected")) == (entry["page"], entry["selected"]):
            summary["unchanged"].append(entry["id"])
        elif force:
            current.update(page=entry["page"], selected=entry["selected"])
            summary["replaced"].append(entry["id"])
        else:
            summary["kept"].append(entry["id"])
