"""Contract tests for telemetry authentication (Eventhouse Shipping §4).

Scope
-----
Ingest authenticates with the service principal the CLI already resolves —
no `EVENTHOUSE_*` credential variables, no second `.env` convention. No
network: this file is about which credential is built and why.

    pytest -m telemetry tests/test_telemetry_credentials.py
    pytest -m telemetry tests/test_telemetry_credentials.py -k partial
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fab_test.scripts._credentials import (
    IncompleteServicePrincipalError,
    resolve_service_principal,
)
from fab_test.scripts.eventhouse_logger import describe_ingest_failure

_ALL_VARS = (
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


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """No test inherits the developer's own credentials."""
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", _NO_SUCH_ENV_FILE)


# --------------------------------------------------------------------------
# The same variables, resolved the same way
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_complete_service_principal_resolves(monkeypatch):
    """Given the Fabric service-principal variables, should resolve them for ingest.

    No EVENTHOUSE_CLIENT_ID and no second .env convention: a caller who has
    already told fab-test who it is should not have to say it twice.
    """
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_ID", "client-1")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "secret-1")

    principal = resolve_service_principal()

    assert principal is not None
    assert (principal.tenant_id, principal.client_id) == ("tenant-1", "client-1")
    assert principal.client_secret == "secret-1"


@pytest.mark.telemetry
def test_the_client_id_aliases_are_both_accepted(monkeypatch):
    """Given FABRIC_CLIENT_ID rather than the SERVICE_PRINCIPAL alias, should resolve."""
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client-1")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "secret-1")

    assert resolve_service_principal().client_id == "client-1"


@pytest.mark.telemetry
def test_no_service_principal_at_all_means_ambient():
    """Given nothing set, should report no principal so the caller falls back to ambient.

    None means "use DefaultAzureCredential", matching the rule
    build_fabric_service_client already documents.
    """
    assert resolve_service_principal() is None


@pytest.mark.telemetry
def test_a_partial_service_principal_is_a_mistake_not_an_ambient_fallback(monkeypatch):
    """Given a half-set principal, should refuse and name what is missing.

    Silently falling back to ambient auth here would answer a different
    question than the caller asked, and the same rule already governs the
    Fabric client.
    """
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")

    with pytest.raises(IncompleteServicePrincipalError) as exc:
        resolve_service_principal()

    message = str(exc.value)
    assert "FABRIC_SERVICE_PRINCIPAL_ID" in message
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in message
    assert "FABRIC_TENANT_ID" not in message, "only the absent variables should be named"


# --------------------------------------------------------------------------
# .env, read without side effects
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_an_env_file_supplies_credentials_without_mutating_the_environment(tmp_path):
    """Given a .env file, should read it and leave os.environ untouched.

    A resolver that exports into the process environment changes what every
    later subprocess sees, which is a side effect nobody asked for.
    """
    import os

    env_file = tmp_path / ".env"
    env_file.write_text(
        "FABRIC_TENANT_ID=tenant-from-file\n"
        "FABRIC_SERVICE_PRINCIPAL_ID=client-from-file\n"
        "FABRIC_SERVICE_PRINCIPAL_SECRET=secret-from-file\n",
        encoding="utf-8",
    )

    principal = resolve_service_principal(env_file=env_file)

    assert principal.tenant_id == "tenant-from-file"
    assert os.environ.get("FABRIC_TENANT_ID") is None


@pytest.mark.telemetry
def test_the_environment_wins_over_the_env_file(tmp_path, monkeypatch):
    """Given both, should prefer the environment — the same order every caller uses."""
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-from-env")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_ID", "client-from-env")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "secret-from-env")
    env_file = tmp_path / ".env"
    env_file.write_text("FABRIC_TENANT_ID=tenant-from-file\n", encoding="utf-8")

    assert resolve_service_principal(env_file=env_file).tenant_id == "tenant-from-env"


@pytest.mark.telemetry
def test_a_missing_env_file_contributes_nothing_rather_than_failing(tmp_path):
    """Given a path that does not exist, should behave as if absent."""
    assert resolve_service_principal(env_file=tmp_path / "nope.env") is None


# --------------------------------------------------------------------------
# A valid credential with no grant is the likely first-run failure
# --------------------------------------------------------------------------


@pytest.mark.telemetry
@pytest.mark.parametrize(
    "message",
    [
        "Forbidden (403): principal is not authorized",
        "Unauthorized access to database fabric_ops",
        "Principal 'aadapp=...' is not authorized to perform 'ingest'",
    ],
)
def test_an_authorization_failure_names_the_ingestor_role(message):
    """Given a 403 from Kusto, should name the grant rather than blame the credential.

    A valid service principal without the Database Ingestor role fails
    identically to a bad secret. Sending a reader to rotate a working secret
    is worse than saying nothing.
    """
    described = describe_ingest_failure(Exception(message))

    assert "Database Ingestor" in described


@pytest.mark.telemetry
def test_an_unrelated_failure_is_passed_through_unembellished():
    """Given a failure that is not an authorization problem, should not guess at a cause."""
    described = describe_ingest_failure(Exception("connection timed out after 30s"))

    assert "Database Ingestor" not in described
    assert "connection timed out" in described


@pytest.mark.telemetry
def test_a_failure_message_is_redacted_before_it_is_reported(monkeypatch):
    """Given an SDK error quoting a connection string, should not echo the secret.

    Kusto errors can carry the connection string that produced them, and the
    secrets constraint puts telemetry alongside stdout and the run manifest.
    """
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "super-secret-value")

    described = describe_ingest_failure(
        Exception("auth failed for AppKey=super-secret-value against the cluster")
    )

    assert "super-secret-value" not in described
    assert "<redacted>" in described
