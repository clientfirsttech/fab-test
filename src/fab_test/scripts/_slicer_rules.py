"""Compile slicer expectations into PBIR Inspector rules (PBIR Slicer Default State epic).

Each expectation becomes one `part: Pages` rule. On the page whose display
name matches, it finds the slicers bound to the contract's table and column
(by their projection, never by visual ID) and compares what each opens with
against tokens in the exact form Power BI Desktop writes:

- selected: the `In` literals, or for a field parameter the display names in
  the filter's `valueMap` annotation (Desktop filters the hidden Fields column)
- contains: the input slicer's `Contains` literals
- range: `ComparisonKind|literal` pairs (2 is >= from, 3 is < the day after to)
- relative: `range|duration|period` from the slicer's data object

A rule returns [] when the page is elsewhere or the slicer matches, so it
passes; otherwise it returns a sentence naming the field, what the slicer
opens with, and what was expected -- PBIR Inspector puts that in the finding.
A second rule per page fails when no page has that display name, so a renamed
page can't make every expectation on it pass by finding nothing.
"""

from __future__ import annotations

import datetime
from typing import Any

from ._pbir_slicers import RELATIVE_MODES, SLICER_TYPES
from ._slicer_contract import SlicerExpectation, dax_literal

RULE_PREFIX = "CONTRACT."
_UNREADABLE = "a selection this check can't read"
_FILTER = "$.visual.objects.general[0].properties.filter.filter"
_DATA = "visual.objects.data.0.properties."


def expected_tokens(expectation: SlicerExpectation) -> list[str]:
    """What a matching slicer's selection reads as, in the rule's comparison form."""
    expected = expectation.expected
    if expectation.check == "relative":
        return [f"'{expected['range']}'|{expected['duration']}D|'{expected['period']}'"]
    if expectation.check == "range":
        bounds = []
        if "from" in expected:
            bounds.append(f"2|{dax_literal(expected['from'])}")
        if "to" in expected:
            bounds.append(f"3|{dax_literal(expected['to'] + datetime.timedelta(days=1))}")
        return bounds
    return [dax_literal(value) for value in expected]


def compile_rules(expectations: list[SlicerExpectation]) -> list[dict[str, Any]]:
    """The PBIR Inspector rules for a contract's (already calendar-resolved) expectations."""
    pages = sorted({e.page for e in expectations})
    return [_slicer_rule(e) for e in expectations] + [_page_rule(page) for page in pages]


def _field(e: SlicerExpectation) -> str:
    return f"'{e.table}'[{e.column}]"


def _describe_expected(e: SlicerExpectation) -> str:
    if e.check in ("selected", "contains"):
        return ", ".join(str(v) for v in e.expected) or "no selection"
    if e.check == "range":
        return f"{e.expected.get('from', 'the earliest date')} to {e.expected.get('to', 'the latest date')}"
    return f"{e.expected['range']} {e.expected['duration']} {e.expected['period']}"


def _slicer_rule(e: SlicerExpectation) -> dict[str, Any]:
    bound = "visual.query.queryState.Values.projections.0.field.Column."
    slicers = {"filter": [{"part": "Visuals"}, {"and": [
        {"in": [{"var": "visual.visualType"}, list(SLICER_TYPES)]},
        {"==": [{"var": bound + "Expression.SourceRef.Entity"}, e.table]},
        {"==": [{"var": bound + "Property"}, e.column]},
    ]}]}
    actual, matches = _comparison(e)
    expected_text = _describe_expected(e)
    mismatches = {"map": [
        {"filter": [slicers, {"!": [matches]}]},
        {"cat": [f"{_field(e)} opens with [", actual, f"]; the contract expects {expected_text}"]},
    ]}
    missing = [f"no slicer bound to {_field(e)} on page '{e.page}'"]
    return {
        "id": f"{RULE_PREFIX}{e.rule_id}",
        "name": f"{e.page}: {_field(e)} opens with {expected_text}",
        "description": f"Slicer default from the contract rule {e.rule_id}.",
        "logType": e.severity,
        "disabled": False,
        "part": "Pages",
        "test": [
            {"if": [
                {"!=": [{"var": "displayName"}, e.page]}, [],
                {"==": [{"count": [slicers]}, 0]}, missing,
                mismatches,
            ]},
            {},
            [],
        ],
    }


