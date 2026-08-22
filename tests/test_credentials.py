"""Contract tests for the credential probe (Artifact Targeting and Auth §7).

Scope
-----
`_credentials.probe_credentials` answers "which identity would fab-test
use?" without acquiring a token. It mirrors the precedence documented on
`build_client_from_env`: environment variables, then a `.env` file, then
an ambient Azure credential -- with ambient attempted only when *no*
service-principal variable is set, so a half-configured principal reads
as the mistake it is rather than being silently overridden.

Ambient availability cannot be proven without acquiring a token, which
would mean a network call or an `az` subprocess. The probe reports it as
resolved-but-unverified and names the command that checks for real; these
tests pin that distinction rather than papering over it. Always passes on
any machine.
"""

import json

import pytest

from fabric_ci_cd_dataops.scripts import _credentials
from fabric_ci_cd_dataops.scripts._credentials import probe_credentials

_ALL_VARS = (
    "FABRIC_TENANT_ID",
    "FABRIC_CLIENT_ID",
    "FABRIC_CLIENT_SECRET",
    "FABRIC_SERVICE_PRINCIPAL_ID",
    "FABRIC_SERVICE_PRINCIPAL_SECRET",
    "PLAYWRIGHT_ENV_FILE",
)

_TENANT = "11111111-1111-1111-1111-111111111111"
_CLIENT = "22222222-2222-2222-2222-222222222222"
_SECRET = "s3cr3t-do-not-print"


@pytest.fixture
def clean_env(monkeypatch):
    """No credential variables, and ambient off unless a test turns it on."""
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: False)
    return monkeypatch


# --------------------------------------------------------------------------- #
# Service principal from the environment
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_full_service_principal_in_environment_resolves(clean_env):
    """All three variables set reports the environment as the winning source."""
    clean_env.setenv("FABRIC_TENANT_ID", _TENANT)
    clean_env.setenv("FABRIC_SERVICE_PRINCIPAL_ID", _CLIENT)
    clean_env.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", _SECRET)

    status = probe_credentials()

    assert status.resolved is True
    assert status.source == "environment"
    assert status.verified is True
    assert status.tenant_id == _TENANT
    assert status.remediation is None


@pytest.mark.fab_test
def test_client_id_spelling_is_accepted(clean_env):
    """FABRIC_CLIENT_ID/SECRET resolve the same as the SERVICE_PRINCIPAL spelling."""
    clean_env.setenv("FABRIC_TENANT_ID", _TENANT)
    clean_env.setenv("FABRIC_CLIENT_ID", _CLIENT)
    clean_env.setenv("FABRIC_CLIENT_SECRET", _SECRET)

    assert probe_credentials().source == "environment"


@pytest.mark.fab_test
def test_partial_service_principal_is_a_mistake_not_an_ambient_fallback(clean_env):
    """A half-set principal names what is missing and never falls through to ambient."""
    clean_env.setattr(_credentials, "ambient_credential_available", lambda: True)
    clean_env.setenv("FABRIC_TENANT_ID", _TENANT)
    clean_env.setenv("FABRIC_SERVICE_PRINCIPAL_ID", _CLIENT)

    status = probe_credentials()

    assert status.resolved is False
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in status.remediation
    assert "ambient" not in status.remediation.lower()


@pytest.mark.fab_test
def test_partial_principal_does_not_name_variables_already_set(clean_env):
    """The remediation asks only for what is actually missing."""
    clean_env.setenv("FABRIC_TENANT_ID", _TENANT)

    remediation = probe_credentials().remediation

    assert "FABRIC_SERVICE_PRINCIPAL_ID" in remediation
    assert "FABRIC_TENANT_ID" not in remediation


