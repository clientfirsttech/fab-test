"""Findings from the AIDD review of the RDL engine and output (2026-10-01).

Each test pins one defect the review reproduced.
"""

import json
from pathlib import Path

import pytest

from fab_test.scripts._rdl_lint import (
    CHECKS,
    _check_ds02_unused_datasets,
    _check_ds05_no_select_star,
    _check_ds07_prefer_stored_procedures,
    _check_qry04_sort_in_query,
    load_rule_catalog,
)
from fab_test.scripts.invoke_rdl_lint import run_rdl_lint

from ._rdl_lint_fixtures import dataset, parse, report

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]


def _with_provider(provider: str, command_text: str) -> str:
    source = (
        '<DataSources><DataSource Name="DS1"><ConnectionProperties>'
        f"<DataProvider>{provider}</DataProvider></ConnectionProperties></DataSource></DataSources>"
    )
    return report(source + "<DataSets>" + dataset("Sales", "DS1", command_text) + "</DataSets>")


class TestOnlyRelationalProvidersAreAskedForSql:
    @pytest.mark.parametrize("provider", ["OLEDB-MD", "ESSBASE", "SAPBW", "SHAREPOINTLIST", "XML"])
    def test_ds07_ignores_a_non_sql_provider(self, tmp_path, provider):
        root, ns = parse(tmp_path, _with_provider(provider, "SELECT {[Measures].[X]} ON 0 FROM [Cube]"))

        assert _check_ds07_prefer_stored_procedures(root, ns, {}) == []

    @pytest.mark.parametrize("provider", ["OLEDB-MD", "ESSBASE"])
    def test_ds05_ignores_a_non_sql_provider(self, tmp_path, provider):
        root, ns = parse(tmp_path, _with_provider(provider, "SELECT * FROM [Cube]"))

        assert _check_ds05_no_select_star(root, ns, {}) == []

    @pytest.mark.parametrize("provider", ["SQL", "SQLAZURE", "OLEDB", "ODBC", "ORACLE"])
    def test_a_relational_provider_is_still_checked(self, tmp_path, provider):
        root, ns = parse(tmp_path, _with_provider(provider, "SELECT Amount FROM Sales"))

        assert len(_check_ds07_prefer_stored_procedures(root, ns, {})) == 1


class TestDs05Shapes:
    @pytest.mark.parametrize("sql", ["SELECT TOP 5 * FROM T", "SELECT DISTINCT * FROM T", "select\n*\nfrom T"])
    def test_select_star_variants_are_caught(self, tmp_path, sql):
        root, ns = parse(tmp_path, _with_provider("SQL", sql))

        assert len(_check_ds05_no_select_star(root, ns, {})) == 1

    @pytest.mark.parametrize("sql", ["-- select * was here\nSELECT A FROM T", "/* select * */ SELECT A FROM T"])
    def test_select_star_in_a_comment_is_not_flagged(self, tmp_path, sql):
        root, ns = parse(tmp_path, _with_provider("SQL", sql))

        assert _check_ds05_no_select_star(root, ns, {}) == []

    def test_an_unquoted_bare_dax_table_is_caught(self, tmp_path):
        root, ns = parse(tmp_path, _with_provider("PBIDATASET", "EVALUATE Sales"))

        assert len(_check_ds05_no_select_star(root, ns, {})) == 1


class TestDs02NameMatching:
    def test_a_field_that_shares_the_dataset_name_does_not_count_as_a_use(self, tmp_path):
        ds = (
            '<DataSet Name="Model"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>x</CommandText></Query></DataSet>"
        )
        body = '<Body><ReportItems><Textbox Name="T1"><Value>=Fields!Model.Value</Value></Textbox></ReportItems></Body>'
        root, ns = parse(tmp_path, report(f"<DataSets>{ds}</DataSets>" + body))

        assert [f["object"] for f in _check_ds02_unused_datasets(root, ns, {})] == ["Model"]

    @pytest.mark.parametrize("expression", ['=Sum(Fields!A.Value, "Model")', "=First(Fields!A.Value, DataSets!Model)"])
    def test_a_scope_argument_or_dataset_reference_is_a_use(self, tmp_path, expression):
        ds = (
            '<DataSet Name="Model"><Query><DataSourceName>DS1</DataSourceName>'
            "<CommandText>x</CommandText></Query></DataSet>"
        )
        body = f'<Body><ReportItems><Textbox Name="T1"><Value>{expression}</Value></Textbox></ReportItems></Body>'
        root, ns = parse(tmp_path, report(f"<DataSets>{ds}</DataSets>" + body))

        assert _check_ds02_unused_datasets(root, ns, {}) == []


