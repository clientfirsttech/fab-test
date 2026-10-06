"""A finding must say where the problem is and what it saw, not only a leaf name.

The message alone is what a CI annotation shows, so each of these puts the
offending fragment in it (DS-02 already did). See the RDL Finding Clarity epic.
"""

import pytest

from fab_test.scripts._rdl_lint import (
    _check_acc01_alt_text,
    _check_acc03_table_caption,
    _check_ds05_no_select_star,
    _check_ds07_prefer_stored_procedures,
    _check_lay02_avoid_total_pages,
    _check_lay04_interactive_sort,
    _check_qry01_filter_in_query,
    _check_qry02_no_calculated_fields,
    _check_qry04_sort_in_query,
    _check_qry05_convert_types_in_query,
    _check_qry06_join_in_query,
)

from ._rdl_lint_fixtures import dataset, parse, report

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


def _sql_report(command_text: str, **kw) -> str:
    source = (
        '<DataSources><DataSource Name="DS1"><ConnectionProperties><DataProvider>SQL</DataProvider>'
        "</ConnectionProperties></DataSource></DataSources>"
    )
    return report(source + "<DataSets>" + dataset("Sales", "DS1", command_text, **kw) + "</DataSets>")


class TestQry02:
    def test_object_is_dataset_then_field_and_message_quotes_the_expression(self, tmp_path):
        ds = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            '<Fields><Field Name="Test"><Value>=Split(Fields!page_id.Value,"/")</Value></Field></Fields>'
            "</DataSet>"
        )
        root, namespace = parse(tmp_path, report(f"<DataSets>{ds}</DataSets>"))

        (finding,) = _check_qry02_no_calculated_fields(root, namespace, {})

        assert finding["object"] == "Sales › Test"
        assert 'Split(Fields!page_id.Value,"/")' in finding["message"]

    def test_a_very_long_expression_is_cut_in_the_message(self, tmp_path):
        ds = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            f'<Fields><Field Name="Big"><Value>={"x" * 500}</Value></Field></Fields></DataSet>'
        )
        root, namespace = parse(tmp_path, report(f"<DataSets>{ds}</DataSets>"))

        (finding,) = _check_qry02_no_calculated_fields(root, namespace, {})

        assert len(finding["message"]) < 200


class TestDs05:
    def test_sql_message_quotes_the_query(self, tmp_path):
        root, namespace = parse(tmp_path, _sql_report("SELECT *\n   FROM PieData"))

        (finding,) = _check_ds05_no_select_star(root, namespace, {})

        assert finding["object"] == "Sales"
        assert "SELECT * FROM PieData" in finding["message"]

    def test_dax_message_quotes_the_evaluate(self, tmp_path):
        source = (
            '<DataSources><DataSource Name="DS1"><ConnectionProperties><DataProvider>PBIDATASET</DataProvider>'
            "</ConnectionProperties></DataSource></DataSources>"
        )
        xml = report(source + "<DataSets>" + dataset("Sales", "DS1", "EVALUATE 'Sales'") + "</DataSets>")
        root, namespace = parse(tmp_path, xml)

        (finding,) = _check_ds05_no_select_star(root, namespace, {})

        assert "EVALUATE 'Sales'" in finding["message"]


class TestDs07:
    def test_message_quotes_the_inline_query(self, tmp_path):
        root, namespace = parse(tmp_path, _sql_report("SELECT Amount FROM Sales"))

        (finding,) = _check_ds07_prefer_stored_procedures(root, namespace, {})

        assert "SELECT Amount FROM Sales" in finding["message"]


class TestQry01:
    def test_dataset_filter_message_quotes_the_expression(self, tmp_path):
        ds = (
            '<DataSet Name="Sales"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>EVALUATE 'T'</CommandText></Query>"
            "<Filters><Filter><FilterExpression>=Fields!Region.Value</FilterExpression></Filter></Filters>"
            "</DataSet>"
        )
        root, namespace = parse(tmp_path, report(f"<DataSets>{ds}</DataSets>"))

        (finding,) = _check_qry01_filter_in_query(root, namespace, {})

        assert finding["object"] == "Sales"
        assert "=Fields!Region.Value" in finding["message"]

    def test_tablix_filter_message_quotes_the_expression(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1">'
            "<Filters><Filter><FilterExpression>=Fields!Year.Value</FilterExpression></Filter></Filters>"
            "</Tablix></ReportItems></Body>"
        )
        root, namespace = parse(tmp_path, xml)

        (finding,) = _check_qry01_filter_in_query(root, namespace, {})

        assert "=Fields!Year.Value" in finding["message"]


def _in_tablix(inner: str, tablix: str = "T1") -> str:
    return report(
        f'<Body><ReportItems><Tablix Name="{tablix}"><TablixBody><TablixRows><TablixRow><TablixCells>'
        f"<TablixCell><CellContents>{inner}</CellContents></TablixCell>"
        "</TablixCells></TablixRow></TablixRows></TablixBody></Tablix></ReportItems></Body>"
    )