# --------------------------------------------------------------------------- #
# .env file
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_env_file_supplies_the_service_principal(clean_env, tmp_path):
    """A .env file resolves the chain when nothing is set in the environment."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"FABRIC_TENANT_ID={_TENANT}\n"
        f"FABRIC_SERVICE_PRINCIPAL_ID={_CLIENT}\n"
        f"FABRIC_SERVICE_PRINCIPAL_SECRET={_SECRET}\n",
        encoding="utf-8",
    )

    status = probe_credentials(env_file=env_file)

    assert status.resolved is True
    assert status.source == ".env"
    assert status.tenant_id == _TENANT


@pytest.mark.fab_test
def test_environment_wins_over_the_env_file(clean_env, tmp_path):
    """Precedence holds: an environment variable beats the same key in .env."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "FABRIC_TENANT_ID=from-the-file\n"
        f"FABRIC_SERVICE_PRINCIPAL_ID={_CLIENT}\n"
        f"FABRIC_SERVICE_PRINCIPAL_SECRET={_SECRET}\n",
        encoding="utf-8",
    )
    clean_env.setenv("FABRIC_TENANT_ID", _TENANT)

    assert probe_credentials(env_file=env_file).tenant_id == _TENANT


@pytest.mark.fab_test
def test_missing_env_file_is_not_an_error(clean_env, tmp_path):
    """A .env path that does not exist degrades to "nothing resolved"."""
    status = probe_credentials(env_file=tmp_path / "absent.env")

    assert status.resolved is False


# --------------------------------------------------------------------------- #
# Ambient Azure credential
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_ambient_credential_resolves_but_is_unverified(clean_env):
    """With no principal set, an available ambient credential resolves unverified."""
    clean_env.setattr(_credentials, "ambient_credential_available", lambda: True)

    status = probe_credentials()

    assert status.resolved is True
    assert status.verified is False
    assert "DefaultAzureCredential" in status.source


@pytest.mark.fab_test
def test_unverified_status_points_at_the_command_that_checks(clean_env):
    """An unverified credential tells the caller how to actually confirm it."""
    clean_env.setattr(_credentials, "ambient_credential_available", lambda: True)

    assert "auth status" in probe_credentials().detail


@pytest.mark.fab_test
def test_nothing_resolvable_lists_every_source_in_precedence_order(clean_env):
    """The remediation names all three accepted sources, in the order tried."""
    status = probe_credentials()

    assert status.resolved is False
    positions = [
        status.remediation.find("FABRIC_TENANT_ID"),
        status.remediation.find(".env"),
        status.remediation.find("az login"),
    ]
    assert all(position >= 0 for position in positions), status.remediation
    assert positions == sorted(positions), "sources listed out of precedence order"


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_probe_never_echoes_the_secret(clean_env, tmp_path):
    """The secrets constraint holds for both the environment and the .env path."""
    env_file = tmp_path / ".env"
    env_file.write_text(f"FABRIC_SERVICE_PRINCIPAL_SECRET={_SECRET}\n", encoding="utf-8")
    clean_env.setenv("FABRIC_TENANT_ID", _TENANT)
    clean_env.setenv("FABRIC_SERVICE_PRINCIPAL_ID", _CLIENT)

    status = probe_credentials(env_file=env_file)

    assert _SECRET not in json.dumps(status.__dict__, default=str)


@pytest.mark.fab_test
def test_probe_acquires_no_token_and_spawns_nothing(clean_env, monkeypatch):
    """No network call and no subprocess -- the probe stays cheap enough for doctor."""
    import subprocess

    def _fail(*args, **kwargs):
        raise AssertionError("probe_credentials must not spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    clean_env.setattr(_credentials, "ambient_credential_available", lambda: True)

    probe_credentials()


@pytest.mark.fab_test
def test_ambient_availability_check_does_not_import_azure_identity(monkeypatch):
    """Availability is a spec lookup: azure.identity's dependency tree stays unloaded.

    Resolving the spec does import the empty `azure` namespace package,
    which is why this guards the submodule rather than the prefix.
    """
    import builtins

    real_import = builtins.__import__

    def _guard(name, *args, **kwargs):
        assert name != "azure.identity", "probe imported azure.identity"
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guard)

    _credentials.ambient_credential_available()
