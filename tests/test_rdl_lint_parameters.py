"""Unit tests for _rdl_lint.py's parameter rules (PRM-01, PRM-03, PRM-04,
PRM-05, PRM-07). Split out of test_rdl_lint.py (Test Module Split precedent) --
see _rdl_lint_fixtures.py for the shared XML builders.

    pytest tests/test_rdl_lint_parameters.py
"""

import pytest

from fab_test.scripts._rdl_lint import (
    _check_prm01_default_value,
    _check_prm03_parameter_count,
    _check_prm04_multivalue_nullable,
    _check_prm05_show_parameter_values,
    _check_prm07_multivalue_dax_filter,
)
from tests._rdl_lint_fixtures import data_source, dataset, parse, report, report_parameter

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


_RS_FILTER = "RSCustomDaxFilter(@Colour,EqualToCondition,[DimVehicle].[Color],String)"


def _dax_report(
    command_text: str,
    *,
    multi_value: bool = True,
    provider: str = "PBIDATASET",
    query_parameters: dict[str, str] | None = None,
    filters: str = "",
) -> str:
    """One semantic-model dataset, fed by report parameter Colour as @Colour."""
    params = {"Colour": "=Parameters!Colour.Value"} if query_parameters is None else query_parameters
    ds = dataset("Sales", "Model", command_text, query_parameters=params, filters=filters)
    return report(
        f"<DataSources>{data_source('Model', provider)}</DataSources><DataSets>{ds}</DataSets>"
        f"<ReportParameters>{report_parameter('Colour', multi_value=multi_value)}</ReportParameters>"
    )


