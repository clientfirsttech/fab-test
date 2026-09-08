"""Contract tests for Lakehouse telemetry configuration (Lakehouse Telemetry Sink §1).

Scope
-----
Where the Lakehouse address comes from, and how the run-level telemetry
decision reflects two independent, optional destinations. No OneLake
client, no credentials, no network — this file is about resolution order
and enablement, mirroring test_telemetry_config.py/test_telemetry_enablement.py
for Eventhouse.

    pytest -m telemetry tests/test_lakehouse_telemetry_config.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fab_test.scripts._config import ConfigError, validate_config
from fab_test.scripts._telemetry import (
    ENABLE_VAR,
    EVENTHOUSE_DATABASE_VAR,
    EVENTHOUSE_URI_VAR,
    LAKEHOUSE_NAME_VAR,
    LAKEHOUSE_WORKSPACE_VAR,
    resolve_lakehouse_config,
    telemetry_decision,
)

_WORKSPACE = "analytics-ws"
_LAKEHOUSE = "TelemetryLakehouse"
_EVENTHOUSE_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"


def _lakehouse_file_config(workspace: str = _WORKSPACE, lakehouse: str = _LAKEHOUSE) -> dict:
    return {"telemetry": {"lakehouse": {"workspace": workspace, "lakehouse": lakehouse}}}


def _both_file_config() -> dict:
    return {
        "telemetry": {
            "eventhouse": {"uri": _EVENTHOUSE_URI, "database": "fabric_ops"},
            "lakehouse": {"workspace": _WORKSPACE, "lakehouse": _LAKEHOUSE},
        }
    }


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """Every test states its own environment; none inherits the developer's."""
    for var in (
        EVENTHOUSE_URI_VAR,
        EVENTHOUSE_DATABASE_VAR,
        LAKEHOUSE_WORKSPACE_VAR,
        LAKEHOUSE_NAME_VAR,
        ENABLE_VAR,
    ):
        monkeypatch.delenv(var, raising=False)


# --------------------------------------------------------------------------
# resolve_lakehouse_config: resolution order and completeness
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_config_file_supplies_the_lakehouse_address_and_names_its_layer():
    """Given only a config file, should resolve from it and say so."""
    resolved = resolve_lakehouse_config(_lakehouse_file_config())

    assert resolved.workspace == _WORKSPACE
    assert resolved.lakehouse == _LAKEHOUSE
    assert resolved.workspace_origin == "fab-test.yml:telemetry.lakehouse.workspace"
    assert resolved.configured is True


@pytest.mark.telemetry
def test_environment_variable_wins_over_the_config_file(monkeypatch):
    """Given both, should prefer the environment variable, matching Eventhouse's precedence."""
    monkeypatch.setenv(LAKEHOUSE_WORKSPACE_VAR, "from-env-ws")

    resolved = resolve_lakehouse_config(_lakehouse_file_config())

    assert resolved.workspace == "from-env-ws"
    assert resolved.workspace_origin == f"env:{LAKEHOUSE_WORKSPACE_VAR}"
    # The lakehouse name was not overridden, so it still comes from the file.
    assert resolved.lakehouse == _LAKEHOUSE
    assert resolved.lakehouse_origin == "fab-test.yml:telemetry.lakehouse.lakehouse"


@pytest.mark.telemetry
def test_nothing_configured_is_not_configured():
    """Given no lakehouse telemetry anywhere, should report unconfigured rather than empty strings."""
    resolved = resolve_lakehouse_config({})

    assert resolved.configured is False
    assert resolved.workspace == ""
    assert resolved.workspace_origin == "default"


@pytest.mark.telemetry
def test_a_workspace_without_a_lakehouse_is_not_configured():
    """Given half an address, should not count as configured.

    Ingest needs both, mirroring Eventhouse's uri+database rule: a half-set
    destination reported as ready is how a run claims success against a
    Lakehouse nobody named.
    """
    resolved = resolve_lakehouse_config({"telemetry": {"lakehouse": {"workspace": _WORKSPACE}}})

    assert resolved.configured is False


