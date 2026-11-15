"""Bookmark navigator defaults (PBIR Bookmark Navigator Default epic): reading and compiling.

Pure tests; `test_bookmark_navigators_live.py` runs the compiled rules through
PBIR Inspector against the SampleModel-DefaultState test bed.
"""

import json
from pathlib import Path

import pytest
import yaml

from fab_test.scripts._bookmark_navigators import (
    NavigatorExpectation,
    compile_navigator_rules,
    read_bookmarks,
    read_navigators,
)
from fab_test.scripts._slicer_contract import ContractError, load_contract, parse_contract

ROOT = Path(__file__).resolve().parents[1]
TEST_BED = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report"
EXAMPLE = ROOT / "fabric-artifacts" / "SampleModel-DefaultState.Report.odcs.yaml"
BOOKMARK_1, BOOKMARK_2 = "75775dd0e605004cae9a", "9c65f6aa324d70ac0e33"


def _document(*navigators, schema=None):
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "id": "c", "version": "1.0.0", "status": "active",
            "customProperties": [{"property": "fabTestReport", "value": "abc"},
                                 {"property": "fabTestBookmarkNavigators", "value": list(navigators)}],
            "schema": schema or []}


def _errors(document) -> str:
    with pytest.raises(ContractError) as caught:
        parse_contract(document, Path("c.odcs.yaml"))
    return str(caught.value)


@pytest.mark.pbir
def test_given_the_test_bed_should_read_each_bookmark_by_its_display_name():
    assert read_bookmarks(TEST_BED) == {BOOKMARK_1: "Bookmark 1", BOOKMARK_2: "Bookmark 2"}


@pytest.mark.pbir
def test_given_the_test_bed_should_read_what_each_navigator_opens_with():
    current = {n.page: n.current for n in read_navigators(TEST_BED)}

    assert current == {"Empty and All": {"selected": None}, "Page 1": {"selected": "Bookmark 2"},
                       "Page 2": {"selected": "Bookmark 1"}}


def _report(tmp_path: Path, *selections) -> Path:
    report = tmp_path / "Bed.Report"
    pages = report / "definition" / "pages"
    (report / "definition" / "bookmarks").mkdir(parents=True)
    (report / "definition" / "bookmarks" / "b1.bookmark.json").write_text(
        json.dumps({"name": "b1", "displayName": "Home"}), encoding="utf-8")
    (pages / "p1").mkdir(parents=True)
    (pages / "pages.json").write_text(json.dumps({"pageOrder": ["p1"]}), encoding="utf-8")
    (pages / "p1" / "page.json").write_text(json.dumps({"displayName": "Overview"}), encoding="utf-8")
    for i, selected in enumerate(selections):
        objects = {} if selected is None else {"bookmarks": [{"properties": {
            "selectedBookmark": {"expr": {"Literal": {"Value": f"'{selected}'"}}}}}]}
        (pages / "p1" / "visuals" / f"v{i}").mkdir(parents=True)
        (pages / "p1" / "visuals" / f"v{i}" / "visual.json").write_text(
            json.dumps({"visual": {"visualType": "bookmarkNavigator", "objects": objects}}), encoding="utf-8")
    return report


@pytest.mark.pbir
@pytest.mark.parametrize("selections, reason", [
    (("b1", None), "2 bookmark navigators on this page preselect different bookmarks"),
    (("gone",), "a bookmark the report no longer has (gone)"),
])
def test_given_differing_navigators_or_a_deleted_bookmark_should_say_why_its_unsupported(tmp_path, selections,
                                                                                         reason):
    [navigator] = read_navigators(_report(tmp_path, *selections))

    assert navigator.current == {"unsupported": reason}


@pytest.mark.pbir
def test_given_two_navigators_preselecting_the_same_bookmark_should_read_one(tmp_path):
    assert [n.current for n in read_navigators(_report(tmp_path, "b1", "b1"))] == [{"selected": "Home"}]


