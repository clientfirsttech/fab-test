"""The shared findings table every rule-shaped analyzer prints at --verbose."""

import pytest

from fab_test.scripts._table_style import TABLE_FORMAT, findings_table, truncate

pytestmark = pytest.mark.fab_test

_FINDINGS = [
    {"rule": "QRY-02", "severity": "warning", "object": "DataSet1 › Test", "message": "calculated field"},
    {"rule": "DS-05", "severity": "error", "object": "DataSet1", "message": "SELECT * FROM PieData"},
    {"rule": "DS-02", "severity": "error", "object": "Alpha", "message": "unused"},
]


class TestTruncate:
    def test_short_text_is_untouched(self):
        assert truncate("abc", 10) == "abc"

    def test_long_text_ends_in_an_ellipsis_at_the_width(self):
        assert truncate("abcdefghij", 8) == "abcde..."

    def test_newlines_are_flattened(self):
        assert truncate("a\nb\r", 10) == "a b"


class TestFindingsTable:
    def test_has_the_four_columns_in_the_house_format(self):
        lines = findings_table(_FINDINGS, 120).splitlines()

        assert TABLE_FORMAT == "rounded_outline"
        assert lines[0].startswith("╭")
        header = lines[1]
        assert header.index("Rule") < header.index("Severity") < header.index("Object") < header.index("Message")

    def test_sorts_errors_first_then_rule_then_object(self):
        out = findings_table(_FINDINGS, 120)

        assert out.index("DS-02") < out.index("DS-05") < out.index("QRY-02")

    def test_capitalizes_severity(self):
        out = findings_table(_FINDINGS, 120)

        assert "Error" in out
        assert "Warning" in out

    def test_a_narrow_terminal_truncates_the_message_not_the_rule(self):
        long = [{"rule": "DS-05", "severity": "error", "object": "DataSet1", "message": "x" * 300}]

        out = findings_table(long, 80)

        assert "DS-05" in out
        assert max(len(line) for line in out.splitlines()) <= 80
        assert "..." in out

    def test_no_findings_is_an_empty_string(self):
        assert findings_table([], 120) == ""
