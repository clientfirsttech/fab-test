"""Unit tests for _rdl_lint.py's layout and subreport rules (LAY-01 ..
LAY-06, SUB-01, SUB-02). Split out of test_rdl_lint.py (Test Module Split
precedent) -- see _rdl_lint_fixtures.py for the shared XML builders.

    pytest tests/test_rdl_lint_layout.py
"""

import pytest

from fab_test.scripts._rdl_lint import (
    _check_lay01_body_fits_page,
    _check_lay02_avoid_total_pages,
    _check_lay03_sub01_subreport_in_tablix,
    _check_lay04_interactive_sort,
    _check_lay05_large_reports_page_breaks,
    _check_lay06_avoid_embedded_images,
    _check_sub02_subreport_count,
    build_test_results,
    run_checks,
)
from tests._rdl_lint_fixtures import parse, report, report_section

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


class TestLay01BodyFitsPage:
    def test_body_plus_margins_within_the_declared_page_width_passes(self, tmp_path):
        xml = report(report_section("6in", page_width="8.5in"))
        root, namespace = parse(tmp_path, xml)

        assert _check_lay01_body_fits_page(root, namespace, {}) == []

    def test_body_plus_margins_over_the_declared_page_width_is_flagged(self, tmp_path):
        xml = report(report_section("7in", page_width="8.5in"))
        root, namespace = parse(tmp_path, xml)

        findings = _check_lay01_body_fits_page(root, namespace, {})

        assert len(findings) == 1

    def test_falls_back_to_the_schema_default_page_width_when_omitted(self, tmp_path):
        """Real Report Builder output (PaginatedExample-WithFilter.rdl) omits
        PageWidth entirely -- 6in body + 1in + 1in margins fits the 8.5in
        Letter default with no PageWidth element at all."""
        xml = report(report_section("6in", page_width=None))
        root, namespace = parse(tmp_path, xml)

        assert _check_lay01_body_fits_page(root, namespace, {}) == []

    def test_normalizes_mixed_units_before_comparing(self, tmp_path):
        """Given page and body sizes in mixed units (in, cm, mm, pt), LAY-01
        should normalize before comparing body width plus margins against
        page width."""
        # 15cm body (~5.91in) + 20mm margins each side (~0.79in x2) = ~7.48in,
        # against a 540pt page width (7.5in) -- fits, but only once normalized.
        xml = report(report_section("15cm", page_width="540pt", left_margin="20mm", right_margin="20mm"))
        root, namespace = parse(tmp_path, xml)

        assert _check_lay01_body_fits_page(root, namespace, {}) == []

    def test_normalized_mixed_units_over_the_page_width_is_flagged(self, tmp_path):
        xml = report(report_section("20cm", page_width="360pt", left_margin="10mm", right_margin="10mm"))
        root, namespace = parse(tmp_path, xml)

        assert len(_check_lay01_body_fits_page(root, namespace, {})) == 1


