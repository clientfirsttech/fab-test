"""A lookup that fails narrows coverage; the envelope says so (Workspace Discovery).

Role discovery, a paginated report's deployed definition, and a parameter's
valid values are best-effort: when one fails the report is still rendered,
with one role or no parameters. That used to surface only as a printed
warning, so -q, --format json and the summary called the narrower run a
plain pass. Now each gap is a warning-level `coverage_limited` finding naming
the override, which makes the status `warning` -- exit 0, as warnings never
fail a build.
"""

from types import SimpleNamespace

import pytest

from fab_test.scripts.playwright_validation import discovery
from fab_test.scripts.playwright_validation.rdl_datasource import RdlReportParameter
from fab_test.scripts.playwright_validation.service_client import ServiceClientError

pytestmark = pytest.mark.playwright


class FailingClient:
    def get_semantic_model_roles(self, workspace_id, dataset_id):
        raise ServiceClientError("HTTP 403")

    def get_paginated_report_definition(self, workspace_id, report_id):
        raise ServiceClientError("HTTP 404")

    def execute_dax_query(self, workspace_id, dataset_id, query):
        raise ServiceClientError("HTTP 401")


CONFIG = SimpleNamespace(report_parameters="", workspace_id="ws", report_id="r1", dataset_workspace_id="")


@pytest.fixture(autouse=True)
def fresh():
    discovery.reset_coverage_limits()
    yield
    discovery.reset_coverage_limits()


def _envelope(status="passed"):
    return {"status": status, "findings": []}


def _limited(envelope):
    discovery.apply_coverage_limits(envelope, "Sales")
    return [f for f in envelope["findings"] if f["rule"] == "coverage_limited"]


def test_given_role_discovery_failing_should_warn_naming_roles_none():
    assert discovery._discover_roles(FailingClient(), "ws", "ds") is None
    envelope = _envelope()
    [finding] = _limited(envelope)
    assert finding["severity"] == "warning"
    assert "--roles none" in finding["message"]
    assert envelope["status"] == "warning"


def test_given_the_paginated_definition_unreadable_should_warn_naming_a_local_rdl():
    assert discovery._declared_parameters(CONFIG, FailingClient()) == []
    [finding] = _limited(_envelope())
    assert "--artifact-dir" in finding["message"]


def test_given_valid_values_unqueryable_should_warn_naming_the_tenant_setting():
    parameter = RdlReportParameter(name="Year", multi_value=False, values_query="EVALUATE x", value_column="[Year]")
    assert discovery._valid_values(parameter, FailingClient(), CONFIG, "ds") == []
    [finding] = _limited(_envelope())
    assert "Year" in finding["message"]
    assert "Execute Queries" in finding["message"]


def test_given_a_failed_run_should_keep_failed_and_still_note_the_gap():
    discovery._discover_roles(FailingClient(), "ws", "ds")
    envelope = _envelope("failed")
    assert len(_limited(envelope)) == 1
    assert envelope["status"] == "failed"


def test_given_full_coverage_should_leave_the_envelope_alone():
    envelope = _envelope()
    assert _limited(envelope) == []
    assert envelope == {"status": "passed", "findings": []}


def test_given_one_report_applied_should_not_leak_into_the_next():
    discovery._discover_roles(FailingClient(), "ws", "ds")
    _limited(_envelope())
    assert _limited(_envelope()) == []
