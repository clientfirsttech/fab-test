"""Navigator Rules, measured with PBIR Inspector (PBIR Bookmark Navigator Default epic).

Runs the real CLI on a copy of the SampleModel-DefaultState test bed, as
`test_slicer_rules_live.py` does, so every way a navigator can drift is seen
failing and the agreed state is seen passing.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from tests.test_slicer_rules_live import (
    TEST_BED,
    _bed,
    _contract,
    _envelope,
    _failed,
    _run,
    _visual,
    inspector,  # noqa: F401 -- the fixture
)

pytestmark = [pytest.mark.integration, pytest.mark.pbir]

PAGE_2_NAVIGATOR, EMPTY_NAVIGATOR = "e699bc93251123e7556a", "1f6b0d93c4e2a7581b3c"
STALE = {"CONTRACT.half-year-current"}  # the slicer rule the test bed fails on purpose


def _navigators(document: dict) -> list[dict]:
    return next(p["value"] for p in document["customProperties"] if p["property"] == "fabTestBookmarkNavigators")


def _expect(document: dict, **selected) -> dict:
    for entry in _navigators(document):
        if entry["id"] in selected:
            entry["selected"] = selected[entry["id"]]
    return document


def test_given_the_test_bed_contract_should_pass_every_navigator(inspector, tmp_path):  # noqa: F811
    root = _bed(tmp_path, _contract())

    _run(root)

    assert _failed(root) == STALE
    rules = {r["id"]: r for r in _envelope(root)["contract"]["navigators"]}
    assert rules["page-1-navigator"]["expected"] == "Bookmark 2"
    assert rules["page-1-navigator"]["bookmarks"] == ["9c65f6aa324d70ac0e33"]  # what the name resolved to
    assert rules["navigator-nothing-preselected"]["expected"] is None


def test_given_each_navigator_expecting_something_else_should_fail_each(inspector, tmp_path):  # noqa: F811
    document = _expect(_contract(), **{"page-1-navigator": "Bookmark 1",          # the other bookmark
                                       "page-2-navigator": None,                  # preselected, expected nothing
                                       "navigator-nothing-preselected": "Bookmark 1"})  # nothing, expected one
    root = _bed(tmp_path, document)

    _run(root)

    assert _failed(root) == STALE | {"CONTRACT.page-1-navigator", "CONTRACT.page-2-navigator",
                                     "CONTRACT.navigator-nothing-preselected"}
    messages = {f["rule"]: f["message"] for f in _envelope(root)["findings"]}
    assert "opens with [Bookmark 2]; the contract expects Bookmark 1" in messages["CONTRACT.page-1-navigator"]
    assert "opens with [Bookmark 1]; the contract expects no bookmark" in messages["CONTRACT.page-2-navigator"]
    assert "opens with [no bookmark]" in messages["CONTRACT.navigator-nothing-preselected"]


def test_given_drift_in_the_report_should_fail_rather_than_pass(inspector, tmp_path):  # noqa: F811
    document = _expect(_contract(), **{"navigator-nothing-preselected": "Bookmark 9"})
    _navigators(document).append({"id": "renamed-page", "page": "Renamed Away", "selected": "Bookmark 1"})
    root = _bed(tmp_path, document)
    bookmarks = root / TEST_BED.name / "definition" / "bookmarks"
    (bookmarks / "9c65f6aa324d70ac0e33.bookmark.json").unlink()  # Bookmark 2, which Page 1 preselects
    index = json.loads((bookmarks / "bookmarks.json").read_text(encoding="utf-8"))
    index["items"] = [i for i in index["items"] if i["name"] != "9c65f6aa324d70ac0e33"]
    (bookmarks / "bookmarks.json").write_text(json.dumps(index), encoding="utf-8")
    shutil.rmtree(_visual(root, PAGE_2_NAVIGATOR).parent)  # Page 2 loses its navigator

    _run(root)

    assert _failed(root) == STALE | {"CONTRACT.page-1-navigator", "CONTRACT.page-2-navigator",
                                     "CONTRACT.navigator-nothing-preselected",
                                     "CONTRACT.page.Renamed Away"}  # the page rule reports the renamed page
    messages = {f["rule"]: f["message"] for f in _envelope(root)["findings"]}
    assert "a bookmark the report no longer has" in messages["CONTRACT.page-1-navigator"]
    assert "the contract expects Bookmark 2 (the report has no bookmark by that name)" in messages[
        "CONTRACT.page-1-navigator"]
    assert "no bookmark navigator on page 'Page 2'" in messages["CONTRACT.page-2-navigator"]
    assert "Bookmark 9 (the report has no bookmark by that name)" in messages["CONTRACT.navigator-nothing-preselected"]


def test_given_a_preselection_added_where_none_was_agreed_should_fail(inspector, tmp_path):  # noqa: F811
    root = _bed(tmp_path, _contract())

    path = _visual(root, EMPTY_NAVIGATOR)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual"]["objects"] = {"bookmarks": [{"properties": {"selectedBookmark": {
        "expr": {"Literal": {"Value": "'75775dd0e605004cae9a'"}}}}}]}
    path.write_text(json.dumps(data), encoding="utf-8")

    _run(root)

    assert _failed(root) == STALE | {"CONTRACT.navigator-nothing-preselected"}


def test_given_a_contract_built_by_init_should_pass_every_navigator(inspector, tmp_path):  # noqa: F811
    root = _bed(tmp_path, None)
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"standard-slicers-fiscal-semester": "calendar"}), encoding="utf-8")
    init = subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "pbir", "contract", "init", str(root / TEST_BED.name),
         "--as-of", "2026-11-14", "--answers", str(answers)],
        capture_output=True, text=True, encoding="utf-8", check=False, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert init.returncode == 0, init.stderr

    _run(root)

    assert _failed(root) == set()
    assert {r["id"] for r in _envelope(root)["contract"]["navigators"]} == {
        "page-1-bookmark-navigator", "page-2-bookmark-navigator", "empty-and-all-bookmark-navigator"}
