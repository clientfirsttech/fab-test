"""Contract tests for the envelope-to-HTML renderer (Human-Readable Reports §3).

Scope
-----
One renderer for every analyzer, driven by the envelope. It computes no
finding of its own: every value shown traces to a field it was handed.

The two finding shapes come from `normalize_findings`, which is the same
normalization the terminal summary already used — BPA's PascalCase keys
and PBIR's lowercase keys collapse to one row shape, and pql-test's
suite/test/expected/actual is detected separately.

Always passes on any machine: pure string rendering, no analyzer invoked
and nothing written outside tmp_path.
"""

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_envelope import (
    build_envelope,
    normalize_findings,
)
from fabric_ci_cd_dataops.scripts._report_html import render_report, write_report

_BPA_FINDING = {
    "RuleName": "[Performance] Do not use floating point data types",
    "RuleID": "AVOID_FLOATING_POINT_DATA_TYPES",
    "ObjectName": "Sales[Amount]",
    "Severity": "2",
    "Category": "Performance",
}
_PBIR_FINDING = {
    "rule": "ENSURE_THEME_COLOURS",
    "severity": "warning",
    "object": "Page 1",
    "message": 'Rule "Ensure charts use theme colours" FAILED',
}
_PQL_FINDING = {
    "suite_name": "Revenue",
    "test_name": "total matches source",
    "expected": "100",
    "actual": "99",
    "passed": False,
}


def _envelope(findings=None, **overrides):
    base = {
        "analyzer": "bpa",
        "artifact_path": "Sales.SemanticModel",
        "status": "passed",
        "findings": findings if findings is not None else [],
    }
    base.update(overrides)
    return build_envelope(**base)


# --------------------------------------------------------------------------- #
# Shared normalization
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_bpa_and_pbir_findings_normalize_to_the_same_shape():
    """PascalCase and lowercase keys must not produce two different tables."""
    kind_bpa, rows_bpa = normalize_findings([_BPA_FINDING])
    kind_pbir, rows_pbir = normalize_findings([_PBIR_FINDING])

    assert kind_bpa == kind_pbir == "rules"
    assert len(rows_bpa[0]) == len(rows_pbir[0])


@pytest.mark.fab_test
def test_pql_test_findings_are_detected_as_their_own_shape():
    kind, rows = normalize_findings([_PQL_FINDING])

    assert kind == "tests"
    assert rows[0][0] == "Revenue"


@pytest.mark.fab_test
def test_rule_findings_sort_most_severe_first():
    low = {**_PBIR_FINDING, "rule": "LOW", "severity": "info"}
    high = {**_PBIR_FINDING, "rule": "HIGH", "severity": "error"}

    _kind, rows = normalize_findings([low, high])

    assert rows[0][0] == "HIGH"


@pytest.mark.fab_test
def test_no_findings_normalizes_to_an_empty_rule_table():
    kind, rows = normalize_findings([])

    assert kind == "rules"
    assert rows == []


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_report_is_self_contained():
    """No external CSS, JS, or fonts: it must open from disk and survive CI."""
    html = render_report(_envelope([_BPA_FINDING]))

    for forbidden in ("http://", "https://", "<script src", "<link "):
        assert forbidden not in html, f"external reference: {forbidden}"


@pytest.mark.fab_test
def test_report_names_the_analyzer_and_artifact():
    html = render_report(_envelope([_BPA_FINDING]))

    assert "bpa" in html
    assert "Sales.SemanticModel" in html


@pytest.mark.fab_test
def test_rule_findings_render_with_their_values():
    html = render_report(_envelope([_PBIR_FINDING]))

    assert "ENSURE_THEME_COLOURS" in html
    assert "Page 1" in html


@pytest.mark.fab_test
def test_test_findings_render_expected_and_actual():
    html = render_report(_envelope([_PQL_FINDING], analyzer="pql_test"))

    assert "Expected" in html
    assert "Actual" in html
    assert "100" in html
    assert "99" in html