def _textbox(name: str, expression: str, extra: str = "") -> str:
    return (
        f'<Textbox Name="{name}">{extra}<Paragraphs><Paragraph><TextRuns><TextRun>'
        f"<Value>{expression}</Value></TextRun></TextRuns></Paragraph></Paragraphs></Textbox>"
    )


class TestLocationPath:
    """An item nested in another named item is reported as Outer › Inner."""

    def test_lay02_names_the_textbox_and_quotes_the_expression(self, tmp_path):
        root, ns = parse(tmp_path, _in_tablix(_textbox("Tb1", '="Page " &amp; Globals!TotalPages')))

        (finding,) = _check_lay02_avoid_total_pages(root, ns, {})

        assert finding["object"] == "T1 › Tb1"
        assert "Globals!TotalPages" in finding["message"]

    def test_qry06_names_the_textbox_and_quotes_the_lookup(self, tmp_path):
        expr = '=Lookup(Fields!A.Value, Fields!B.Value, Fields!C.Value, "Other")'
        root, ns = parse(tmp_path, _in_tablix(_textbox("Tb1", expr)))

        (finding,) = _check_qry06_join_in_query(root, ns, {})

        assert finding["object"] == "T1 › Tb1"
        assert "Lookup(Fields!A.Value" in finding["message"]

    def test_lay04_names_the_nested_textbox(self, tmp_path):
        root, ns = parse(tmp_path, _in_tablix(_textbox("Tb1", "x", "<UserSort/>")))

        (finding,) = _check_lay04_interactive_sort(root, ns, {})

        assert finding["object"] == "T1 › Tb1"

    def test_acc01_names_the_nested_image(self, tmp_path):
        root, ns = parse(tmp_path, _in_tablix('<Image Name="Img1"><Source>External</Source></Image>'))

        (finding,) = _check_acc01_alt_text(root, ns, {})

        assert finding["object"] == "T1 › Img1"

    def test_a_top_level_item_keeps_its_plain_name(self, tmp_path):
        xml = report('<Body><ReportItems><Image Name="Img1"><Source>External</Source></Image></ReportItems></Body>')
        root, ns = parse(tmp_path, xml)

        (finding,) = _check_acc01_alt_text(root, ns, {})

        assert finding["object"] == "Img1"

    def test_an_unnamed_item_falls_back_to_its_element_name_not_a_question_mark(self, tmp_path):
        xml = report("<Body><ReportItems><Tablix><TablixBody /></Tablix></ReportItems></Body>")
        root, ns = parse(tmp_path, xml)

        (finding,) = _check_acc03_table_caption(root, ns, {})

        assert finding["object"] == "Tablix"


class TestQry04RealShape:
    """Report Builder writes SortExpressions as a sibling of Group inside
    TablixMember, and also directly under Tablix -- not inside Group."""

    def test_member_sort_is_flagged_with_the_group_path_and_expression(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers><TablixMember>'
            '<Group Name="PieID" />'
            "<SortExpressions><SortExpression><Value>=Fields!PieID.Value</Value></SortExpression></SortExpressions>"
            "</TablixMember></TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, ns = parse(tmp_path, xml)

        (finding,) = _check_qry04_sort_in_query(root, ns, {})

        assert finding["object"] == "T1 › PieID"
        assert "=Fields!PieID.Value" in finding["message"]

    def test_a_tablix_level_sort_is_flagged_on_the_tablix(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><DataSetName>DataSet1</DataSetName>'
            "<SortExpressions><SortExpression><Value>=Fields!PieName.Value</Value></SortExpression></SortExpressions>"
            "</Tablix></ReportItems></Body>"
        )
        root, ns = parse(tmp_path, xml)

        (finding,) = _check_qry04_sort_in_query(root, ns, {})

        assert finding["object"] == "T1"
        assert "=Fields!PieName.Value" in finding["message"]

    def test_the_real_fixture_trips_qry04(self):
        from pathlib import Path

        from fab_test.scripts._rdl_lint import parse_rdl

        fixture = Path(__file__).resolve().parent.parent / "fabric-artifacts" / "rdl" / "QRY-04.rdl"
        root, ns = parse_rdl(fixture)

        assert _check_qry04_sort_in_query(root, ns, {})


class TestQry05:
    def test_message_says_how_many_times(self, tmp_path):
        xml = report(
            "<Body><ReportItems>"
            + _textbox("A", "=CDate(Fields!D.Value)")
            + _textbox("B", "=CDate(Fields!D.Value)")
            + "</ReportItems></Body>"
        )
        root, ns = parse(tmp_path, xml)

        (finding,) = _check_qry05_convert_types_in_query(root, ns, {})

        assert "2 times" in finding["message"]