@pytest.mark.pbir
def test_given_the_test_bed_contract_should_read_its_navigator_entries():
    navigators = load_contract(EXAMPLE).navigators

    assert {n.rule_id: (n.page, n.selected) for n in navigators} == {
        "page-1-navigator": ("Page 1", "Bookmark 2"), "page-2-navigator": ("Page 2", "Bookmark 1"),
        "navigator-nothing-preselected": ("Empty and All", None)}
    assert {n.severity for n in navigators} == {"error"}


@pytest.mark.pbir
@pytest.mark.parametrize("entry, error", [
    ({"page": "P", "selected": "B"}, "[0].id: required, findings are named by it"),
    ({"id": "n", "selected": "B"}, "[0].page: required, the page's display name"),
    ({"id": "n", "page": "P"}, "[0].selected: required, a bookmark's display name"),
    ({"id": "n", "page": "P", "selected": ["B"]}, "[0].selected: required, a bookmark's display name"),  # same rule
    ({"id": "n", "page": "P", "selected": "B", "severity": "fatal"}, "[0].severity: must be one of"),
    ({"id": "n", "page": "P", "selected": "B", "visual": "00dd"}, "[0].visual: unknown key"),
    ("Page 1", "[0]: must be a mapping with id, page and selected"),
])
def test_given_a_malformed_navigator_entry_should_name_its_path_and_what_is_wrong(entry, error):
    assert f"customProperties.fabTestBookmarkNavigators{error}" in _errors(_document(entry))


@pytest.mark.pbir
def test_given_an_id_shared_with_a_slicer_rule_or_reserved_should_refuse_it():
    slicer = {"name": "T", "properties": [{"name": "C", "quality": [
        {"id": "dup", "type": "custom", "engine": "fab-test", "implementation": {"page": "P", "selected": []}}]}]}

    message = _errors(_document({"id": "dup", "page": "P", "selected": None},
                                {"id": "page.P", "page": "P", "selected": None}, schema=[slicer]))

    assert "id 'dup': used by more than one rule" in message
    assert "id 'page.P': ids starting 'page.' are reserved" in message


@pytest.mark.pbir
def test_given_a_contract_with_only_navigators_should_be_found_as_a_fab_test_contract(tmp_path):
    from fab_test.scripts._slicer_contract_run import _has_slicer_rules

    path = tmp_path / "x.odcs.yaml"
    path.write_text(yaml.safe_dump(_document({"id": "n", "page": "P", "selected": None})), encoding="utf-8")

    assert _has_slicer_rules(path)


@pytest.mark.pbir
def test_given_a_navigator_only_contract_without_a_schema_should_read_it():
    document = _document({"id": "n", "page": "P", "selected": None})
    del document["schema"]                       # ODCS v3 doesn't require one

    contract = parse_contract(document, Path("c.odcs.yaml"))

    assert (contract.expectations, [n.rule_id for n in contract.navigators]) == ([], ["n"])


@pytest.mark.pbir
def test_given_a_schema_that_isnt_a_list_should_still_refuse_it():
    assert "\n  schema: must be a list\n" in _errors(_document(schema="AlignmentDim")) + "\n"


def _rule(expectation, bookmarks=None):
    rules = compile_navigator_rules([expectation], bookmarks or {BOOKMARK_1: "Bookmark 1", BOOKMARK_2: "Bookmark 2"})
    [rule] = rules
    return rule


@pytest.mark.pbir
def test_given_a_navigator_expectation_should_compile_a_page_scoped_rule_carrying_its_severity():
    rule = _rule(NavigatorExpectation("page-1-navigator", "Page 1", "Bookmark 2", "warning"))

    assert (rule["id"], rule["part"], rule["logType"]) == ("CONTRACT.page-1-navigator", "Pages", "warning")
    assert rule["name"] == "Page 1: the bookmark navigator opens with Bookmark 2"


