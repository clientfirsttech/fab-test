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
from fab_test.scripts import fab_test_registry as registry
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
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setattr(registry, "desktop_ports", list)
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: True)
    from fab_test.scripts import _pql_identity

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

    result = registry.check_readiness(analyzer, _args())

    assert result["status"] == "warning"
    assert result["ready"] is False
    assert "credentials from environment" in result["reason"]
    assert "no workspace" in result["reason"]
    assert "FABRIC_WORKSPACE_ID" in result["remediation"]
    assert "FABRIC_CLIENT_SECRET" not in result["remediation"]
    assert "SERVICE_PRINCIPAL" not in result["remediation"]


@pytest.mark.parametrize("analyzer", ["pql_test", "dependencies"])
def test_an_ambient_credential_without_a_workspace_is_info_naming_az_login(analyzer):
    result = registry.check_readiness(analyzer, _args())

    assert result["status"] == "info"
    assert result["ready"] is None
    assert "not configured" in result["reason"]
    assert "credentials" not in result["reason"]
    assert "FABRIC_WORKSPACE_ID" in result["remediation"]
    assert "az login" in result["remediation"]


def test_playwright_without_a_workspace_or_service_principal_is_info_without_az_login():
    result = registry.check_readiness("playwright", _args())

    assert result["status"] == "info"
    assert "run `az login`" not in result["remediation"].lower()
    assert "cannot use `az login`" in result["remediation"]
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in result["remediation"]


def test_no_credential_machinery_at_all_is_still_info(monkeypatch):
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: False)

    result = registry.check_readiness("pql_test", _args())

    assert result["status"] == "info"


def test_a_partial_service_principal_without_a_workspace_is_an_error(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")

    result = registry.check_readiness("pql_test", _args())

    assert result["status"] == "error"
    assert result["ready"] is False
    assert "incomplete" in result["reason"]
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in result["remediation"]


def test_pql_test_remediation_offers_desktop():
    assert "Power BI Desktop" in registry.check_readiness("pql_test", _args())["remediation"]


@pytest.mark.parametrize("analyzer", ["playwright", "dependencies"])
def test_the_playwright_family_remediation_names_its_env_file_key(analyzer, monkeypatch):
    _service_principal(monkeypatch)

    assert "PLAYWRIGHT_WORKSPACE_ID" in registry.check_readiness(analyzer, _args())["remediation"]


def test_pql_test_with_a_running_desktop_stays_ready(monkeypatch):
    monkeypatch.setattr(registry, "desktop_ports", lambda: [51001])

    result = registry.check_readiness("pql_test", _args())

    assert result["status"] == "ready"


# --------------------------------------------------------------------------- #
# Workspace configured: today's answers, now with a status
# --------------------------------------------------------------------------- #


def test_a_workspace_and_service_principal_is_ready(monkeypatch):
    _service_principal(monkeypatch)

    assert registry.check_readiness("playwright", _args(workspace_id=_WS))["status"] == "ready"


def test_a_workspace_with_only_az_login_is_ready_for_pql_test():
    assert registry.check_readiness("pql_test", _args(workspace_id=_WS))["status"] == "ready"


def test_a_workspace_with_only_az_login_is_an_error_for_playwright():
    assert registry.check_readiness("playwright", _args(workspace_id=_WS))["status"] == "error"


def test_a_workspace_with_a_partial_service_principal_is_an_error(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")

    assert registry.check_readiness("pql_test", _args(workspace_id=_WS))["status"] == "error"


@pytest.mark.parametrize("analyzer", ["pql_lint", "rdl", "pql_test", "playwright"])
def test_every_readiness_row_carries_a_status(analyzer):
    assert registry.check_readiness(analyzer, _args())["status"] in _STATUSES


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

    result = registry.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "error"
    assert "x@y.z" in result["remediation"]


def test_pql_test_signed_in_as_the_same_account_is_ready_and_says_so(monkeypatch):
    _identity(monkeypatch, ("john@kerski.net", None))

    result = registry.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "ready"
    assert "john@kerski.net" in result["reason"]
    assert "unverified" not in result["reason"]


def test_pql_test_identity_that_cannot_be_compared_stays_unverified(monkeypatch):
    _identity(monkeypatch, None)

    result = registry.check_readiness("pql_test", _args(workspace_id=_WS))

    assert result["status"] == "ready"
    assert "unverified" in result["reason"]


def test_a_service_principal_never_runs_the_identity_check(monkeypatch):
    _service_principal(monkeypatch)
    _identity(monkeypatch, ("a@b.c", "must not be used"))

    assert registry.check_readiness("pql_test", _args(workspace_id=_WS))["status"] == "ready"


def test_dependencies_never_runs_the_identity_check(monkeypatch):
    _identity(monkeypatch, ("a@b.c", "must not be used"))

    assert registry.check_readiness("dependencies", _args(workspace_id=_WS))["status"] == "ready"
