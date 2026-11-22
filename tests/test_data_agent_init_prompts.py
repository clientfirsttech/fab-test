"""`tests init`: the caller's own questions, one-key match types, and follow-up chains.

Pure functions and an injected prompt loop: no console, no service, no promptfoo.
"""

import io
import json
import re
import shutil
import subprocess

import pytest

from fab_test.scripts import _data_agent_init_tests as init_tests
from fab_test.scripts._data_agent_init_tests import (
    InitInputError,
    ask_tests,
    assertion,
    default_match,
    parse_match,
)

pytestmark = pytest.mark.data_agent


# -- match types -------------------------------------------------------------


@pytest.mark.parametrize(("typed", "match"), [
    ("n", "number"), ("N", "number"), ("number", "number"),
    ("c", "contains"), ("x", "exact"), ("exact", "exact"), ("equals", "exact"),
    ("s", "starts"), ("starts with", "starts"), ("starts-with", "starts"),
    ("e", "ends"), ("ends-with", "ends"), ("p", "pattern"), ("regex", "pattern"), ("r", "refuses"),
])
def test_one_key_or_the_full_name_picks_a_match(typed, match):
    assert parse_match(typed) == match


def test_an_unknown_match_names_the_valid_keys():
    with pytest.raises(InitInputError, match=r"n number.*c contains.*r refuses"):
        parse_match("q")


@pytest.mark.parametrize(("expect", "match"), [("16,376", "number"), ("42", "number"), ("-3.5", "number"),
                                               ("yes", "contains"), ("Spider-Man", "contains")])
def test_the_default_is_number_for_a_number_and_contains_otherwise(expect, match):
    assert default_match(expect) == match


@pytest.mark.parametrize(("expect", "output", "passes"), [
    ("16,376", "There are 16,376 characters.", True),
    ("16,376", "There are 16376 characters.", True),
    ("16376", "There are 16,376 characters.", True),
    ("16,376", "There are 116,376 characters.", False),
    ("16,376", "There are 16,3760 characters.", False),
    ("3.5", "It is 3.5 hours.", True),
    ("3.5", "It is 345 hours.", False),
])
def test_number_accepts_the_figure_with_or_without_thousands_separators(expect, output, passes):
    check = assertion("number", expect)
    assert check["type"] == "regex"
    assert bool(re.search(check["value"], output)) is passes


def test_a_number_match_needs_a_number():
    with pytest.raises(InitInputError, match="number"):
        assertion("number", "lots")


def _js(check, output):
    """Evaluate the small JavaScript predicates init writes, in Python, for these fixed shapes."""
    expression = check["value"]
    text = output.strip().lower()
    needle = re.search(r'"((?:[^"\\]|\\.)*)"', expression).group(1).encode().decode("unicode_escape")
    if "startsWith" in expression:
        return text.startswith(needle)
    return re.sub(r"[.!?\s]+$", "", text).endswith(needle)


@pytest.mark.parametrize(("match", "expect", "output", "passes"), [
    ("starts", "yes", "Yes. It is.", True),
    ("starts", "yes", "No, it isn't.", False),
    ("ends", "spider-man", "The answer is Spider-Man.", True),
    ("ends", "spider-man", "Spider-Man is the answer.", False),
])
def test_starts_and_ends_with_ignore_case_and_trailing_punctuation(match, expect, output, passes):
    check = assertion(match, expect)
    assert check["type"] == "javascript"
    assert _js(check, output) is passes


def test_ends_with_escapes_quotes_in_the_written_javascript():
    check = assertion("ends", 'say "hi"')
    assert '\\"hi\\"' in check["value"]


@pytest.mark.parametrize(("match", "expect", "expected"), [
    ("contains", "Spider-Man", {"type": "icontains", "value": "Spider-Man"}),
    ("exact", "Yes.", {"type": "equals", "value": "Yes."}),
    ("pattern", r"16,?376", {"type": "regex", "value": r"16,?376"}),
])
def test_each_match_writes_its_promptfoo_assertion(match, expect, expected):
    assert assertion(match, expect) == expected


def test_refuses_checks_for_a_decline_and_needs_no_expected_answer():
    check = assertion("refuses", None)
    assert check["type"] == "javascript"
    assert "can.t" in check["value"]


