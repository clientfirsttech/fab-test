"""`tests init` [e]dit: change a test's answer or delete it, picked by number (Data Agent Testing epic).

An injected prompt loop and a temporary suite: no console, no service, no promptfoo.
"""

from __future__ import annotations

import argparse
import io
import json

import pytest
import yaml

from fab_test.scripts import _data_agent_init as init
from fab_test.scripts._data_agent_init_edit import edit_tests, later_turns
from fab_test.scripts._data_agent_init_tests import InitInputError
from fab_test.scripts._data_agent_init_tests import tests_from_specs as _from_specs

pytestmark = pytest.mark.data_agent


def _suite_tests():
    return _from_specs([
        {"query": "How many orders?", "expect": "1,204", "match": "n",
         "follow_ups": [{"query": "More than 1,000?", "expect": "yes", "match": "s"},
                        {"query": "And 2,000?", "expect": "no", "match": "s"}]},
        {"query": "Tell me a joke", "match": "r"},
    ])


def _edit(tests, *typed):
    replies = iter(typed)
    err = io.StringIO()
    changed, removed = edit_tests(tests, lambda prompt: (err.write(prompt), next(replies))[1], err)
    return changed, removed, err.getvalue()


def test_the_list_numbers_every_test_and_indents_follow_ups():
    _changed, _removed, shown = _edit(_suite_tests(), "")
    assert "1. how-many-orders: How many orders?" in shown
    assert "2.   how-many-orders-follow-up-1: More than 1,000?" in shown
    assert "4. tell-me-a-joke: Tell me a joke" in shown


def test_changing_an_answer_rewrites_only_its_check():
    tests = _suite_tests()
    changed, removed, _shown = _edit(tests, "4", "c", "a pun", "", "")
    (test,) = changed
    assert removed == set()
    assert {k: v for k, v in test.items() if k != "assert"} == {k: v for k, v in tests[3].items() if k != "assert"}
    assert "a pun" in json.dumps(test["assert"]) and test["assert"] != tests[3]["assert"]


def test_enter_changes_the_answer_and_a_follow_up_stays_in_its_conversation():
    tests = _suite_tests()
    changed, _removed, _shown = _edit(tests, "2", "", "no", "", "")
    (test,) = changed
    assert test["vars"] == tests[1]["vars"]  # still the second turn of how-many-orders
    assert "no" in json.dumps(test["assert"])


def test_deleting_a_first_turn_deletes_its_conversation():
    _changed, removed, shown = _edit(_suite_tests(), "1", "d", "")
    assert removed == {"how-many-orders", "how-many-orders-follow-up-1", "how-many-orders-follow-up-2"}
    assert "2 later turns" in shown


def test_deleting_a_follow_up_deletes_the_turns_after_it_only():
    _changed, removed, _shown = _edit(_suite_tests(), "2", "d", "")
    assert removed == {"how-many-orders-follow-up-1", "how-many-orders-follow-up-2"}


def test_a_lone_test_deletes_alone():
    _changed, removed, shown = _edit(_suite_tests(), "4", "d", "")
    assert removed == {"tell-me-a-joke"} and "later turn" not in shown


def test_a_wrong_number_or_key_asks_again_and_a_deleted_test_says_so():
    changed, removed, shown = _edit(_suite_tests(), "9", "x", "4", "q", "d", "4", "")
    assert removed == {"tell-me-a-joke"} and changed == []
    assert "1 to 4" in shown and "c changes, d deletes" in shown and "already deleted" in shown


def test_later_turns_follow_the_suite_order():
    tests = _suite_tests()
    assert later_turns(tests, "how-many-orders-follow-up-1") == ["how-many-orders-follow-up-1",
                                                                  "how-many-orders-follow-up-2"]
    assert later_turns(tests, "tell-me-a-joke") == ["tell-me-a-joke"]


# -- the whole flow, at a console and from --answers ---------------------------------


