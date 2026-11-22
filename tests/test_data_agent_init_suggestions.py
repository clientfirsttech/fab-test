"""What `tests init` suggests from a Data Agent's definition (decision 14, Review 1 item 10).

Suggestions only: the person still writes every expected answer. A table the source has but the agent
leaves unselected is something the agent should decline; a figure is worth asking, a label is not.
"""

import json

import pytest

from fab_test.scripts._data_agent_init_questions import DECLINE_SUGGESTION, read_suggestions

pytestmark = pytest.mark.data_agent


def _agent(tmp_path, elements, instructions=None, source_instructions=None):
    item = tmp_path / "Sales.DataAgent"
    source = item / "Files" / "Config" / "draft" / "model"
    source.mkdir(parents=True)
    (item / ".platform").write_text(json.dumps({"config": {"logicalId": "sales-id"},
                                                "metadata": {"displayName": "Sales"}}), encoding="utf-8")
    (source.parent / "stage_config.json").write_text(json.dumps({"aiInstructions": instructions}), encoding="utf-8")
    (source / "datasource.json").write_text(json.dumps({
        "displayName": "Sales Model", "dataSourceInstructions": source_instructions, "elements": elements,
    }), encoding="utf-8")
    return item


def _table(name, selected=True, children=()):
    return {"type": "semantic_model.table", "display_name": name, "is_selected": selected, "children": list(children)}


def _measure(name, data_type="Int64", selected=True):
    return {"type": "semantic_model.measure", "display_name": name, "is_selected": selected, "data_type": data_type}


def _column(name):
    return {"type": "semantic_model.column", "display_name": name, "is_selected": True, "data_type": "String"}


def test_a_table_the_agent_leaves_out_is_a_question_it_should_decline(tmp_path):
    item = _agent(tmp_path, [_table("Orders", children=[_column("Id")]),
                             _table("Payroll", selected=False, children=[_column("Salary")])])
    found = read_suggestions(item)
    assert "How many rows are in the Payroll table?" in found.decline
    assert found.decline[-1] == DECLINE_SUGGESTION  # the generic out-of-scope question stays last
    assert "How many rows are in the Orders table?" in found.questions
    assert not set(found.questions) & set(found.decline)


def test_figures_are_suggested_and_labels_or_dates_are_not(tmp_path):
    item = _agent(tmp_path, [_table("Sales", children=[
        _measure("Total Revenue", "Decimal"), _measure("Order Count", "Int64"),
        _measure("Report Title", "String"), _measure("Now", "DateTime"), _measure("Margin", None)])])
    questions = read_suggestions(item).questions
    assert "What is the Total Revenue?" in questions and "What is the Order Count?" in questions
    assert "What is the Margin?" in questions  # no type recorded: offered
    assert "What is the Report Title?" not in questions and "What is the Now?" not in questions


def test_the_agents_own_instructions_are_shown_for_writing_questions_against(tmp_path):
    item = _agent(tmp_path, [_table("Orders", children=[_column("Id")])],
                  instructions="Answer only about orders.", source_instructions="Revenue is in EUR.")
    assert read_suggestions(item).instructions == ["Answer only about orders.", "Sales Model: Revenue is in EUR."]


def test_no_instructions_reads_as_none(tmp_path):
    item = _agent(tmp_path, [_table("Orders", children=[_column("Id")])])
    assert read_suggestions(item).instructions == []


def test_questions_names_what_to_decline_and_the_agents_instructions(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    _agent(tmp_path, [_table("Orders", children=[_column("Id")]), _table("Payroll", selected=False)],
           instructions="Answer only about orders.")
    cli = Path(sys.executable).with_name("fab-test.exe" if sys.platform == "win32" else "fab-test")
    env = {**os.environ, "FAB_TEST_ENABLE_DATA_AGENT": "1", "CI": "true"}

    def questions(*extra):
        return subprocess.run([str(cli), "data-agent", "tests", "init", "Sales", "--artifact-dir", str(tmp_path),
                               "--questions", *extra], capture_output=True, text=True, encoding="utf-8",
                              env=env, timeout=60, check=False)

    payload = json.loads(questions("--format", "json").stdout)
    assert payload["decline"] == ["How many rows are in the Payroll table?", DECLINE_SUGGESTION]
    assert payload["instructions"] == ["Answer only about orders."]
    assert payload["suggestions"][-2:] == payload["decline"]  # numbered after the questions, as `?` numbers them
    text = questions().stdout
    assert "How many rows are in the Payroll table? (the agent should decline)" in text
    assert "Answer only about orders." in text


def test_question_mark_marks_what_the_agent_should_decline():
    import io

    from fab_test.scripts._data_agent_init_tests import ask_tests

    replies, err = iter(["?", ""]), io.StringIO()
    ask_tests(["Q1?", "Off topic?"], ask=lambda _prompt: next(replies), err=err, declines={"Off topic?"})
    assert "2. Off topic? (the agent should decline)" in err.getvalue() and "1. Q1?\n" in err.getvalue()
