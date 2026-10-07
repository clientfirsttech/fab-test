"""Unit tests for _rdl_lint.py's accessibility rules (ACC-01, ACC-02,
ACC-03, ACC-08). See _rdl_lint_fixtures.py for the shared XML builders.

    pytest tests/test_rdl_lint_accessibility.py
"""

import pytest

from fab_test.scripts._rdl_lint import (
    _check_acc01_alt_text,
    _check_acc02_chart_alt_text_quality,
    _check_acc03_table_caption,
    _check_acc08_html_link_alt_text,
)
from tests._rdl_lint_fixtures import parse, report

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


class TestAcc01AltText:
    def test_flags_an_image_with_no_tooltip(self, tmp_path):
        xml = report('<Body><ReportItems><Image Name="Img1" /></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        findings = _check_acc01_alt_text(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Img1"

    def test_a_literal_tooltip_passes(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Image Name="Img1"><ToolTip>Company logo</ToolTip></Image></ReportItems></Body>'
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_acc01_alt_text(root, namespace, {}) == []

    def test_an_expression_tooltip_counts_as_present(self, tmp_path):
        """Given a ToolTip that is an expression (=...), ACC-01 should treat
        it as present."""
        xml = report(
            '<Body><ReportItems><Chart Name="Chart1">'
            "<ToolTip>=\"Sales for \" &amp; Fields!Region.Value</ToolTip>"
            "</Chart></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_acc01_alt_text(root, namespace, {}) == []

    def test_a_tablix_with_no_tooltip_is_not_flagged_here(self, tmp_path):
        """Given a Tablix with no ToolTip, should report ACC-03 only, not
        ACC-01 as well."""
        xml = report('<Body><ReportItems><Tablix Name="T1" /></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        assert _check_acc01_alt_text(root, namespace, {}) == []


class TestAcc02ChartAltTextQuality:
    def test_flags_a_default_placeholder_name(self, tmp_path):
        """Given a chart ToolTip equal to a default like Chart1, ACC-02
        should flag it as a placeholder rather than as missing."""
        xml = report('<Body><ReportItems><Chart Name="Chart1"><ToolTip>Chart1</ToolTip></Chart></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        findings = _check_acc02_chart_alt_text_quality(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Chart1"

    def test_flags_a_tooltip_equal_to_the_chart_own_name(self, tmp_path):
        """Given a chart ToolTip equal to the chart's own Name, ACC-02
        should flag it as a placeholder."""
        xml = report(
            '<Body><ReportItems><Chart Name="SalesByRegion">'
            "<ToolTip>SalesByRegion</ToolTip></Chart></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_acc02_chart_alt_text_quality(root, namespace, {})

        assert len(findings) == 1

    def test_a_descriptive_tooltip_passes(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Chart Name="Chart1">'
            "<ToolTip>Monthly sales trend by region</ToolTip>"
            "</Chart></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_acc02_chart_alt_text_quality(root, namespace, {}) == []

    def test_an_expression_tooltip_is_not_judged_for_wording(self, tmp_path):
        """Given a ToolTip that is an expression (=...), ACC-02 should not
        judge its wording -- even if it would look like a placeholder as
        literal text."""
        xml = report(
            '<Body><ReportItems><Chart Name="Chart1">'
            "<ToolTip>=Fields!ChartName.Value</ToolTip></Chart></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_acc02_chart_alt_text_quality(root, namespace, {}) == []

    def test_a_missing_tooltip_is_not_this_rule_concern(self, tmp_path):
        """Missing entirely is ACC-01's finding, not ACC-02's."""
        xml = report('<Body><ReportItems><Chart Name="Chart1" /></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        assert _check_acc02_chart_alt_text_quality(root, namespace, {}) == []


class TestAcc03TableCaption:
    def test_flags_a_tablix_with_no_tooltip(self, tmp_path):
        xml = report('<Body><ReportItems><Tablix Name="T1" /></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        findings = _check_acc03_table_caption(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "T1"

    def test_a_tablix_with_a_tooltip_passes(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1">'
            "<ToolTip>Sales by region and month</ToolTip></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_acc03_table_caption(root, namespace, {}) == []


class TestAcc08HtmlLinkAltText:
    def test_flags_an_html_text_run_with_no_tooltip(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1"><Paragraphs><Paragraph><TextRuns>'
            '<TextRun><Value>Click here</Value><MarkupType>HTML</MarkupType></TextRun>'
            "</TextRuns></Paragraph></Paragraphs></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_acc08_html_link_alt_text(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Tb1"

    def test_an_html_text_run_with_a_tooltip_passes(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1"><ToolTip>Opens the sales dashboard</ToolTip>'
            '<Paragraphs><Paragraph><TextRuns>'
            '<TextRun><Value>Click here</Value><MarkupType>HTML</MarkupType></TextRun>'
            "</TextRuns></Paragraph></Paragraphs></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_acc08_html_link_alt_text(root, namespace, {}) == []

    def test_a_plain_text_run_is_not_flagged(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1"><Paragraphs><Paragraph><TextRuns>'
            "<TextRun><Value>Plain text</Value></TextRun>"
            "</TextRuns></Paragraph></Paragraphs></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_acc08_html_link_alt_text(root, namespace, {}) == []
