"""Contract tests: `doctor` says what is missing, at the severity it deserves.

Scope
-----
With no workspace found, `doctor` reported "no workspace or credentials
resolved" without probing credentials, and every non-ready row was ❌
whether the run was broken or simply never set up (Doctor Severity epic).

    pytest tests/test_doctor_severity.py
"""

from __future__ import annotations

import argparse

import pytest

from fab_test.scripts import _credentials
from fab_test.scripts import _readiness as readiness
from fab_test.scripts.fab_test_summary import _print_doctor

_WS = "798dfd00-0081-45d3-a7a7-f74f62e57277"
_STATUSES = {"ready", "warning", "info", "error"}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for var in (
        "FABRIC_WORKSPACE_ID",
        "FABRIC_TENANT_ID",
        "FABRIC_SERVICE_PRINCIPAL_ID",
        "FABRIC_SERVICE_PRINCIPAL_SECRET",
        "FABRIC_CLIENT_ID",
        "FABRIC_CLIENT_SECRET",
        "PLAYWRIGHT_WORKSPACE_ID",
        # Readiness wording differs in CI (no --interactive hint), so a run
        # with CI's own variables set must not change what is tested here.
        "CI",
        "GITHUB_ACTIONS",
        "TF_BUILD",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setattr(readiness, "desktop_ports", list)
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: True)
    monkeypatch.setattr(_credentials, "az_cli_available", lambda: True)
    from fab_test.scripts import _cloud_readiness, _pql_identity, _service_export

    monkeypatch.setattr(_cloud_readiness, "az_cli_available", lambda: True)
    monkeypatch.setattr(_service_export, "az_cli_available", lambda: True)
    monkeypatch.setattr(_pql_identity, "identity_check", lambda: None)  # no az / pql-test subprocess


def _service_principal(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client-1")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "secret-value-1")


def _args(**overrides) -> argparse.Namespace:
    defaults = {"workspace_id": "", "file_config": {}}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# --------------------------------------------------------------------------- #
# No workspace
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("analyzer", ["pql_test", "playwright", "dependencies"])
def test_a_service_principal_without_a_workspace_is_a_warning_about_the_workspace(
    analyzer, monkeypatch
):
    _service_principal(monkeypatch)

    result = readiness.check_readiness(analyzer, _args())

    assert result["status"] == "warning"
    assert result["ready"] is False
    assert "credentials from environment" in result["reason"]
    assert "no workspace" in result["reason"]
    assert "FABRIC_WORKSPACE_ID" in result["remediation"]
    assert "FABRIC_CLIENT_SECRET" not in result["remediation"]
    assert "SERVICE_PRINCIPAL" not in result["remediation"]


@pytest.mark.parametrize("analyzer", ["pql_test", "dependencies"])
def test_an_ambient_credential_without_a_workspace_is_info_naming_az_login(analyzer):
    result = readiness.check_readiness(analyzer, _args())

    assert result["status"] == "info"
    assert result["ready"] is None
    assert "not configured" in result["reason"]
    assert "credentials" not in result["reason"]
    assert "FABRIC_WORKSPACE_ID" in result["remediation"]
    assert "az login" in result["remediation"]


def test_playwright_without_a_workspace_or_service_principal_is_info_without_az_login():
    result = readiness.check_readiness("playwright", _args())

    assert result["status"] == "info"
    assert "run `az login`" not in result["remediation"].lower()
    assert "cannot use `az login`" in result["remediation"]
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in result["remediation"]


def test_no_credential_machinery_at_all_is_still_info(monkeypatch):
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: False)

    result = readiness.check_readiness("pql_test", _args())

    assert result["status"] == "info"


