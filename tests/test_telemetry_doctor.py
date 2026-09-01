"""Contract tests for telemetry in `fab-test doctor` (Eventhouse Shipping §7).

Scope
-----
Telemetry is a prerequisite that can be missing in four distinct ways, and
`doctor` said nothing about any of them. It must also not repeat the false
green it once reported for four cloud analyzers with no credentials at all.

    pytest -m telemetry tests/test_telemetry_doctor.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fab_test.scripts._telemetry import (
    ENABLE_VAR,
    EVENTHOUSE_DATABASE_VAR,
    EVENTHOUSE_URI_VAR,
)
from fab_test.scripts.fab_test import _telemetry_readiness

_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"
_CONFIGURED = {"telemetry": {"eventhouse": {"uri": _URI, "database": "fabric_ops"}}}

_CREDENTIAL_VARS = (
    "FABRIC_TENANT_ID",
    "FABRIC_CLIENT_ID",
    "FABRIC_SERVICE_PRINCIPAL_ID",
    "FABRIC_CLIENT_SECRET",
    "FABRIC_SERVICE_PRINCIPAL_SECRET",
)

# A path guaranteed not to exist, so `.env` discovery in this module never
# picks up a real `.fab-test/.env` or `.env` a developer keeps in their own
# checkout -- these tests must always pass on any machine.
_NO_SUCH_ENV_FILE = str(Path(tempfile.gettempdir()) / "fab-test-test-isolation" / ".env")


class _Args:
    """A doctor invocation, with telemetry configured unless a test says not."""

    def __init__(self, file_config=None):
        self.telemetry = None
        self.file_config = file_config if file_config is not None else _CONFIGURED
        self.output_format = "text"
        self.playwright_env_file = None


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for var in (EVENTHOUSE_URI_VAR, EVENTHOUSE_DATABASE_VAR, ENABLE_VAR, *_CREDENTIAL_VARS):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", _NO_SUCH_ENV_FILE)


def _with_credentials(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_ID", "client-1")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "secret-1")


def _without_ambient(monkeypatch):
    """No az login, no managed identity — nothing but the explicit variables.

    azure-identity is installed in this environment, so DefaultAzureCredential
    is *available* even with no principal set. A test that means "no
    credentials at all" has to say so.
    """
    from fab_test.scripts import _credentials

    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: False)


def _with_extra(monkeypatch, installed: bool):
    """Pretend the [telemetry] extra is or is not importable."""
    from fab_test.scripts import eventhouse_logger

    def _load():
        if not installed:
            raise eventhouse_logger.TelemetryDependencyError(
                f"not installed. Install it with: {eventhouse_logger.TELEMETRY_EXTRA_HINT}"
            )
        return object()

    monkeypatch.setattr(eventhouse_logger, "load_ingest_dependencies", _load)


# --------------------------------------------------------------------------
# Unconfigured is not broken
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_unconfigured_telemetry_is_reported_plainly_not_as_a_failure(monkeypatch):
    """Given no telemetry configuration, should say so without claiming a failure.

    Most runs of a laptop tool never configure telemetry. A ❌ on every one
    of them trains people to ignore the report.
    """
    _with_extra(monkeypatch, installed=False)

    row = _telemetry_readiness(_Args(file_config={}))

    assert row["ready"] is None, "not applicable, rather than ready or broken"
    assert "not configured" in row["reason"]
    assert not row["remediation"]


# --------------------------------------------------------------------------
# The four ways it can be missing
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_missing_extra_is_reported_with_its_install_command(monkeypatch):
    """Given a destination but no ingest client, should name the pip command."""
    _with_credentials(monkeypatch)
    _with_extra(monkeypatch, installed=False)

    row = _telemetry_readiness(_Args())

    assert row["ready"] is False
    assert "fab-test[telemetry]" in row["remediation"]


@pytest.mark.telemetry
def test_missing_credentials_are_reported_in_the_wording_the_analyzers_use(monkeypatch):
    """Given a destination and the client but no credentials, should name the variables.

    Reusing the analyzers' own wording matters: a reader who has already
    solved this for `pql-test` should recognise it rather than parse a
    second dialect of the same instruction.
    """
    _with_extra(monkeypatch, installed=True)
    _without_ambient(monkeypatch)

    row = _telemetry_readiness(_Args())

    assert row["ready"] is False
    assert "FABRIC_TENANT_ID" in row["remediation"]


@pytest.mark.telemetry
def test_a_partial_service_principal_is_reported_as_such(monkeypatch):
    """Given half a principal, should name what is absent rather than fall back silently."""
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
    _with_extra(monkeypatch, installed=True)

    row = _telemetry_readiness(_Args())

    assert row["ready"] is False
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in row["remediation"]


# --------------------------------------------------------------------------
# No false green
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_resolvable_credentials_do_not_earn_a_green_tick(monkeypatch):
    """Given everything resolves, should still not claim ready — the grant is unverified.

    A service principal without the Database Ingestor role authenticates
    perfectly and cannot ingest. `doctor` previously reported four cloud
    analyzers ready with no credentials at all; claiming ready here on the
    strength of a resolvable credential would be the same mistake.
    """
    _with_credentials(monkeypatch)
    _with_extra(monkeypatch, installed=True)

    row = _telemetry_readiness(_Args())

    assert row["ready"] is None, "configured and plausible is not the same as verified"
    assert "Database Ingestor" in (row["remediation"] or row["reason"])


@pytest.mark.telemetry
def test_the_destination_is_named_so_a_reader_can_check_it(monkeypatch):
    """Given a configured destination, should show which cluster and database."""
    _with_credentials(monkeypatch)
    _with_extra(monkeypatch, installed=True)

    row = _telemetry_readiness(_Args())

    assert _URI in row["resolved_path"]
    assert "fabric_ops" in row["resolved_path"]


# --------------------------------------------------------------------------
# It cannot change whether doctor passes
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_ambient_sign_in_counts_as_a_credential(monkeypatch):
    """Given no principal but an available ambient credential, should not report none found.

    `az login`, a managed identity, or a VS Code sign-in is a credential.
    Telling that caller to set service-principal variables would send them
    to fix something that is not broken.
    """
    _with_extra(monkeypatch, installed=True)

    row = _telemetry_readiness(_Args())

    assert row["ready"] is not False


@pytest.mark.telemetry
def test_the_row_is_shaped_like_every_other_doctor_row(monkeypatch):
    """Given the row, should carry the keys the printer reads.

    A row missing a key the renderer indexes crashes `doctor`, which is a
    worse outcome than any telemetry problem it was added to report.
    """
    _with_extra(monkeypatch, installed=True)

    row = _telemetry_readiness(_Args())

    assert set(row) >= {"analyzer", "ready", "reason", "remediation", "resolved_path"}
    assert row["analyzer"] == "telemetry"
