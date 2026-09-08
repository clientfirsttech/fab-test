"""Contract tests for BPA's full test-results list (HTML Report Format §3).

Scope
-----
TE2's TRX native output already records every rule evaluated -- passed and
failed -- as a `<UnitTestResult>`. Historically only failures made it past
`_parse_bpa_native_output` into `findings`, so a passing run rendered as an
empty report with no evidence anything ran. `test_results` carries every
row (with a pass/warning/error status) so the report can show the whole
list and let the reader filter down to failures, without changing what
`findings` means to the callers that already read it (exit codes, the
terminal table, CI gating).

Always passes on any machine: pure XML parsing, no Tabular Editor invoked.
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from fab_test.scripts.invoke_tabular_editor_bpa import run_bpa

_TRX = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<TestRun id="abc" name="model" runUser="user"'
    ' xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">\n'
    '  <ResultSummary outcome="Failed">\n'
    '    <Counters total="2" executed="2" passed="1" failed="1" />\n'
    "  </ResultSummary>\n"
    "  <TestDefinitions>\n"
    '    <UnitTest name="Avoid bi-directional relationships" id="2">\n'
    "      <Properties>\n"
    "        <Property><Key>RuleID</Key><Value>PERF_01</Value></Property>\n"
    "        <Property><Key>Severity</Key><Value>2</Value></Property>\n"
    "        <Property><Key>Category</Key><Value>Performance</Value></Property>\n"
    "      </Properties>\n"
    "    </UnitTest>\n"
    '    <UnitTest name="Add descriptions to measures" id="4">\n'
    "      <Properties>\n"
    "        <Property><Key>RuleID</Key><Value>MAINT_02</Value></Property>\n"
    "        <Property><Key>Severity</Key><Value>3</Value></Property>\n"
    "        <Property><Key>Category</Key><Value>Maintenance</Value></Property>\n"
    "      </Properties>\n"
    "    </UnitTest>\n"
    "  </TestDefinitions>\n"
    "  <Results>\n"
    '    <UnitTestResult testId="2" testName="Avoid bi-directional relationships"'
    ' outcome="Passed"><Output /></UnitTestResult>\n'
    '    <UnitTestResult testId="4" testName="Add descriptions to measures"'
    ' outcome="Failed">\n'
    "      <Output><ErrorInfo>\n"
    "        <Message>1 object(s) in violation of rule</Message>\n"
    "        <StackTrace>Objects in violation:\n"
    "  [Total Sales] (Measure)</StackTrace>\n"
    "      </ErrorInfo></Output>\n"
    "    </UnitTestResult>\n"
    "  </Results>\n"
    "</TestRun>"
)

_ALL_PASSED_TRX = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<TestRun id="abc" name="model" runUser="user"'
    ' xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">\n'
    '  <ResultSummary outcome="Passed">\n'
    '    <Counters total="1" executed="1" passed="1" failed="0" />\n'
    "  </ResultSummary>\n"
    "  <TestDefinitions>\n"
    '    <UnitTest name="Avoid bi-directional relationships" id="2">\n'
    "      <Properties>\n"
    "        <Property><Key>RuleID</Key><Value>PERF_01</Value></Property>\n"
    "        <Property><Key>Severity</Key><Value>2</Value></Property>\n"
    "        <Property><Key>Category</Key><Value>Performance</Value></Property>\n"
    "      </Properties>\n"
    "    </UnitTest>\n"
    "  </TestDefinitions>\n"
    "  <Results>\n"
    '    <UnitTestResult testId="2" testName="Avoid bi-directional relationships"'
    ' outcome="Passed"><Output /></UnitTestResult>\n'
    "  </Results>\n"
    "</TestRun>"
)


_TRX_TABLE_AND_RELATIONSHIP_OBJECTS = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<TestRun id="abc" name="model" runUser="user"'
    ' xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010">\n'
    '  <ResultSummary outcome="Failed">\n'
    '    <Counters total="2" executed="2" passed="0" failed="2" />\n'
    "  </ResultSummary>\n"
    "  <TestDefinitions>\n"
    '    <UnitTest name="Ensure tables have relationships" id="1">\n'
    "      <Properties>\n"
    "        <Property><Key>RuleID</Key><Value>MAINT_01</Value></Property>\n"
    "        <Property><Key>Severity</Key><Value>2</Value></Property>\n"
    "        <Property><Key>Category</Key><Value>Maintenance</Value></Property>\n"
    "      </Properties>\n"
    "    </UnitTest>\n"
    '    <UnitTest name="Do not use floating point data types" id="2">\n'
    "      <Properties>\n"
    "        <Property><Key>RuleID</Key><Value>PERF_02</Value></Property>\n"
    "        <Property><Key>Severity</Key><Value>2</Value></Property>\n"
    "        <Property><Key>Category</Key><Value>Performance</Value></Property>\n"
    "      </Properties>\n"
    "    </UnitTest>\n"
    "  </TestDefinitions>\n"
    "  <Results>\n"
    '    <UnitTestResult testId="1" testName="Ensure tables have relationships"'
    ' outcome="Failed">\n'
    "      <Output><ErrorInfo>\n"
    "        <Message>1 object(s) in violation of rule</Message>\n"
    "        <StackTrace>Objects in violation:\n"
    "  'Orphan Table'</StackTrace>\n"
    "      </ErrorInfo></Output>\n"
    "    </UnitTestResult>\n"
    '    <UnitTestResult testId="2" testName="Do not use floating point data types"'
    ' outcome="Failed">\n'
    "      <Output><ErrorInfo>\n"
    "        <Message>1 object(s) in violation of rule</Message>\n"
    "        <StackTrace>Objects in violation:\n"
    "  'Sales'[Amount]</StackTrace>\n"
    "      </ErrorInfo></Output>\n"
    "    </UnitTestResult>\n"
    "  </Results>\n"
    "</TestRun>"
)


@pytest.mark.bpa
def test_failed_result_carries_a_table_or_column_object_not_just_bracketed_measures(
    tmp_path,
):
    """TE2 formats table/column object names with single quotes, not brackets.

    A bracket-only filter would silently drop these, leaving the report's
    Object column blank for any rule that names a table or column instead
    of a measure.
    """
    _exit_code, data = _run(tmp_path, _TRX_TABLE_AND_RELATIONSHIP_OBJECTS)

    by_rule = {r["RuleID"]: r for r in data["test_results"]}
    assert "'Orphan Table'" in by_rule["MAINT_01"]["ObjectName"]
    assert "'Sales'[Amount]" in by_rule["PERF_02"]["ObjectName"]


def _run(tmp_path: Path, trx: str):
    tmdl = tmp_path / "SalesModel.SemanticModel"
    tmdl.mkdir()
    rules = tmp_path / "rules.json"
    rules.write_text("[]", encoding="utf-8")
    te = tmp_path / "TabularEditor.exe"
    te.write_text("fake", encoding="utf-8")
    output = tmp_path / "out.json"
    native_out = tmp_path / "native.xml"
    native_out.write_text(trx, encoding="utf-8")

    class Args:
        tmdl_path = str(tmdl)
        bpa_rules_path = str(rules)
        tabular_editor_path = str(te)
        output_path = str(output)
        native_output_path = str(native_out)

    with mock.patch("fab_test.scripts._analyzer_process.subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        exit_code = run_bpa(Args())
    return exit_code, json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.bpa
def test_envelope_carries_a_test_results_entry_for_every_rule_evaluated(tmp_path):
    """Given one passed and one failed rule, should list both, not only the failure."""
    _exit_code, data = _run(tmp_path, _TRX)

    assert len(data["findings"]) == 1, "findings stays failure-only for existing consumers"
    assert len(data["test_results"]) == 2, "test_results should include the passed rule too"


@pytest.mark.bpa
def test_a_passing_run_still_lists_every_test_conducted(tmp_path):
    """Given all rules pass, the envelope must not read as if nothing ran."""
    exit_code, data = _run(tmp_path, _ALL_PASSED_TRX)

    assert exit_code == 0
    assert data["findings"] == []
    assert len(data["test_results"]) == 1
    assert data["test_results"][0]["status"] == "pass"


@pytest.mark.bpa
def test_test_results_carry_a_pass_fail_status_per_row(tmp_path):
    _exit_code, data = _run(tmp_path, _TRX)

    by_rule = {r["RuleID"]: r for r in data["test_results"]}
    assert by_rule["PERF_01"]["status"] == "pass"
    assert by_rule["MAINT_02"]["status"] == "error", "severity 3 crosses the error threshold"


@pytest.mark.bpa
def test_a_failed_rule_below_the_error_threshold_is_a_warning_status(tmp_path):
    below_threshold = _TRX.replace(
        "<Key>Severity</Key><Value>3</Value>", "<Key>Severity</Key><Value>2</Value>"
    )
    _exit_code, data = _run(tmp_path, below_threshold)

    by_rule = {r["RuleID"]: r for r in data["test_results"]}
    assert by_rule["MAINT_02"]["status"] == "warning"


@pytest.mark.bpa
def test_test_results_carries_the_rule_identity_fields(tmp_path):
    _exit_code, data = _run(tmp_path, _TRX)

    by_rule = {r["RuleID"]: r for r in data["test_results"]}
    passed = by_rule["PERF_01"]
    assert passed["RuleName"] == "Avoid bi-directional relationships"
    assert passed["Category"] == "Performance"


@pytest.mark.bpa
def test_failed_result_carries_the_violating_object(tmp_path):
    _exit_code, data = _run(tmp_path, _TRX)

    by_rule = {r["RuleID"]: r for r in data["test_results"]}
    assert "[Total Sales]" in by_rule["MAINT_02"]["ObjectName"]