# --------------------------------------------------------------------------
# telemetry_decision: two independent, optional destinations
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_lakehouse_only_configuration_enables_telemetry():
    """Given only Lakehouse is configured, should `--telemetry` enable with no Eventhouse address."""
    decision = telemetry_decision(cli_telemetry=None, file_config=_lakehouse_file_config())

    assert decision.enabled is True
    assert decision.lakehouse.configured is True
    assert decision.eventhouse.configured is False
    assert decision.refusal is None


@pytest.mark.telemetry
def test_decision_carries_both_destinations_independently():
    """Given both are configured, should the decision expose both resolved destinations."""
    decision = telemetry_decision(cli_telemetry=None, file_config=_both_file_config())

    assert decision.enabled is True
    assert decision.eventhouse.configured is True
    assert decision.lakehouse.configured is True
    assert decision.eventhouse.uri == _EVENTHOUSE_URI
    assert decision.lakehouse.workspace == _WORKSPACE


@pytest.mark.telemetry
def test_neither_destination_configured_is_not_an_error():
    """Given neither is configured, should stay off without complaining."""
    decision = telemetry_decision(cli_telemetry=None, file_config={})

    assert decision.enabled is False
    assert decision.refusal is None


@pytest.mark.telemetry
def test_explicit_flag_with_neither_destination_refuses_naming_both():
    """Given --telemetry and nothing configured, should name both destinations' fixes.

    An explicit request that quietly no-ops is exactly what Eventhouse
    Shipping ended for the Eventhouse path; the same must hold once a second
    destination exists.
    """
    decision = telemetry_decision(cli_telemetry=True, file_config={})

    assert decision.enabled is False
    assert decision.refusal is not None
    assert "telemetry.eventhouse.uri" in decision.refusal
    assert "telemetry.lakehouse.workspace" in decision.refusal


@pytest.mark.telemetry
def test_explicit_flag_ships_when_only_lakehouse_is_configured():
    """Given --telemetry with only a Lakehouse address, should enable and not refuse."""
    decision = telemetry_decision(cli_telemetry=True, file_config=_lakehouse_file_config())

    assert decision.enabled is True
    assert decision.refusal is None


# --------------------------------------------------------------------------
# The config file may carry a `telemetry.lakehouse` block, alongside eventhouse
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_validate_config_accepts_a_lakehouse_telemetry_block():
    """Given a `telemetry.lakehouse` block, should validate."""
    validate_config(_lakehouse_file_config())


@pytest.mark.telemetry
def test_validate_config_accepts_both_destinations_together():
    """Given both `telemetry.eventhouse` and `telemetry.lakehouse`, should validate."""
    validate_config(_both_file_config())


@pytest.mark.telemetry
def test_validate_config_names_the_full_path_of_an_unknown_lakehouse_key():
    """Given a typo inside the lakehouse block, should name the nested key, not just 'telemetry'."""
    config = {"telemetry": {"lakehouse": {"workspac": _WORKSPACE, "lakehouse": _LAKEHOUSE}}}

    with pytest.raises(ConfigError) as exc:
        validate_config(config)

    assert "telemetry.lakehouse.workspac" in str(exc.value)
    assert "workspace" in str(exc.value), "a close match should be suggested"


@pytest.mark.telemetry
def test_validate_config_rejects_a_non_string_lakehouse_value():
    """Given a wrongly typed value, should name the key and the expected type."""
    config = {"telemetry": {"lakehouse": {"workspace": 42}}}

    with pytest.raises(ConfigError) as exc:
        validate_config(config)

    assert "telemetry.lakehouse.workspace" in str(exc.value)
    assert "str" in str(exc.value)


@pytest.mark.telemetry
def test_published_schema_describes_the_lakehouse_telemetry_block():
    """Given the shipped JSON schema, should accept the same block validate_config does.

    Mirrors the Eventhouse schema-drift guard: an editor autocompletes from
    the schema, and disagreement with `_config`'s own validation would
    refuse a file one of them accepts.
    """
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "src/fab_test/schemas/fab-test.schema.json"
        ).read_text(encoding="utf-8")
    )

    lakehouse = schema["properties"]["telemetry"]["properties"]["lakehouse"]
    assert set(lakehouse["properties"]) == {"workspace", "lakehouse"}
    assert lakehouse["additionalProperties"] is False