class TestPrm07MultivalueDaxFilter:
    @pytest.mark.parametrize(
        "dax",
        [
            "EVALUATE FILTER(DimVehicle, DimVehicle[Color] = @Colour)",
            "EVALUATE FILTER(DimVehicle, DimVehicle[Color] IN {@Colour})",
            "EVALUATE SUMMARIZECOLUMNS(DimVehicle[Make], TREATAS({@Colour}, DimVehicle[Color]))",
        ],
    )
    def test_flags_a_multivalue_parameter_used_directly_in_dax(self, tmp_path, dax):
        root, namespace = parse(tmp_path, _dax_report(dax))

        findings = _check_prm07_multivalue_dax_filter(root, namespace, {})

        assert [f["object"] for f in findings] == ["Sales › @Colour"]
        assert "RSCustomDaxFilter(@Colour" in findings[0]["message"]

    @pytest.mark.parametrize(
        ("data_type", "dax_type"),
        [("Integer", "Int64"), ("Float", "Double"), ("DateTime", "DateTime"), ("Boolean", "Boolean"),
         ("String", "String"), (None, "String")],
    )
    def test_the_suggested_fix_names_the_parameters_type(self, tmp_path, data_type, dax_type):
        replacement = f"<DataType>{data_type}</DataType>" if data_type else ""
        xml = _dax_report("EVALUATE FILTER(DimVehicle, DimVehicle[Color] = @Colour)").replace(
            "<DataType>Integer</DataType>", replacement
        )
        root, namespace = parse(tmp_path, xml)

        message = _check_prm07_multivalue_dax_filter(root, namespace, {})[0]["message"]

        assert message.endswith(f"[Table].[Column],{dax_type})")

    @pytest.mark.parametrize(
        "call",
        [
            _RS_FILTER,
            _RS_FILTER.lower(),
            _RS_FILTER.replace(",String)", ", String)"),  # rendered fine in fab-test [Dev], 2026-10-10
            "RSCustomDaxFilter(@Colour,EqualToCondition,[Dim Vehicle].[Body Color],String)",
        ],
    )
    def test_rscustomdaxfilter_passes(self, tmp_path, call):
        root, namespace = parse(tmp_path, _dax_report(f"EVALUATE SUMMARIZECOLUMNS(DimVehicle[Make], {call})"))

        assert _check_prm07_multivalue_dax_filter(root, namespace, {}) == []

    @pytest.mark.parametrize(
        "call",
        [
            # Each failed to render in fab-test [Dev], 2026-10-10: "Cannot find table ." / "Failed to resolve name ."
            "RSCustomDaxFilter(@Colour,EqualToCondition, [DimVehicle].[Color],String)",
            "RSCustomDaxFilter( @Colour , EqualToCondition,[DimVehicle].[Color],String)",
            "RSCustomDaxFilter(@Colour, EqualToCondition, [DimVehicle].[Color], String)",
        ],
    )
    def test_flags_rscustomdaxfilter_written_with_spaces(self, tmp_path, call):
        root, namespace = parse(tmp_path, _dax_report(f"EVALUATE SUMMARIZECOLUMNS(DimVehicle[Make], {call})"))

        findings = _check_prm07_multivalue_dax_filter(root, namespace, {})

        assert [f["object"] for f in findings] == ["Sales › @Colour"]
        assert "spaces" in findings[0]["message"]
        assert "RSCustomDaxFilter(@Colour,EqualToCondition,[Table].[Column],Int64)" in findings[0]["message"]

    def test_a_filter_defined_as_a_var_passes(self, tmp_path):
        """The shape in github.com/kerski/paginated-reports-multivalue-example."""
        dax = (
            "DEFINE VAR _FilterX =RSCustomDaxFilter(@Colour,EqualToCondition,[DimVehicle].[Color],String) "
            "EVALUATE SUMMARIZECOLUMNS(DimVehicle[Make],_FilterX)"
        )
        root, namespace = parse(tmp_path, _dax_report(dax))

        assert _check_prm07_multivalue_dax_filter(root, namespace, {}) == []

    def test_a_single_value_parameter_passes(self, tmp_path):
        xml = _dax_report("EVALUATE FILTER(DimVehicle, DimVehicle[Color] = @Colour)", multi_value=False)
        root, namespace = parse(tmp_path, xml)

        assert _check_prm07_multivalue_dax_filter(root, namespace, {}) == []

    def test_a_relational_source_is_not_judged(self, tmp_path):
        xml = _dax_report("SELECT Make FROM DimVehicle WHERE Color IN (@Colour)", provider="SQL")
        root, namespace = parse(tmp_path, xml)

        assert _check_prm07_multivalue_dax_filter(root, namespace, {}) == []

    @pytest.mark.parametrize(
        "value",
        ["=Parameters!Colour.Value(0)", '=Join(Parameters!Colour.Value, "|")', '=JOIN(Parameters!Colour.Value,",")'],
    )
    def test_a_single_string_from_the_parameter_passes(self, tmp_path, value):
        dax = "EVALUATE FILTER(DimVehicle, PATHCONTAINS(@Colour, DimVehicle[Color]))"
        root, namespace = parse(tmp_path, _dax_report(dax, query_parameters={"Colour": value}))

        assert _check_prm07_multivalue_dax_filter(root, namespace, {}) == []

    def test_a_report_side_filter_passes(self, tmp_path):
        filters = (
            "<Filters><Filter><FilterExpression>=Fields!Color.Value</FilterExpression><Operator>In</Operator>"
            "<FilterValues><FilterValue>=Parameters!Colour.Value</FilterValue></FilterValues></Filter></Filters>"
        )
        root, namespace = parse(tmp_path, _dax_report("EVALUATE DimVehicle", query_parameters={}, filters=filters))

        assert _check_prm07_multivalue_dax_filter(root, namespace, {}) == []

    def test_rscustomdaxfilter_only_in_the_designer_state_still_fires(self, tmp_path):
        xml = _dax_report("EVALUATE FILTER(DimVehicle, DimVehicle[Color] = @Colour)").replace(
            "EVALUATE 'DecoyTable'", f"EVALUATE SUMMARIZECOLUMNS({_RS_FILTER})"
        )
        root, namespace = parse(tmp_path, xml)

        assert len(_check_prm07_multivalue_dax_filter(root, namespace, {})) == 1

    def test_matches_on_the_query_parameter_name(self, tmp_path):
        params = {"SelectedColours": "=Parameters!Colour.Value"}
        rs_filter = _RS_FILTER.replace("@Colour", "@SelectedColours")
        fires = _dax_report(
            "EVALUATE FILTER(DimVehicle, DimVehicle[Color] IN {@SelectedColours})", query_parameters=params
        )
        passes = _dax_report(f"EVALUATE SUMMARIZECOLUMNS({rs_filter})", query_parameters=params)

        findings = _check_prm07_multivalue_dax_filter(*parse(tmp_path, fires), {})

        assert [f["object"] for f in findings] == ["Sales › @SelectedColours"]
        assert _check_prm07_multivalue_dax_filter(*parse(tmp_path, passes), {}) == []

    def test_a_filter_on_another_query_parameter_does_not_cover_this_one(self, tmp_path):
        params = {"Colour": "=Parameters!Colour.Value", "ColourAlt": "=Parameters!Colour.Value"}
        dax = f"EVALUATE SUMMARIZECOLUMNS({_RS_FILTER}, TREATAS({{@ColourAlt}}, DimVehicle[Color]))"
        root, namespace = parse(tmp_path, _dax_report(dax, query_parameters=params))

        findings = _check_prm07_multivalue_dax_filter(root, namespace, {})

        assert [f["object"] for f in findings] == ["Sales › @ColourAlt"]
