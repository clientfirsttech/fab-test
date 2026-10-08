"""Contract tests for classifying a pql-test run (status and message).

Pure functions over pql-test's own output: no subprocess, no tenant.
"""

import pytest

from fab_test.scripts._pql_test_status import classify, discovery_connection_error

pytestmark = [pytest.mark.pql_test, pytest.mark.analyzers]

# pql-test 0.1.19's warning lines, verbatim apart from the model names.
_UNREACHABLE = (
    "Warning: live test discovery failed against powerbi://api.powerbi.com/v1.0/myorg/Demo / Sales: "
    "AdomdConnectionException: The specified Power BI workspace ('Demo') is not found."
)
_NOT_INSTALLED = (
    "Warning: live test discovery failed against powerbi://api.powerbi.com/v1.0/myorg/Demo / Sales: "
    "AdomdErrorResponseException: Query (1, 10) Failed to resolve name 'PQL.Assert.RetrieveTests'."
)
_NO_TESTS = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}


def test_given_an_unreachable_model_should_return_pql_tests_reason():
    output = f"No tests found.\n{_UNREACHABLE}"
    assert discovery_connection_error(output) == (
        "AdomdConnectionException: The specified Power BI workspace ('Demo') is not found."
    )


def test_given_a_reachable_model_without_pql_assert_should_not_report_a_connection_error():
    assert discovery_connection_error(_NOT_INSTALLED) == ""


def test_given_no_discovery_warning_should_not_report_a_connection_error():
    assert discovery_connection_error("========= 3 passed =========") == ""


def test_given_nothing_ran_because_the_model_was_unreachable_should_say_it_could_not_connect():
    status, message = classify(_NO_TESTS, [], 0, discovery_connection_error(_UNREACHABLE))
    assert status == "warning"
    assert message.startswith("pql-test ran no tests: could not connect to the model")
    assert "is not found" in message
    assert "pql-test auth status" in message


def test_given_nothing_ran_in_a_reachable_model_should_say_it_has_no_tests():
    status, message = classify(_NO_TESTS, [], 0, discovery_connection_error(_NOT_INSTALLED))
    assert (status, message) == ("warning", "pql-test found no tests to run in this model")


def test_given_passing_tests_should_pass_with_counts():
    status, message = classify({"passed": 3, "failed": 0, "skipped": 0, "total": 3}, [], 0)
    assert status == "passed"
    assert "3 tests, 3 passed" in message