@pytest.mark.fab_test
def test_a_report_with_no_findings_says_so():
    """An empty table is a worse answer than a sentence."""
    html = render_report(_envelope([]))

    assert "<table" not in html.lower() or "No findings" in html
    assert "No findings" in html


@pytest.mark.fab_test
def test_markup_in_a_finding_is_escaped():
    """A rule name or DAX expression must never inject markup."""
    hostile = {
        **_PBIR_FINDING,
        "rule": "<script>alert(1)</script>",
        "message": 'x < y && a > b "quoted"',
    }

    html = render_report(_envelope([hostile]))

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.fab_test
def test_renderer_invents_no_finding():
    """Every row traces to an input finding -- the renderer computes nothing."""
    html = render_report(_envelope([_PBIR_FINDING]))

    assert html.count("<tr") == 2, "expected exactly one header row and one data row"


@pytest.mark.fab_test
def test_render_is_deterministic():
    """Same envelope, same bytes -- no timestamps or ordering churn in the output."""
    envelope = _envelope([_BPA_FINDING, _PBIR_FINDING])

    assert render_report(envelope) == render_report(envelope)


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_write_report_creates_the_file_and_returns_its_path(tmp_path):
    target = tmp_path / "nested" / "report.html"

    written = write_report(_envelope([_BPA_FINDING]), target)

    assert written == target
    assert target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


# --------------------------------------------------------------------------- #
# The per-run index (§6)
# --------------------------------------------------------------------------- #


def _index_rows(tmp_path):
    return [
        {
            "analyzer": "bpa",
            "artifact": "Sales",
            "status": "warning",
            "errors": 0,
            "warnings": 21,
            "output_path": str(tmp_path / "bpa" / "Sales" / "envelope.json"),
            "report_path": str(tmp_path / "bpa" / "Sales" / "report.html"),
        },
        {
            "analyzer": "pql_test",
            "artifact": "Sales",
            "status": "skipped",
            "errors": 0,
            "warnings": 0,
            "output_path": str(tmp_path / "pql_test" / "Sales" / "envelope.json"),
            "report_path": None,
        },
    ]


@pytest.mark.fab_test
def test_index_totals_match_the_rows_it_was_given(tmp_path):
    """Built from the summary's own rows, so the two cannot disagree."""
    from fabric_ci_cd_dataops.scripts._report_html import render_index

    html = render_index(_index_rows(tmp_path), tmp_path)

    assert "21 warning(s)" in html
    assert "2 artifact(s)" in html


@pytest.mark.fab_test
def test_index_links_are_relative_to_the_index_location(tmp_path):
    """The page must survive being moved or downloaded as a CI artifact."""
    from fabric_ci_cd_dataops.scripts._report_html import render_index

    html = render_index(_index_rows(tmp_path), tmp_path)

    assert 'href="bpa/Sales/report.html"' in html
    assert str(tmp_path) not in html, "absolute path leaked into a link"


@pytest.mark.fab_test
def test_index_marks_a_missing_report_rather_than_linking_nothing(tmp_path):
    from fabric_ci_cd_dataops.scripts._report_html import render_index

    html = render_index(_index_rows(tmp_path), tmp_path)

    assert html.count("<a href=") == 3, "2 envelopes + 1 report expected"


@pytest.mark.fab_test
def test_write_index_returns_the_written_path(tmp_path):
    from fabric_ci_cd_dataops.scripts._report_html import write_index

    written = write_index(_index_rows(tmp_path), tmp_path)

    assert written == tmp_path / "index.html"
    assert written.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


@pytest.mark.fab_test
def test_write_report_is_utf8(tmp_path):
    """Findings carry model names with non-ASCII characters."""
    finding = {**_PBIR_FINDING, "object": "Café — Ventas"}
    target = tmp_path / "report.html"

    write_report(_envelope([finding]), target)

    assert "Café — Ventas" in target.read_text(encoding="utf-8")
