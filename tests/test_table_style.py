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

    def test_a_narrow_terminal_wraps_the_message_instead_of_cutting_it(self):
        message = "SELECT * FROM PieData: SELECT * fetches every column -- list only the columns the report uses"
        long = [{"rule": "DS-05", "severity": "error", "object": "DataSet1", "message": message}]

        out = findings_table(long, 80)

        assert "DS-05" in out
        assert max(len(line) for line in out.splitlines()) <= 80
        assert "..." not in out
        flat = " ".join(" ".join(line.strip("│ ").split()) for line in out.splitlines())
        for word in message.split():
            assert word in flat

    def test_a_long_object_path_is_wrapped_too(self):
        long_object = "AVeryLongDatasetName › AVeryLongFieldName_" + "x" * 40
        row = [{"rule": "QRY-02", "severity": "warning", "object": long_object, "message": "m"}]

        out = findings_table(row, 80)

        assert max(len(line) for line in out.splitlines()) <= 80
        assert "x" * 40 in "".join(out.replace("│", "").split())

    def test_no_findings_is_an_empty_string(self):
        assert findings_table([], 120) == ""


class TestEdgeCells:
    def test_numeric_looking_cells_are_not_reformatted_or_right_aligned(self):
        row = [{"rule": "R", "severity": "error", "object": "007", "message": "1e5"}]

        out = findings_table(row, 80)

        assert "007" in out
        assert "1e5" in out
        assert "100000" not in out

    def test_a_missing_severity_counts_as_an_error_and_sorts_first(self):
        rows = [
            {"rule": "B", "severity": "warning", "object": "o", "message": "m"},
            {"rule": "A", "object": "o", "message": "m"},
        ]

        out = findings_table(rows, 120)

        assert out.index("Error") < out.index("Warning")

    def test_info_sorts_after_warning(self):
        rows = [
            {"rule": "A", "severity": "info", "object": "o", "message": "m"},
            {"rule": "B", "severity": "warning", "object": "o", "message": "m"},
        ]

        out = findings_table(rows, 120)

        assert out.index("Warning") < out.index("Info")


class TestDisplayWidth:
    @staticmethod
    def _width(text: str) -> int:
        import unicodedata

        return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)

    def test_double_width_text_never_overflows_the_terminal(self):
        row = [{"rule": "DS-02", "severity": "error", "object": "データセット" * 8, "message": "漢字" * 40}]

        out = findings_table(row, 80)

        assert max(self._width(line) for line in out.splitlines()) <= 80

    def test_every_character_survives_the_wrap(self):
        message = "漢字" * 40
        row = [{"rule": "R", "severity": "error", "object": "o", "message": message}]

        out = findings_table(row, 80)

        assert "".join(out.replace("│", "").split()).count("漢字") == 40

    def test_a_long_unbroken_token_is_split_not_dropped(self):
        row = [{"rule": "R", "severity": "error", "object": "o", "message": "x" * 200}]

        out = findings_table(row, 80)

        assert "".join(out.replace("│", "").split()).count("x") == 200