@pytest.mark.skipif(not shutil.which("node"), reason="node evaluates the assertion as promptfoo does")
@pytest.mark.parametrize(("output", "passes"), [
    ("There's content here I can't work with. Try asking a new question.", True),
    ("I'm sorry, but I cannot share private account details.", True),
    ("Unable to help with that!\nAsk about the data instead.", True),
    ("Here's a classic goulash recipe.\n\n- Don't overcook the onions.", False),
    ("There are 16,376 characters. I don't have data on others.", False),
])
def test_a_refusal_is_declined_in_the_first_sentence(output, passes):
    """Decision 23: a recipe that says "don't" later is an answer, not a refusal."""
    check = assertion("refuses", None)
    script = f"const output = {json.dumps(output)};\nprocess.stdout.write(String({check['value']}));"
    result = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True,
                            encoding="utf-8", timeout=30, check=True)
    assert result.stdout == ("true" if passes else "false")


# -- specs to suite tests ----------------------------------------------------


def test_a_chain_shares_one_conversation_resetting_on_its_first_turn():
    tests = init_tests.tests_from_specs([{
        "query": "How many characters are in the data?", "expect": "16,376", "match": "n",
        "follow_ups": [{"query": "Is that more than 10,000?", "expect": "yes", "match": "s"},
                       {"query": "And fewer than 20,000?", "expect": "yes"}],
    }])

    ids = [test["metadata"]["id"] for test in tests]
    assert ids == ["how-many-characters-are-in-the-data",
                   "how-many-characters-are-in-the-data-follow-up-1",
                   "how-many-characters-are-in-the-data-follow-up-2"]
    assert tests[0]["vars"] == {"query": "How many characters are in the data?",
                                "conversation": ids[0], "reset": True}
    assert all(test["vars"]["conversation"] == ids[0] and "reset" not in test["vars"] for test in tests[1:])
    assert tests[2]["assert"] == [{"type": "icontains", "value": "yes"}]  # default: contains


def test_a_lone_question_has_no_conversation():
    (test,) = init_tests.tests_from_specs([{"query": "What is my bank balance?", "match": "r"}])
    assert test["vars"] == {"query": "What is my bank balance?"}
    assert test["description"] == "What is my bank balance?"


def test_ids_are_readable_slugs_and_two_new_questions_never_share_one():
    tests = init_tests.tests_from_specs([{"query": "Top hero?", "expect": "x"}, {"query": "Top hero!", "expect": "y"}])
    assert [test["metadata"]["id"] for test in tests] == ["top-hero", "top-hero-2"]


def test_a_long_question_gets_a_short_id():
    (test,) = init_tests.tests_from_specs([{"query": "word " * 40, "expect": "x"}])
    assert len(test["metadata"]["id"]) <= 48


def test_an_explicit_id_is_kept():
    (test,) = init_tests.tests_from_specs([{"id": "char-count", "query": "How many?", "expect": "1"}])
    assert test["metadata"]["id"] == "char-count"


# -- the answers file --------------------------------------------------------


def test_the_answers_file_takes_what_the_prompts_take():
    tests = init_tests.tests_from_answers({"tests": [
        {"query": "How many characters?", "expect": "16,376", "match": "number",
         "follow_ups": [{"query": "More than 10,000?", "expect": "yes", "match": "s"}]},
        {"query": "My bank balance?", "match": "r"},
    ]})
    assert [test["assert"][0]["type"] for test in tests] == ["regex", "javascript", "javascript"]


@pytest.mark.parametrize(("document", "message"), [
    ([], "JSON object"),
    ({"tests": "nope"}, "list"),
    ({"tests": [{"expect": "1"}]}, "query"),
    ({"tests": [{"query": "Q?"}]}, "expect"),
    ({"tests": [{"query": "Q?", "expect": "1", "match": "zzz"}]}, "n number"),
    ({"tests": [{"query": "Q?", "expect": "1", "follow_ups": "no"}]}, "follow_ups"),
    ({"count": "42"}, "tests"),
], ids=["not-object", "not-list", "no-query", "no-expect", "bad-match", "bad-follow-ups", "old-shape"])
def test_a_malformed_answers_file_says_what_to_fix(document, message):
    with pytest.raises(InitInputError, match=message):
        init_tests.tests_from_answers(document)


# -- the prompt loop -----------------------------------------------------------


def _session(*typed, suggestions=("What is the Number of Characters?", "How many rows are in MarvelFact?")):
    replies = iter(typed)
    err = io.StringIO()
    specs = ask_tests(list(suggestions), ask=lambda prompt: (err.write(prompt), next(replies))[1], err=err)
    return specs, err.getvalue()