class TestLay02AvoidTotalPages:
    def test_flags_an_expression_referencing_total_pages(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=Globals!TotalPages</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert len(_check_lay02_avoid_total_pages(root, namespace, {})) == 1

    def test_no_reference_passes(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=Globals!PageNumber</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_lay02_avoid_total_pages(root, namespace, {}) == []


class TestLay03Sub01SubreportInTablix:
    def test_a_subreport_nested_in_a_tablix_is_one_finding_carrying_both_ids(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixBody>'
            '<Subreport Name="Sub1"><ReportName>Child</ReportName></Subreport>'
            "</TablixBody></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        findings = _check_lay03_sub01_subreport_in_tablix(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["rule"] == "LAY-03/SUB-01"
        assert findings[0]["object"] == "T1 › Sub1"

    def test_run_checks_produces_one_finding_reported_under_both_catalog_ids(self, tmp_path):
        """End-to-end through run_checks + the catalog: one Subreport in one
        Tablix must not become two findings just because both LAY-03 and
        SUB-01 are enabled catalog rules."""
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixBody>'
            '<Subreport Name="Sub1"><ReportName>Child</ReportName></Subreport>'
            "</TablixBody></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)
        catalog = [
            {"id": "LAY-03", "severity": "error", "disabled": False},
            {"id": "SUB-01", "severity": "error", "disabled": False},
        ]

        findings = run_checks(root, namespace, catalog)

        assert len(findings) == 1
        assert findings[0]["rule"] == "LAY-03/SUB-01"

    def test_build_test_results_shows_the_finding_under_both_rows(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixBody>'
            '<Subreport Name="Sub1"><ReportName>Child</ReportName></Subreport>'
            "</TablixBody></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)
        catalog = [
            {"id": "LAY-03", "severity": "error", "disabled": False, "description": "d"},
            {"id": "SUB-01", "severity": "error", "disabled": False, "description": "d"},
        ]
        findings = run_checks(root, namespace, catalog)

        rows = build_test_results(catalog, findings, implemented={"LAY-03"})

        rows_by_rule = {row["rule"]: row for row in rows}
        assert rows_by_rule["LAY-03"]["status"] == "error"
        assert rows_by_rule["SUB-01"]["status"] == "error"
        assert rows_by_rule["SUB-01"]["object"] == "T1 › Sub1"

    def test_sub01_is_skip_with_its_own_description_when_nothing_fires(self, tmp_path):
        xml = report("<Body />")
        root, namespace = parse(tmp_path, xml)
        catalog = [
            {"id": "LAY-03", "severity": "error", "disabled": False, "description": "d1"},
            {"id": "SUB-01", "severity": "error", "disabled": False, "description": "d2"},
        ]
        findings = run_checks(root, namespace, catalog)

        rows = build_test_results(catalog, findings, implemented={"LAY-03"})

        rows_by_rule = {row["rule"]: row for row in rows}
        assert rows_by_rule["SUB-01"]["status"] == "skip"
        assert rows_by_rule["SUB-01"]["message"] == "d2"

    def test_a_subreport_outside_any_tablix_is_not_flagged(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Subreport Name="Sub1"><ReportName>Child</ReportName></Subreport></ReportItems></Body>'
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_lay03_sub01_subreport_in_tablix(root, namespace, {}) == []


class TestLay04InteractiveSort:
    def test_flags_a_textbox_with_user_sort(self, tmp_path):
        xml = report('<Body><ReportItems><Textbox Name="Tb1"><UserSort /></Textbox></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        assert len(_check_lay04_interactive_sort(root, namespace, {})) == 1

    def test_no_user_sort_passes(self, tmp_path):
        xml = report('<Body><ReportItems><Textbox Name="Tb1" /></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        assert _check_lay04_interactive_sort(root, namespace, {}) == []


class TestLay05LargeReportsPageBreaks:
    def test_flags_a_tablix_group_with_no_page_break(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers>'
            '<TablixMember><Group Name="G1" /></TablixMember>'
            "</TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert len(_check_lay05_large_reports_page_breaks(root, namespace, {})) == 1

    def test_a_configured_page_break_passes(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers>'
            '<TablixMember><Group Name="G1"><PageBreak><BreakLocation>Start</BreakLocation></PageBreak>'
            "</Group></TablixMember>"
            "</TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_lay05_large_reports_page_breaks(root, namespace, {}) == []

    def test_a_tablix_with_no_groups_is_not_flagged(self, tmp_path):
        xml = report('<Body><ReportItems><Tablix Name="T1" /></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        assert _check_lay05_large_reports_page_breaks(root, namespace, {}) == []


class TestLay06AvoidEmbeddedImages:
    def test_flags_an_embedded_images_declaration(self, tmp_path):
        xml = report('<EmbeddedImages><EmbeddedImage Name="Logo" /></EmbeddedImages><Body />')
        root, namespace = parse(tmp_path, xml)

        assert len(_check_lay06_avoid_embedded_images(root, namespace, {})) == 1

    def test_flags_an_image_with_embedded_source(self, tmp_path):
        xml = report('<Body><ReportItems><Image Name="Img1"><Source>Embedded</Source></Image></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        assert len(_check_lay06_avoid_embedded_images(root, namespace, {})) == 1

    def test_an_external_image_passes(self, tmp_path):
        xml = report('<Body><ReportItems><Image Name="Img1"><Source>External</Source></Image></ReportItems></Body>')
        root, namespace = parse(tmp_path, xml)

        assert _check_lay06_avoid_embedded_images(root, namespace, {}) == []


class TestSub02SubreportCount:
    def test_flags_50_or_more_subreports(self, tmp_path):
        subreports = "".join(
            f'<Subreport Name="S{i}"><ReportName>C{i}</ReportName></Subreport>' for i in range(50)
        )
        xml = report(f"<Body><ReportItems>{subreports}</ReportItems></Body>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_sub02_subreport_count(root, namespace, {"max_subreports": 49})

        assert len(findings) == 1

    def test_under_the_threshold_passes(self, tmp_path):
        subreports = "".join(
            f'<Subreport Name="S{i}"><ReportName>C{i}</ReportName></Subreport>' for i in range(10)
        )
        xml = report(f"<Body><ReportItems>{subreports}</ReportItems></Body>")
        root, namespace = parse(tmp_path, xml)

        assert _check_sub02_subreport_count(root, namespace, {"max_subreports": 49}) == []

    def test_uses_the_default_threshold_when_the_catalog_omits_it(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Subreport Name="S1"><ReportName>C1</ReportName></Subreport></ReportItems></Body>'
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_sub02_subreport_count(root, namespace, {}) == []