class TestQry04AggregateSorts:
    def test_a_sort_by_an_aggregate_is_not_flagged(self, tmp_path):
        xml = report(
            '<Body><ReportItems><Tablix Name="T1"><TablixRowHierarchy><TablixMembers><TablixMember>'
            '<Group Name="G1" />'
            "<SortExpressions><SortExpression><Value>=Sum(Fields!A.Value)</Value></SortExpression></SortExpressions>"
            "</TablixMember></TablixMembers></TablixRowHierarchy></Tablix></ReportItems></Body>"
        )
        root, ns = parse(tmp_path, xml)

        assert _check_qry04_sort_in_query(root, ns, {}) == []


class TestCatalogLoading:
    def _write(self, tmp_path, rules):
        path = tmp_path / "rules.json"
        path.write_text(json.dumps({"rules": rules}), encoding="utf-8")
        return path

    def test_an_unknown_status_is_rejected_by_name(self, tmp_path):
        path = self._write(tmp_path, [{"id": "X-01", "status": "Active"}])

        with pytest.raises(ValueError, match="X-01.*Active"):
            load_rule_catalog(path)

    def test_a_duplicate_rule_id_is_rejected(self, tmp_path):
        path = self._write(tmp_path, [{"id": "X-01"}, {"id": "X-01", "severity": "error"}])

        with pytest.raises(ValueError, match="duplicate.*X-01"):
            load_rule_catalog(path)

    def test_a_valid_catalog_loads(self, tmp_path):
        path = self._write(tmp_path, [{"id": "X-01", "status": "planned"}, {"id": "X-02"}])

        assert [r["id"] for r in load_rule_catalog(path)] == ["X-01", "X-02"]


class _Args:
    def __init__(self, artifact, rules_path, output_path):
        self.artifact_path = str(artifact)
        self.rules_path = str(rules_path)
        self.output_path = str(output_path)
        self.verbose = False


_CLEAN = (
    '<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">'
    "<Body><ReportItems /></Body></Report>"
)


class TestWrapperRobustness:
    def test_a_malformed_rules_file_writes_an_error_envelope_and_exits_1(self, tmp_path: Path, capsys):
        artifact = tmp_path / "Sales.rdl"
        artifact.write_text(_CLEAN, encoding="utf-8")
        rules = tmp_path / "bad.json"
        rules.write_text("{bad", encoding="utf-8")
        output = tmp_path / "out" / "envelope.json"

        code = run_rdl_lint(_Args(artifact, rules, output))

        assert code == 1
        envelope = json.loads(output.read_text(encoding="utf-8"))
        assert envelope["status"] == "error"
        assert "::error::" in capsys.readouterr().err

    def test_info_only_findings_do_not_make_a_warning_run(self, tmp_path: Path):
        artifact = tmp_path / "Sales.rdl"
        artifact.write_text(_CLEAN, encoding="utf-8")
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps({"rules": [{"id": "FAKE-01", "severity": "info"}]}), encoding="utf-8")
        output = tmp_path / "env.json"
        CHECKS["FAKE-01"] = lambda *_: [{"object": "x", "message": "m"}]
        try:
            code = run_rdl_lint(_Args(artifact, rules, output))
        finally:
            del CHECKS["FAKE-01"]

        assert code == 0
        assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"

    def test_a_clean_run_message_counts_rules_checked_not_unimplemented_ones(self, tmp_path: Path):
        artifact = tmp_path / "Sales.rdl"
        artifact.write_text(_CLEAN, encoding="utf-8")
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps({"rules": [{"id": "FAKE-01"}, {"id": "FAKE-02", "disabled": True}]}), encoding="utf-8")
        output = tmp_path / "env.json"
        CHECKS["FAKE-01"] = lambda *_: []
        CHECKS["FAKE-02"] = lambda *_: []
        try:
            run_rdl_lint(_Args(artifact, rules, output))
        finally:
            del CHECKS["FAKE-01"], CHECKS["FAKE-02"]

        message = json.loads(output.read_text(encoding="utf-8"))["message"]
        assert "1 rule(s) checked" in message
        assert "not yet implemented" not in message


class TestVerboseSummaryDoesNotRepeatTheTable:
    @staticmethod
    def _envelope(root: Path, analyzer: str):
        path = root / analyzer / "Sales" / "envelope.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({
                "status": "failed",
                "findings": [{"rule": "DS-02", "severity": "error", "object": "A", "message": "m"}],
            }),
            encoding="utf-8",
        )

    def test_rdl_already_printed_its_wrapped_table_so_the_summary_skips_it(self, tmp_path: Path, capsys):
        from fab_test.scripts.fab_test_summary import _print_summary

        self._envelope(tmp_path, "rdl")

        _print_summary("rdl", [("Sales", 1)], tmp_path, "verbose")

        assert "Findings:" not in capsys.readouterr().out

    def test_another_analyzer_keeps_the_summary_findings_block(self, tmp_path: Path, capsys):
        from fab_test.scripts.fab_test_summary import _print_summary

        self._envelope(tmp_path, "pbir")

        _print_summary("pbir", [("Sales", 1)], tmp_path, "verbose")

        assert "Findings:" in capsys.readouterr().out