def test_you_write_the_questions_and_follow_ups():
    specs, shown = _session(
        "How many characters are in the data?", "16,376", "",       # Enter takes number
        "Is that more than 10,000?", "yes", "s",
        "",                                                         # no more follow-ups
        "",                                                         # no more questions
    )
    assert specs == [{"query": "How many characters are in the data?", "expect": "16,376", "match": "number",
                      "follow_ups": [{"query": "Is that more than 10,000?", "expect": "yes", "match": "starts"}]}]
    assert "(Enter = number)" in shown and "(Enter = contains)" in shown


def test_enter_on_the_expected_answer_means_the_agent_should_decline():
    specs, shown = _session("What is my bank balance?", "", "", "")
    assert specs == [{"query": "What is my bank balance?", "expect": None, "match": "refuses", "follow_ups": []}]
    assert "decline" in shown


def test_question_mark_lists_suggestions_and_a_number_picks_one():
    specs, shown = _session("?", "2", "6,000", "", "", "")
    assert "1. What is the Number of Characters?" in shown
    assert specs[0]["query"] == "How many rows are in MarvelFact?"


def test_a_wrong_key_asks_again_and_keeps_the_answers_so_far():
    specs, shown = _session("Top hero?", "Spider-Man", "z", "c", "", "")
    assert "n number" in shown  # re-asked naming the keys
    assert specs == [{"query": "Top hero?", "expect": "Spider-Man", "match": "contains", "follow_ups": []}]


def test_a_number_match_on_words_asks_again():
    specs, _shown = _session("Top hero?", "Spider-Man", "n", "", "", "")
    assert specs[0]["match"] == "contains"


def test_choosing_exact_warns_that_agents_rarely_answer_word_for_word():
    _specs, shown = _session("Say yes", "Yes.", "x", "", "")
    assert "word for word" in shown


def test_enter_at_the_first_question_writes_nothing():
    specs, _shown = _session("")
    assert specs == []


# -- the whole interactive flow, as a person at a console runs it --------------------