def test_a_partial_service_principal_without_a_workspace_is_an_error(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")

    result = readiness.check_readiness("pql_test", _args())

    assert result["status"] == "error"
    assert result["ready"] is False
    assert "incomplete" in result["reason"]
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in result["remediation"]


def test_pql_test_remediation_offers_desktop():
    assert "Power BI Desktop" in readiness.check_readiness("pql_test", _args())["remediation"]


@pytest.mark.parametrize("analyzer", ["playwright", "dependencies"])
def test_the_playwright_family_remediation_names_its_env_file_key(analyzer, monkeypatch):
    _service_principal(monkeypatch)

    assert "PLAYWRIGHT_WORKSPACE_ID" in readiness.check_readiness(analyzer, _args())["remediation"]


def test_pql_test_with_a_running_desktop_stays_ready(monkeypatch):
    monkeypatch.setattr(readiness, "desktop_ports", lambda: [51001])

    result = readiness.check_readiness("pql_test", _args())

    assert result["status"] == "ready"


# --------------------------------------------------------------------------- #
# Workspace configured: today's answers, now with a status
# --------------------------------------------------------------------------- #


def test_a_workspace_and_service_principal_is_ready(monkeypatch):
    _service_principal(monkeypatch)

    assert readiness.check_readiness("playwright", _args(workspace_id=_WS))["status"] == "ready"


def test_a_workspace_with_only_az_login_is_ready_for_pql_test():
    assert readiness.check_readiness("pql_test", _args(workspace_id=_WS))["status"] == "ready"


def test_a_workspace_with_only_az_login_is_an_error_for_playwright():
    assert readiness.check_readiness("playwright", _args(workspace_id=_WS))["status"] == "error"


def test_a_workspace_with_a_partial_service_principal_is_an_error(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")

    assert readiness.check_readiness("pql_test", _args(workspace_id=_WS))["status"] == "error"


@pytest.mark.parametrize("analyzer", ["pql_lint", "rdl", "pql_test", "playwright"])
def test_every_readiness_row_carries_a_status(analyzer):
    assert readiness.check_readiness(analyzer, _args())["status"] in _STATUSES


# --------------------------------------------------------------------------- #
# Azure CLI presence (Doctor Az Detection epic)
# --------------------------------------------------------------------------- #


def test_a_workspace_with_ambient_credentials_and_no_az_cli_is_an_error(monkeypatch):
    from fab_test.scripts import _cloud_readiness

    monkeypatch.setattr(_cloud_readiness, "az_cli_available", lambda: False)

    result = readiness.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "error"
    assert result["ready"] is False
    assert "Azure CLI" in result["reason"]
    assert "not installed" in result["reason"]
    assert "Install the Azure CLI" in result["remediation"]


def test_a_workspace_with_ambient_credentials_and_az_cli_present_is_still_ready(monkeypatch):
    from fab_test.scripts import _cloud_readiness

    monkeypatch.setattr(_cloud_readiness, "az_cli_available", lambda: True)

    result = readiness.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "ready"


def test_a_service_principal_is_unaffected_by_a_missing_az_cli(monkeypatch):
    from fab_test.scripts import _cloud_readiness

    _service_principal(monkeypatch)
    monkeypatch.setattr(_cloud_readiness, "az_cli_available", lambda: False)

    # "dependencies", not "playwright": this assertion is about the az-presence
    # branch, not about whether the playwright runner extra is installed here.
    assert readiness.check_readiness("dependencies", _args(workspace_id=_WS))["status"] == "ready"


def test_no_workspace_never_probes_the_az_cli(monkeypatch):
    from fab_test.scripts import _cloud_readiness

    def _boom():
        raise AssertionError("az_cli_available must not be called without a workspace")

    monkeypatch.setattr(_cloud_readiness, "az_cli_available", _boom)

    result = readiness.check_readiness("pql_test", _args())

    assert result["status"] == "info"


def test_a_missing_az_cli_is_reported_before_the_pql_test_identity_check(monkeypatch):
    from fab_test.scripts import _cloud_readiness

    _identity(monkeypatch, None)  # az not found: identity_check cannot compare
    monkeypatch.setattr(_cloud_readiness, "az_cli_available", lambda: False)

    result = readiness.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "error"
    assert "Azure CLI" in result["reason"]


# --------------------------------------------------------------------------- #
# Output and exit code
# --------------------------------------------------------------------------- #


def _row(name: str, ready: bool | None, status: str | None = None) -> dict:
    row = {
        "analyzer": name,
        "ready": ready,
        "reason": f"{name} reason",
        "resolved_path": None,
        "remediation": f"{name} fix",
        "version": None,
    }
    if status:
        row["status"] = status
    return row


def test_any_error_exits_one_even_when_another_analyzer_is_ready():
    rows = [_row("pql_lint", True), _row("bpa", False)]

    assert _print_doctor(rows, output_format="json") == 1


def test_warnings_and_info_alone_exit_zero():
    rows = [_row("pql_test", False, "warning"), _row("playwright", None, "info")]

    assert _print_doctor(rows, output_format="json") == 0


def test_strict_turns_a_warning_into_a_failure():
    rows = [_row("pql_lint", True), _row("pql_test", False, "warning")]

    assert _print_doctor(rows, output_format="json", strict=True) == 1


def test_json_rows_carry_their_status(capsys):
    import json

    _print_doctor([_row("pql_lint", True), _row("telemetry", None)], output_format="json")

    statuses = [r["status"] for r in json.loads(capsys.readouterr().out)["analyzers"]]
    assert statuses == ["ready", "info"]


def test_a_warning_prints_its_mark_and_remediation(capsys):
    _print_doctor([_row("pql_test", False, "warning")], output_format="text")

    out = capsys.readouterr().out
    assert "⚠ pql_test: pql_test reason" in out
    assert "→ pql_test fix" in out


def test_doctor_takes_strict():
    from fab_test.scripts.fab_test_parser import build_parser

    assert build_parser().parse_args(["doctor", "--strict"]).strict is True
    assert build_parser().parse_args(["doctor"]).strict is False


# --------------------------------------------------------------------------- #
# Service-mode line
# --------------------------------------------------------------------------- #


def test_the_service_line_has_no_stray_separator_for_an_ambient_credential():
    from fab_test.scripts._service_export import service_readiness

    line = service_readiness(_args())

    assert ". ;" not in line
    assert line.endswith("; or pass --interactive")


def test_the_service_line_offers_no_interactive_sign_in_in_ci(monkeypatch):
    """Given CI, should not suggest --interactive, which never prompts there."""
    from fab_test.scripts._service_export import service_readiness

    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    line = service_readiness(_args())

    assert "--interactive" not in line


def test_the_service_line_names_a_missing_az_cli(monkeypatch):
    """Given an ambient credential and no `az`, should say so (Doctor Az Detection epic)."""
    from fab_test.scripts import _service_export
    from fab_test.scripts._service_export import service_readiness

    monkeypatch.setattr(_service_export, "az_cli_available", lambda: False)

    line = service_readiness(_args())

    assert "Azure CLI" in line
    assert "not installed" in line


def test_the_service_line_is_silent_about_az_when_it_is_present():
    from fab_test.scripts._service_export import service_readiness

    line = service_readiness(_args())

    assert "Azure CLI" not in line


def test_the_service_line_does_not_mention_az_for_a_service_principal(monkeypatch):
    """A configured service principal never needs `az`, missing or not."""
    from fab_test.scripts import _service_export
    from fab_test.scripts._service_export import service_readiness

    _service_principal(monkeypatch)
    monkeypatch.setattr(_service_export, "az_cli_available", lambda: False)

    line = service_readiness(_args())

    assert "Azure CLI" not in line


# --------------------------------------------------------------------------- #
# A tool fetched on first run is not broken
# --------------------------------------------------------------------------- #


def test_a_tool_not_yet_downloaded_is_info_and_does_not_fail_doctor():
    from fab_test.scripts._analyzer_tool_bootstrap import _probe_pending_install

    result = _probe_pending_install({"archive_type": "zip"}, "https://example.com/tool.zip", "1.0")

    assert result["status"] == "info"
    assert _print_doctor([{"analyzer": "bpa", **result}], output_format="json") == 0


# --------------------------------------------------------------------------- #
# pql_test with az login: the identity the run would refuse
# --------------------------------------------------------------------------- #


def _identity(monkeypatch, result):
    from fab_test.scripts import _pql_identity

    monkeypatch.setattr(_pql_identity, "identity_check", lambda: result)


def test_pql_test_signed_in_as_another_account_is_an_error(monkeypatch):
    _identity(monkeypatch, ("john@kerski.net", "fab-test is signed in as john@kerski.net but pql-test as x@y.z."))

    result = readiness.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "error"
    assert "x@y.z" in result["remediation"]


def test_pql_test_signed_in_as_the_same_account_is_ready_and_says_so(monkeypatch):
    _identity(monkeypatch, ("john@kerski.net", None))

    result = readiness.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "ready"
    assert "john@kerski.net" in result["reason"]
    assert "unverified" not in result["reason"]


def test_pql_test_identity_that_cannot_be_compared_stays_unverified(monkeypatch):
    _identity(monkeypatch, None)

    result = readiness.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "ready"
    assert "unverified" in result["reason"]


def test_a_service_principal_never_runs_the_identity_check(monkeypatch):
    _service_principal(monkeypatch)
    _identity(monkeypatch, ("a@b.c", "must not be used"))

    assert readiness.check_readiness("pql_test", _args(workspace_id=_WS))["status"] == "ready"


def test_dependencies_never_runs_the_identity_check(monkeypatch):
    _identity(monkeypatch, ("a@b.c", "must not be used"))

    assert readiness.check_readiness("dependencies", _args(workspace_id=_WS))["status"] == "ready"