def _item(tmp_path):
    item = tmp_path / "Sales.DataAgent"
    draft = item / "Files" / "Config" / "draft" / "model"
    draft.mkdir(parents=True)
    (item / ".platform").write_text(json.dumps({"config": {"logicalId": "sales-id"},
                                                "metadata": {"displayName": "Sales"}}), encoding="utf-8")
    (draft.parent / "stage_config.json").write_text("{}", encoding="utf-8")
    (draft / "datasource.json").write_text(json.dumps({"elements": [
        {"type": "semantic_model.table", "display_name": "Orders", "is_selected": True}]}), encoding="utf-8")
    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    suite.write_text(yaml.safe_dump({"fabTestDataAgent": "sales-id", "prompts": ["{{query}}"],
                                     "tests": _suite_tests()}, sort_keys=False), encoding="utf-8")
    return suite


def _run(tmp_path, monkeypatch, typed=(), *, dry_run=False, answers=None):
    suite = _item(tmp_path)
    replies = iter(typed)
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    monkeypatch.setattr(init, "can_ask", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    answers_file = None
    if answers is not None:
        answers_file = tmp_path / "answers.json"
        answers_file.write_text(json.dumps(answers), encoding="utf-8")
    args = argparse.Namespace(target="Sales", artifact=None, artifact_dir=str(tmp_path), tests=None, force=False,
                              questions=False, answers=str(answers_file) if answers_file else None,
                              dry_run=dry_run, output_format="text", quiet=False, verbose=0, file_config={})
    code = init.init_main(args)
    return code, [t["metadata"]["id"] for t in yaml.safe_load(suite.read_text(encoding="utf-8"))["tests"]]


def test_at_the_console_e_edits_then_offers_new_questions(tmp_path, monkeypatch, capsys):
    code, ids = _run(tmp_path, monkeypatch, ["e", "4", "d", "", ""])
    out, err = capsys.readouterr()
    assert code == 0 and ids == ["how-many-orders", "how-many-orders-follow-up-1", "how-many-orders-follow-up-2"]
    assert "[e]dit" in err and "removed=1" in out


def test_a_changed_answer_keeps_its_place(tmp_path, monkeypatch, capsys):
    code, ids = _run(tmp_path, monkeypatch, ["e", "1", "c", "1,300", "", "", ""])
    out, _err = capsys.readouterr()
    assert code == 0 and ids[0] == "how-many-orders" and len(ids) == 4
    assert "replaced=1" in out


def test_a_dry_run_edit_asks_before_writing(tmp_path, monkeypatch, capsys):
    code, ids = _run(tmp_path, monkeypatch, ["e", "4", "d", "", "", "y"], dry_run=True)
    _out, err = capsys.readouterr()
    assert code == 0 and "tell-me-a-joke" not in ids
    assert "removed=1" in err or "Write the changes" in err


def test_answers_remove_takes_ids_and_their_later_turns(tmp_path, monkeypatch):
    code, ids = _run(tmp_path, monkeypatch, answers={"tests": [], "remove": ["how-many-orders-follow-up-1"]})
    assert code == 0 and ids == ["how-many-orders", "tell-me-a-joke"]


@pytest.mark.parametrize("remove,message", [
    (["no-such-test"], "no-such-test"),
    ("tell-me-a-joke", "list"),
])
def test_answers_remove_refuses_what_it_cannot_find(tmp_path, monkeypatch, capsys, remove, message):
    code, ids = _run(tmp_path, monkeypatch, answers={"tests": [], "remove": remove})
    _out, err = capsys.readouterr()
    assert code == 2 and len(ids) == 4 and message in err


def test_remove_is_refused_in_an_answers_test_entry():
    from fab_test.scripts._data_agent_init_tests import specs_from_answers

    with pytest.raises(InitInputError, match="top level"):
        specs_from_answers({"tests": [{"query": "q", "expect": "1", "remove": True}]})
