"""Contract tests for what turns telemetry on (Eventhouse Shipping §2).

Scope
-----
A configured Eventhouse is the enablement — there is no new flag. The two
switches that already existed keep working, and `--telemetry` with nothing
configured refuses loudly instead of quietly doing nothing, which is the
failure this epic exists to end.

    pytest -m telemetry tests/test_telemetry_enablement.py
    pytest -m telemetry tests/test_telemetry_enablement.py -k refus
"""

from __future__ import annotations

import pytest

from fabric_ci_cd_dataops.scripts._telemetry import (
    ENABLE_VAR,
    EVENTHOUSE_DATABASE_VAR,
    EVENTHOUSE_URI_VAR,
    telemetry_decision,
)

_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"
_CONFIGURED = {"telemetry": {"eventhouse": {"uri": _URI, "database": "fabric_ops"}}}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """Every test states its own environment; none inherits the developer's."""
    for var in (EVENTHOUSE_URI_VAR, EVENTHOUSE_DATABASE_VAR, ENABLE_VAR):
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------------------
# Configuration is the enablement
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_configured_eventhouse_ships_without_any_flag():
    """Given a configured destination and no flags, should ship.

    The reason to configure a destination is to send to it. Requiring a flag
    on top would mean every CI job carries one, and a configured-but-silent
    Eventhouse is a support question waiting to happen.
    """
    decision = telemetry_decision(cli_telemetry=None, file_config=_CONFIGURED)

    assert decision.enabled is True
    assert decision.refusal is None


@pytest.mark.telemetry
def test_nothing_configured_and_no_flag_does_not_ship():
    """Given no destination and no flag, should stay off without complaining."""
    decision = telemetry_decision(cli_telemetry=None, file_config={})

    assert decision.enabled is False
    assert decision.refusal is None, "unconfigured is not an error"


# --------------------------------------------------------------------------
# The two switches that already existed
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_no_telemetry_refuses_even_when_configured():
    """Given --no-telemetry, should send nothing regardless of configuration."""
    decision = telemetry_decision(cli_telemetry=False, file_config=_CONFIGURED)

    assert decision.enabled is False
    assert decision.refusal is None, "an explicit off is not an error"


@pytest.mark.telemetry
def test_enable_eventhouse_logging_true_still_asks_for_telemetry(monkeypatch):
    """Given the legacy environment variable and no address, should ask but not ship.

    It cannot ship: there is nowhere to send. What it must not do is fail the
    run — this is the exact combination every existing caller has today, and
    §6 turns the missing destination into a warning rather than an error.
    """
    monkeypatch.setenv(ENABLE_VAR, "true")

    decision = telemetry_decision(cli_telemetry=None, file_config={})

    assert decision.requested is True
    assert decision.enabled is False
    assert decision.refusal is None


@pytest.mark.telemetry
def test_enable_eventhouse_logging_true_ships_to_a_configured_address(monkeypatch):
    """Given the legacy variable and an address, should ship."""
    monkeypatch.setenv(ENABLE_VAR, "true")

    decision = telemetry_decision(cli_telemetry=None, file_config=_CONFIGURED)

    assert decision.enabled is True


@pytest.mark.telemetry
def test_an_explicit_off_beats_configuration(monkeypatch):
    """Given ENABLE_EVENTHOUSE_LOGGING=false and a configured destination, should not ship.

    Configuration enables implicitly; the variable says no explicitly. An
    explicit off wins, or the variable would stop being a way to turn
    telemetry off in an environment whose config file you do not control.
    """
    monkeypatch.setenv(ENABLE_VAR, "false")

    decision = telemetry_decision(cli_telemetry=None, file_config=_CONFIGURED)

    assert decision.enabled is False


@pytest.mark.telemetry
def test_the_flag_beats_the_environment_variable(monkeypatch):
    """Given --telemetry against an explicit off, should ship — flag > env, as documented."""
    monkeypatch.setenv(ENABLE_VAR, "false")

    decision = telemetry_decision(cli_telemetry=True, file_config=_CONFIGURED)

    assert decision.enabled is True


# --------------------------------------------------------------------------
# An explicit request with nowhere to send refuses, loudly
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_telemetry_flag_with_no_destination_refuses_and_names_the_fix():
    """Given --telemetry and nothing configured, should refuse with the key and the variable.

    Today this silently reaches a placeholder and reports success. An
    explicit request that quietly no-ops is exactly what this epic ends, so
    it must name both ways to supply an address.
    """
    decision = telemetry_decision(cli_telemetry=True, file_config={})

    assert decision.enabled is False
    assert decision.refusal is not None
    assert "telemetry.eventhouse.uri" in decision.refusal
    assert EVENTHOUSE_URI_VAR in decision.refusal


@pytest.mark.telemetry
def test_telemetry_flag_with_half_a_destination_also_refuses():
    """Given a URI but no database, should refuse rather than ship somewhere unnamed."""
    decision = telemetry_decision(
        cli_telemetry=True, file_config={"telemetry": {"eventhouse": {"uri": _URI}}}
    )

    assert decision.enabled is False
    assert "database" in decision.refusal


@pytest.mark.telemetry
def test_the_legacy_variable_alone_does_not_refuse(monkeypatch):
    """Given ENABLE_EVENTHOUSE_LOGGING=true and no address, should not refuse the run.

    Backward compatibility: this combination is what every existing caller
    has today. It cannot start failing runs — §6 reports the missing
    destination as a warning instead.
    """
    monkeypatch.setenv(ENABLE_VAR, "true")

    decision = telemetry_decision(cli_telemetry=None, file_config={})

    assert decision.refusal is None


# --------------------------------------------------------------------------
# The decision carries the destination, so callers resolve it once
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_the_decision_carries_the_resolved_destination():
    """Given a configured destination, should expose it for the dry-run preview and doctor."""
    decision = telemetry_decision(cli_telemetry=None, file_config=_CONFIGURED)

    assert decision.eventhouse.uri == _URI
    assert decision.eventhouse.database == "fabric_ops"
