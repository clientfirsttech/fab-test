"""Unit tests for _rdl_lint.py's parameter rules (PRM-01, PRM-03, PRM-04,
PRM-05). Split out of test_rdl_lint.py (Test Module Split precedent) --
see _rdl_lint_fixtures.py for the shared XML builders.

    pytest tests/test_rdl_lint_parameters.py
"""

import pytest

from fab_test.scripts._rdl_lint import (
    _check_prm01_default_value,
    _check_prm03_parameter_count,
    _check_prm04_multivalue_nullable,
    _check_prm05_show_parameter_values,
)
from tests._rdl_lint_fixtures import parse, report, report_parameter

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


class TestPrm01DefaultValue:
    def test_flags_a_parameter_with_no_default(self, tmp_path):
        param = report_parameter("Region", default=False)
        xml = report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_prm01_default_value(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Region"

    def test_a_parameter_with_a_default_passes(self, tmp_path):
        param = report_parameter("Region", default=True)
        xml = report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        assert _check_prm01_default_value(root, namespace, {}) == []


class TestPrm03ParameterCount:
    def test_flags_separate_year_month_day_parameters_under_the_threshold(self, tmp_path):
        """Fires even when the total count is under max_parameters -- the
        anti-pattern is the date decomposition, not the raw count."""
        params = "".join(report_parameter(n) for n in ("Year", "Month", "Day"))
        xml = report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_prm03_parameter_count(root, namespace, {"max_parameters": 5})

        assert len(findings) == 1
        assert "DateTime" in findings[0]["message"]

    def test_unrelated_parameters_under_the_threshold_pass(self, tmp_path):
        params = "".join(report_parameter(n) for n in ("Region", "Product"))
        xml = report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        assert _check_prm03_parameter_count(root, namespace, {"max_parameters": 5}) == []

    def test_flags_a_count_over_the_catalog_threshold(self, tmp_path):
        params = "".join(report_parameter(f"P{i}") for i in range(6))
        xml = report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_prm03_parameter_count(root, namespace, {"max_parameters": 5})

        assert any("threshold" in f["message"] for f in findings)

    def test_uses_the_default_threshold_when_the_catalog_omits_it(self, tmp_path):
        params = "".join(report_parameter(f"P{i}") for i in range(3))
        xml = report(f"<ReportParameters>{params}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        assert _check_prm03_parameter_count(root, namespace, {}) == []


class TestPrm04MultivalueNullable:
    def test_flags_multivalue_with_nullable(self, tmp_path):
        param = report_parameter("Region", multi_value=True, nullable=True)
        xml = report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        findings = _check_prm04_multivalue_nullable(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Region"

    def test_multivalue_with_allow_blank_is_not_flagged(self, tmp_path):
        param = report_parameter("Region", multi_value=True, allow_blank=True)
        xml = report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        assert _check_prm04_multivalue_nullable(root, namespace, {}) == []

    def test_multivalue_alone_is_not_flagged(self, tmp_path):
        param = report_parameter("Region", multi_value=True)
        xml = report(f"<ReportParameters>{param}</ReportParameters>")
        root, namespace = parse(tmp_path, xml)

        assert _check_prm04_multivalue_nullable(root, namespace, {}) == []


class TestPrm05ShowParameterValues:
    def test_flags_a_parameter_never_displayed(self, tmp_path):
        param = report_parameter("Region")
        xml = report(f"<ReportParameters>{param}</ReportParameters><Body />")
        root, namespace = parse(tmp_path, xml)

        findings = _check_prm05_show_parameter_values(root, namespace, {})

        assert len(findings) == 1
        assert findings[0]["object"] == "Region"

    def test_a_value_reference_counts_as_displayed(self, tmp_path):
        param = report_parameter("Region")
        xml = report(
            f"<ReportParameters>{param}</ReportParameters>"
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=Parameters!Region.Value</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_prm05_show_parameter_values(root, namespace, {}) == []

    def test_a_label_reference_also_counts_as_displayed(self, tmp_path):
        """Given a parameter referenced as Parameters!X.Label rather than
        .Value in a textbox, PRM-05 should count it as displayed."""
        param = report_parameter("Region")
        xml = report(
            f"<ReportParameters>{param}</ReportParameters>"
            '<Body><ReportItems><Textbox Name="Tb1">'
            "<Value>=Parameters!Region.Label</Value></Textbox></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        assert _check_prm05_show_parameter_values(root, namespace, {}) == []