@pytest.mark.pbir
def test_given_a_navigator_expectation_should_find_navigators_by_type_and_compare_the_bookmarks_internal_name():
    text = json.dumps(_rule(NavigatorExpectation("n", "Page 1", "Bookmark 2", "error"))["test"])

    assert '{"==": [{"var": "visual.visualType"}, "bookmarkNavigator"]}' in text
    selected = "visual.objects.bookmarks.0.properties.selectedBookmark.expr.Literal.Value"
    assert f'"in": [{{"var": "{selected}"}}, ["\'{BOOKMARK_2}\'"]]' in text   # the name Desktop saves
    assert '{"var": "name"}' not in text and '"visual.name"' not in text     # never one visual by its id


@pytest.mark.pbir
def test_given_a_bookmark_the_report_doesnt_have_should_say_so_in_the_rule():
    rule = _rule(NavigatorExpectation("n", "Page 1", "Bookmark 9", "error"))

    assert "Bookmark 9 (the report has no bookmark by that name)" in json.dumps(rule)


@pytest.mark.pbir
def test_given_nothing_preselected_expected_should_name_it():
    rule = _rule(NavigatorExpectation("n", "P", None, "error"))

    assert rule["name"] == "P: the bookmark navigator opens with no bookmark"


def _bookmarks(report: Path, listed: list[str], files: dict[str, object]) -> None:
    folder = report / "definition" / "bookmarks"
    (folder / "bookmarks.json").write_text(json.dumps({"items": [{"name": n} for n in listed]}), encoding="utf-8")
    for name, content in files.items():
        text = content if isinstance(content, str) else json.dumps(content)
        (folder / f"{name}.bookmark.json").write_text(text, encoding="utf-8")


@pytest.mark.pbir
def test_given_bookmark_files_bookmarks_json_doesnt_list_or_cant_read_should_treat_them_as_gone(tmp_path):
    report = _report(tmp_path)
    _bookmarks(report, ["b1", "broken", "listed"], {
        "orphan": {"name": "orphan", "displayName": "Orphan"},           # left on disk, not in the report
        "broken": "{not json", "listed": ["not", "an", "object"],
        "b1": {"name": "b1", "displayName": "Home"}})

    assert read_bookmarks(report) == {"b1": "Home"}


@pytest.mark.pbir
def test_given_a_grouped_bookmark_should_read_it_from_its_group(tmp_path):
    report = _report(tmp_path)
    folder = report / "definition" / "bookmarks"
    (folder / "bookmarks.json").write_text(json.dumps({"items": [
        {"name": "g1", "displayName": "Group", "children": ["b1"]}]}), encoding="utf-8")

    assert read_bookmarks(report) == {"b1": "Home"}


@pytest.mark.pbir
def test_given_two_bookmarks_sharing_a_display_name_should_refuse_to_guess(tmp_path):
    report = _report(tmp_path, "b1")
    _bookmarks(report, ["b1", "b2"], {"b2": {"name": "b2", "displayName": "Home"}})

    [navigator] = read_navigators(report)
    rule = _rule(NavigatorExpectation("n", "Overview", "Home", "error"), read_bookmarks(report))

    assert "2 bookmarks are named Home" in navigator.current["unsupported"]
    assert "Home (2 bookmarks share that name)" in json.dumps(rule)
    selected = "visual.objects.bookmarks.0.properties.selectedBookmark.expr.Literal.Value"
    assert f'"in": [{{"var": "{selected}"}}, []]' in json.dumps(rule)  # matches neither, so both fail


@pytest.mark.pbir
@pytest.mark.parametrize("value", [None, "not a list"])
def test_given_a_navigator_property_without_a_list_should_start_one_or_refuse(value):
    from fab_test.scripts._bookmark_navigators import merge_navigators

    document = {"customProperties": [{"property": "fabTestBookmarkNavigators", "value": value}]}
    summary = {"added": [], "kept": [], "replaced": [], "unchanged": []}
    entry = {"id": "n", "page": "P", "selected": None}

    if value is None:
        merge_navigators(document, [entry], False, summary)
        assert document["customProperties"][0]["value"] == [entry] and summary["added"] == ["n"]
    else:
        with pytest.raises(ValueError, match="fabTestBookmarkNavigators"):
            merge_navigators(document, [entry], False, summary)


