"""Unit tests for _rdl_lint.py's accessibility rules (ACC-01, ACC-02,
ACC-03, ACC-06, ACC-08). See _rdl_lint_fixtures.py for the shared XML builders.

    pytest tests/test_rdl_lint_accessibility.py
"""

import pytest

from fab_test.scripts._rdl_checks_contrast import _check_acc06_text_contrast
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


def _text(
    color: str = "", *, background: str = "", body_background: str = "", size: str = "", bold: bool = False
) -> str:
    run_style = "".join([
        f"<Color>{color}</Color>" if color else "",
        f"<FontSize>{size}</FontSize>" if size else "",
        "<FontWeight>Bold</FontWeight>" if bold else "",
    ])
    box_style = f"<Style><BackgroundColor>{background}</BackgroundColor></Style>" if background else ""
    body_style = f"<Style><BackgroundColor>{body_background}</BackgroundColor></Style>" if body_background else ""
    return report(
        '<Body><ReportItems><Textbox Name="Tb1"><Paragraphs><Paragraph><TextRuns><TextRun>'
        f"<Value>Revenue</Value><Style>{run_style}</Style></TextRun></TextRuns></Paragraph></Paragraphs>"
        f"{box_style}</Textbox></ReportItems>{body_style}</Body>"
    )


class TestAcc06TextContrast:
    def test_flags_light_grey_text_on_the_default_white(self, tmp_path):
        root, namespace = parse(tmp_path, _text("#AAAAAA"))

        findings = _check_acc06_text_contrast(root, namespace, {})

        assert [f["object"] for f in findings] == ["Tb1"]
        assert "2.3:1" in findings[0]["message"]

    def test_the_background_is_inherited_from_the_body(self, tmp_path):
        root, namespace = parse(tmp_path, _text("White", body_background="#F0F0F0"))

        assert len(_check_acc06_text_contrast(root, namespace, {})) == 1

    def test_a_transparent_background_shows_its_container(self, tmp_path):
        root, namespace = parse(tmp_path, _text("Black", background="Transparent", body_background="Black"))

        assert len(_check_acc06_text_contrast(root, namespace, {})) == 1

    def test_report_builder_header_grey_on_white_passes(self, tmp_path):
        root, namespace = parse(tmp_path, _text("#666666", background="White"))

        assert _check_acc06_text_contrast(root, namespace, {}) == []

    def test_large_text_needs_only_three_to_one(self, tmp_path):
        large = _text("#949494", size="18pt")
        bold = _text("#949494", size="14pt", bold=True)
        small = _text("#949494", size="12pt")

        assert _check_acc06_text_contrast(*parse(tmp_path, large), {}) == []
        assert _check_acc06_text_contrast(*parse(tmp_path, bold), {}) == []
        assert len(_check_acc06_text_contrast(*parse(tmp_path, small), {})) == 1

    def test_expressions_and_unknown_colors_are_not_judged(self, tmp_path):
        expression = _text('=IIf(Fields!X.Value &lt; 0, "Red", "Black")')
        unknown = _text("MediumAquamarine", background="White")

        assert _check_acc06_text_contrast(*parse(tmp_path, expression), {}) == []
        assert _check_acc06_text_contrast(*parse(tmp_path, unknown), {}) == []

    def test_the_minimum_comes_from_the_catalog(self, tmp_path):
        root, namespace = parse(tmp_path, _text("#666666"))

        assert len(_check_acc06_text_contrast(root, namespace, {"min_contrast": 7.0})) == 1