def test_a_person_at_the_console_writes_a_chain_into_the_paired_suite(tmp_path, monkeypatch, capsys):
    import argparse
    import json

    import yaml

    from fab_test.scripts import _data_agent_init as init

    item = tmp_path / "Sales.DataAgent"
    draft = item / "Files" / "Config" / "draft" / "model"
    draft.mkdir(parents=True)
    (item / ".platform").write_text(json.dumps({"config": {"logicalId": "sales-id"},
                                                "metadata": {"displayName": "Sales"}}), encoding="utf-8")
    (draft.parent / "stage_config.json").write_text("{}", encoding="utf-8")
    (draft / "datasource.json").write_text(json.dumps({"elements": [
        {"type": "semantic_model.table", "display_name": "Orders", "is_selected": True, "children": [
            {"type": "semantic_model.measure", "display_name": "Order Count", "is_selected": True}]},
    ]}), encoding="utf-8")
    typed = iter(["?", "1", "1,204", "", "Is that more than 1,000?", "yes", "s", "", ""])
    monkeypatch.setattr("builtins.input", lambda: next(typed))
    monkeypatch.setattr(init, "can_ask", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    args = argparse.Namespace(target="Sales", artifact=None, artifact_dir=str(tmp_path), tests=None, force=False,
                              questions=False, answers=None, dry_run=False, output_format="text",
                              quiet=False, verbose=0, file_config={})

    assert init.init_main(args) == 0

    out, err = capsys.readouterr()
    assert "1. What is the Order Count?" in err  # prompts on stderr, never stdout
    assert "Question" not in out and "tests written added=2" in out
    tests = yaml.safe_load((tmp_path / "Sales.DataAgent.promptfoo.yaml").read_text(encoding="utf-8"))["tests"]
    assert [test["vars"]["query"] for test in tests] == ["What is the Order Count?", "Is that more than 1,000?"]
    assert tests[1]["vars"]["conversation"] == tests[0]["metadata"]["id"] == "what-is-the-order-count"


def test_a_long_id_ends_on_a_whole_word():
    (test,) = init_tests.tests_from_specs([{"query": "What is the current balance of my private bank account?",
                                            "match": "r"}])
    assert test["metadata"]["id"] == "what-is-the-current-balance-of-my"


def _console_init(tmp_path, monkeypatch, typed, *, dry_run):
    import argparse
    import json

    from fab_test.scripts import _data_agent_init as init

    item = tmp_path / "Sales.DataAgent"
    draft = item / "Files" / "Config" / "draft" / "model"
    draft.mkdir(parents=True)
    (item / ".platform").write_text(json.dumps({"config": {"logicalId": "sales-id"},
                                                "metadata": {"displayName": "Sales"}}), encoding="utf-8")
    (draft.parent / "stage_config.json").write_text("{}", encoding="utf-8")
    (draft / "datasource.json").write_text(json.dumps({"elements": [
        {"type": "semantic_model.table", "display_name": "Orders", "is_selected": True}]}), encoding="utf-8")
    replies = iter(typed)
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    monkeypatch.setattr(init, "can_ask", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    args = argparse.Namespace(target="Sales", artifact=None, artifact_dir=str(tmp_path), tests=None, force=False,
                              questions=False, answers=None, dry_run=dry_run, output_format="text",
                              quiet=False, verbose=0, file_config={})
    return init.init_main(args), tmp_path / "Sales.DataAgent.promptfoo.yaml"


@pytest.mark.parametrize(("keep", "written"), [("y", True), ("", False), ("n", False)])
def test_a_console_dry_run_offers_to_keep_what_you_typed(tmp_path, monkeypatch, capsys, keep, written):
    """Typed questions are work: a preview must not throw them away (the user lost two sessions)."""
    code, suite = _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", "", keep], dry_run=True)

    out, err = capsys.readouterr()
    assert code == 0
    assert "Write 1 new test to" in err and "[y/N]" in err
    assert suite.exists() is written
    assert ("tests written added=1" in out) is written
    assert "tests dry run, nothing written" in out


def test_a_console_run_without_dry_run_writes_without_asking_again(tmp_path, monkeypatch, capsys):
    code, suite = _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    assert code == 0 and suite.exists()
    assert "[y/N]" not in capsys.readouterr().err


# -- appending politely: say where, and ask about a question the suite already has ----------


_EXISTING = {"how many characters are in the data": {"id": "character-count", "summary": "regex 16,?376"}}


def _session_with(existing, *typed):
    replies = iter(typed)
    err = io.StringIO()
    specs = ask_tests([], ask=lambda prompt: (err.write(prompt), next(replies))[1], err=err, existing=existing)
    return specs, err.getvalue()


def test_a_question_already_in_the_suite_is_kept_on_enter_without_asking_its_answer():
    specs, shown = _session_with(_EXISTING, "How many characters are in the data? ", "", "")
    assert specs == []
    assert "Already in the suite as character-count, expecting regex 16,?376" in shown
    assert "[k]eep it (Enter) or [r]eplace" in shown
    assert "Expected answer" not in shown


def test_replacing_a_question_already_in_the_suite_keeps_its_id():
    specs, _shown = _session_with(_EXISTING, "how many characters are in the data", "r", "16,376", "", "", "")
    assert specs == [{"query": "how many characters are in the data", "expect": "16,376", "match": "number",
                      "follow_ups": [], "id": "character-count", "replace": True}]


def test_a_wrong_key_for_keep_or_replace_asks_again():
    specs, shown = _session_with(_EXISTING, "How many characters are in the data?", "z", "k", "")
    assert specs == [] and shown.count("[k]eep it (Enter) or [r]eplace") == 2


def test_the_answers_file_replaces_only_when_it_says_so(tmp_path, monkeypatch, capsys):
    import argparse
    import json

    import yaml

    from fab_test.scripts import _data_agent_init as init

    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)  # suite: top-order
    capsys.readouterr()
    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    for replace, expected in ((False, "kept"), (True, "replaced")):
        answers = tmp_path / "answers.json"
        answers.write_text(json.dumps({"tests": [{"query": "Top order?", "expect": "43", "replace": replace}]}),
                           encoding="utf-8")
        args = argparse.Namespace(target="Sales", artifact=None, artifact_dir=str(tmp_path), tests=None,
                                  force=False, questions=False, answers=str(answers), dry_run=False,
                                  output_format="json", quiet=False, verbose=0, file_config={}, tests_dir=None)
        assert init.init_main(args) == 0
        assert json.loads(capsys.readouterr().out)[expected] == ["top-order"]
    assert "43" in yaml.safe_load(suite.read_text(encoding="utf-8"))["tests"][0]["assert"][0]["value"]


def test_init_says_where_the_questions_go_before_the_first_one(tmp_path, monkeypatch, capsys):
    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    first = capsys.readouterr().err
    assert first.index("Writing a new suite: ") < first.index("Question 1")

    import argparse

    from fab_test.scripts import _data_agent_init as init

    replies = iter(["", "Top order?", "", ""])  # Enter adds; the question is there: Enter keeps it; done
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    args = argparse.Namespace(target="Sales", artifact=None, artifact_dir=str(tmp_path), tests=None, force=False,
                              questions=False, answers=None, dry_run=False, output_format="text",
                              quiet=False, verbose=0, file_config={}, tests_dir=None)
    assert init.init_main(args) == 0
    second = capsys.readouterr().err
    assert "has 1 test:" in second and "top-order: Top order?" in second and "[a]dd to it (Enter)" in second
    assert "--tests FILE" in second  # the way to a separate suite
    assert second.index("has 1 test:") < second.index("Question 1")


# -- add to the suite, or start it over ------------------------------------------------


def _again(tmp_path, monkeypatch, typed, *, dry_run=False, answers=None, output_format="text"):
    """Run init a second time on the suite _console_init wrote."""
    import argparse

    from fab_test.scripts import _data_agent_init as init

    replies = iter(typed)
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    args = argparse.Namespace(target="Sales", artifact=None, artifact_dir=str(tmp_path), tests=None, force=False,
                              questions=False, answers=answers, dry_run=dry_run, output_format=output_format,
                              quiet=False, verbose=0, file_config={}, tests_dir=None)
    return init.init_main(args)


def _suite_ids(tmp_path):
    import yaml

    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    return [test["metadata"]["id"] for test in yaml.safe_load(suite.read_text(encoding="utf-8"))["tests"]]


def test_enter_adds_to_the_suite(tmp_path, monkeypatch, capsys):
    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    capsys.readouterr()
    assert _again(tmp_path, monkeypatch, ["", "Top region?", "West", "", "", ""]) == 0
    err = capsys.readouterr().err
    assert "[a]dd to it (Enter) or [r]eplace all 1 test?" in err
    assert _suite_ids(tmp_path) == ["top-order", "top-region"]


def test_r_starts_the_suite_over_with_only_the_new_questions(tmp_path, monkeypatch, capsys):
    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    capsys.readouterr()
    assert _again(tmp_path, monkeypatch, ["r", "Top order?", "43", "", "", ""]) == 0
    out = capsys.readouterr().out
    assert _suite_ids(tmp_path) == ["top-order"]  # the same question, not asked keep or replace: all were dropped
    assert "removed=1" in out and "added=1" in out


def test_starting_over_with_no_new_questions_leaves_the_suite_untouched(tmp_path, monkeypatch, capsys):
    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    before = suite.read_bytes()
    assert _again(tmp_path, monkeypatch, ["r", ""]) == 0
    assert suite.read_bytes() == before


def test_a_wrong_key_for_add_or_replace_asks_again(tmp_path, monkeypatch, capsys):
    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    capsys.readouterr()
    assert _again(tmp_path, monkeypatch, ["x", "a", ""]) == 0
    err = capsys.readouterr().err
    assert err.count("[a]dd to it (Enter) or [r]eplace all 1 test?") == 2 and "a adds, r replaces" in err


def test_a_dry_run_that_starts_over_says_so_when_offering_to_write(tmp_path, monkeypatch, capsys):
    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    capsys.readouterr()
    assert _again(tmp_path, monkeypatch, ["r", "Top region?", "West", "", "", "", "y"], dry_run=True) == 0
    assert "Replace the 1 test in " in capsys.readouterr().err
    assert _suite_ids(tmp_path) == ["top-region"]


def test_the_answers_file_starts_over_with_replace_all(tmp_path, monkeypatch, capsys):
    import json

    _console_init(tmp_path, monkeypatch, ["Top order?", "42", "", "", ""], dry_run=False)
    capsys.readouterr()
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"replace_all": True, "tests": [{"query": "Top region?", "expect": "West"}]}),
                       encoding="utf-8")
    assert _again(tmp_path, monkeypatch, [], answers=str(answers), output_format="json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == ["top-order"] and payload["added"] == ["top-region"]
    assert _suite_ids(tmp_path) == ["top-region"]