@pytest.mark.pbir
def test_given_custom_properties_that_arent_a_list_should_refuse():
    from fab_test.scripts._bookmark_navigators import merge_navigators

    with pytest.raises(ValueError, match="customProperties"):
        merge_navigators({"customProperties": {"a": 1}}, [{"id": "n", "page": "P", "selected": None}], False,
                         {"added": [], "kept": [], "replaced": [], "unchanged": []})


def _question(current):
    return {"id": "n", "kind": "navigator", "page": "P", "current": current,
            "choices": ["skip"] if "unsupported" in current else ["keep", "skip"]}


@pytest.mark.pbir
def test_given_an_unsupported_navigator_should_offer_only_skip(tmp_path):
    from fab_test.scripts._bookmark_navigators import navigator_questions

    [question] = navigator_questions(_report(tmp_path, "gone"), lambda text: "n")

    assert (question["choices"], question["suggested"]) == (["skip"], "skip")
    assert "a bookmark the report no longer has (gone)" in question["prompt"]


@pytest.mark.pbir
def test_given_a_navigator_should_offer_keep_and_show_its_bookmark_or_no_bookmark(tmp_path):
    from fab_test.scripts._bookmark_navigators import navigator_questions

    [home] = navigator_questions(_report(tmp_path, "b1"), lambda text: "n")
    [nothing] = navigator_questions(_report(tmp_path / "2", None), lambda text: "n")

    assert (home["choices"], home["suggested"]) == (["keep", "skip"], "keep")
    assert "opens with Home." in home["prompt"] and "opens with no bookmark." in nothing["prompt"]


@pytest.mark.pbir
@pytest.mark.parametrize("current, answer", [({"unsupported": "why"}, "keep"), ({"selected": "Home"}, "calendar")])
def test_given_an_answer_the_navigator_cant_take_should_refuse_it_naming_the_choices(current, answer):
    from fab_test.scripts._bookmark_navigators import navigator_entry

    allowed = "skip" if "unsupported" in current else "keep or skip"
    with pytest.raises(ValueError, match=f"n: answer must be {allowed}, got '{answer}'"):
        navigator_entry(_question(current), answer)


@pytest.mark.pbir
def test_given_keep_or_skip_should_write_the_entry_or_nothing():
    from fab_test.scripts._bookmark_navigators import navigator_entry

    assert navigator_entry(_question({"selected": None}), "keep") == {"id": "n", "page": "P", "selected": None}
    assert navigator_entry(_question({"selected": "Home"}), "skip") is None


@pytest.mark.pbir
@pytest.mark.parametrize("entry, force, bucket, stored", [
    ({"id": "n", "page": "P", "selected": "Home"}, False, "unchanged", "Home"),
    ({"id": "n", "page": "P", "selected": "Away"}, False, "kept", "Home"),       # without --force, yours stays
    ({"id": "n", "page": "P", "selected": "Away"}, True, "replaced", "Away"),
    ({"id": "m", "page": "Q", "selected": None}, False, "added", "Home"),
])
def test_given_an_existing_entry_should_report_what_merging_did_to_it(entry, force, bucket, stored):
    from fab_test.scripts._bookmark_navigators import merge_navigators

    mine = {"id": "n", "page": "P", "selected": "Home", "severity": "warning"}
    document = {"customProperties": [{"property": "fabTestBookmarkNavigators", "value": [mine]}]}
    summary = {"added": [], "kept": [], "replaced": [], "unchanged": []}

    merge_navigators(document, [entry], force, summary)

    assert {k: v for k, v in summary.items() if v} == {bucket: [entry["id"]]}
    assert (mine["selected"], mine["severity"]) == (stored, "warning")      # --force keeps anything else you added