def _comparison(e: SlicerExpectation) -> tuple[dict, dict]:
    """(what the slicer opens with, as text; whether it matches) as JSON Logic.

    Every check requires the one filter row shape it reads, so a selection in
    any other shape ("all except", several columns) is a mismatch reported as
    unreadable -- never an empty list that happens to equal ``[]``.
    """
    tokens = expected_tokens(e)
    rows = {"count": [{"path": f"{_FILTER}.Where[*]"}]}
    no_rows = {"==": [rows, 0]}
    one_row = {"==": [rows, 1]}
    if e.check == "relative":
        actual = {"cat": [{"var": _DATA + "relativeRange.expr.Literal.Value"}, "|",
                          {"var": _DATA + "relativeDuration.expr.Literal.Value"}, "|",
                          {"var": _DATA + "relativePeriod.expr.Literal.Value"}]}
        relative = {"and": [{"in": [{"var": _DATA + "mode.expr.Literal.Value"}, list(RELATIVE_MODES)]}, one_row,
                            {">": [{"count": [{"path": f"{_FILTER}..DateSpan"}]}, 0]}]}
        shown = {"if": [no_rows, "no selection", relative, actual, _UNREADABLE]}
        return shown, {"and": [relative, {"==": [actual, tokens[0]]}]}
    if e.check == "range":
        pairs = {"map": [{"path": f"{_FILTER}..Comparison"},
                         {"cat": [{"var": "ComparisonKind"}, "|", {"var": "Right.Literal.Value"}]}]}
        return _shown(no_rows, {"strjoin": [pairs, ", "]}), {"and": [one_row, {"equalsets": [pairs, tokens]}]}
    if e.check == "contains":
        values = {"path": f"{_FILTER}..Contains.Right.Literal.Value"}
        return _shown(no_rows, {"strjoin": [values, ", "]}), _either_empty(tokens, no_rows, {
            "and": [one_row, {"equalsets": [values, tokens]}]})
    plain = {"and": [one_row,
                     {"==": [{"count": [{"path": f"{_FILTER}.Where[*].Condition.In"}]}, 1]},
                     {"==": [{"count": [{"path": f"{_FILTER}.Where[*].Condition.In.Expressions[*]"}]}, 1]}]}
    literals = {"path": f"{_FILTER}.Where[*].Condition.In.Values[*][0].Literal.Value"}
    names = {"path": f"{_FILTER}.Where[*].Annotations.filterExpressionMetadata.valueMap[*]['0']"}
    is_parameter = {">": [{"count": [names]}, 0]}
    values = {"if": [is_parameter, {"strjoin": [names, ", "]}, {"strjoin": [literals, ", "]}]}
    shown = {"if": [no_rows, "no selection", plain, values, _UNREADABLE]}
    display = [str(v) for v in e.expected]
    same = {"if": [is_parameter, {"equalsets": [names, display]}, {"equalsets": [literals, tokens]}]}
    return shown, _either_empty(tokens, no_rows, {"and": [plain, same]})


def _shown(no_rows: dict, values: dict) -> dict:
    return {"if": [no_rows, "no selection", values]}


def _either_empty(tokens: list[str], no_rows: dict, matches: dict) -> dict:
    """An empty expectation means the slicer has no filter at all, whatever shape it would take."""
    return no_rows if not tokens else matches


def _page_rule(page: str) -> dict[str, Any]:
    return {
        "id": f"{RULE_PREFIX}page.{page}",
        "name": f"The contract's page '{page}' exists",
        "description": "A slicer contract names this page; a renamed or deleted page would otherwise pass unseen.",
        "logType": "error",
        "disabled": False,
        "test": [
            {"in": [page, {"map": [{"part": "Pages"}, {"var": "displayName"}]}]},
            {},
            True,
        ],
    }
