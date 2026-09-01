"""Contract tests for telemetry configuration (Eventhouse Shipping §1).

Scope
-----
Where the Eventhouse address comes from, and how a caller finds out. No
cluster, no credentials, no network — this file is about resolution order
and what `config --show` reports.

    pytest -m telemetry tests/test_telemetry_config.py
    pytest -m telemetry tests/test_telemetry_config.py -k origin
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fab_test.scripts._config import ConfigError, validate_config
from fab_test.scripts._telemetry import (
    EVENTHOUSE_DATABASE_VAR,
    EVENTHOUSE_URI_VAR,
    resolve_eventhouse_config,
)

_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"


def _file_config(uri: str = _URI, database: str = "fabric_ops") -> dict:
    """A merged file config carrying a telemetry block, built fresh per test."""
    return {"telemetry": {"eventhouse": {"uri": uri, "database": database}}}


# --------------------------------------------------------------------------
# The config file may carry a telemetry block at all
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_validate_config_accepts_a_telemetry_block():
    """Given a telemetry block, should validate.

    The schema is `additionalProperties: false`, so before this epic a
    `telemetry:` key was a validation *error* — a user following any
    documentation would have been refused by the config front door.
    """
    validate_config(_file_config())


@pytest.mark.telemetry
def test_validate_config_names_the_full_path_of_an_unknown_telemetry_key():
    """Given a typo inside the block, should name the nested key, not just 'telemetry'."""
    config = {"telemetry": {"eventhouse": {"uri": _URI, "databse": "fabric_ops"}}}

    with pytest.raises(ConfigError) as exc:
        validate_config(config)

    assert "telemetry.eventhouse.databse" in str(exc.value)
    assert "database" in str(exc.value), "a close match should be suggested"


@pytest.mark.telemetry
def test_validate_config_rejects_a_non_string_uri():
    """Given a wrongly typed value, should name the key and the expected type."""
    config = {"telemetry": {"eventhouse": {"uri": 42}}}

    with pytest.raises(ConfigError) as exc:
        validate_config(config)

    assert "telemetry.eventhouse.uri" in str(exc.value)
    assert "str" in str(exc.value)


@pytest.mark.telemetry
def test_the_table_is_not_a_config_key():
    """Given a `table` key, should be refused — the table is derived from the analyzer.

    One fewer thing to get wrong: `fabric_static_analysis` vs
    `fabric_dynamic_analysis` already follows from which analyzer ran.
    """
    with pytest.raises(ConfigError):
        validate_config({"telemetry": {"eventhouse": {"table": "fabric_static_analysis"}}})


# --------------------------------------------------------------------------
# Resolution order: env > config file > default
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_config_file_supplies_the_address_and_names_its_layer(monkeypatch):
    """Given only a config file, should resolve from it and say so."""
    monkeypatch.delenv(EVENTHOUSE_URI_VAR, raising=False)
    monkeypatch.delenv(EVENTHOUSE_DATABASE_VAR, raising=False)

    resolved = resolve_eventhouse_config(_file_config())

    assert resolved.uri == _URI
    assert resolved.database == "fabric_ops"
    assert resolved.uri_origin == "fab-test.yml:telemetry.eventhouse.uri"
    assert resolved.configured is True


@pytest.mark.telemetry
def test_environment_variable_wins_over_the_config_file(monkeypatch):
    """Given both, should prefer the environment variable.

    Matches the documented flag > env > config > default order that every
    other setting follows; telemetry is not a second mechanism.
    """
    monkeypatch.setenv(EVENTHOUSE_URI_VAR, "https://from-env.kusto.fabric.microsoft.com")
    monkeypatch.delenv(EVENTHOUSE_DATABASE_VAR, raising=False)

    resolved = resolve_eventhouse_config(_file_config())

    assert resolved.uri == "https://from-env.kusto.fabric.microsoft.com"
    assert resolved.uri_origin == f"env:{EVENTHOUSE_URI_VAR}"
    # The database was not overridden, so it still comes from the file.
    assert resolved.database == "fabric_ops"
    assert resolved.database_origin == "fab-test.yml:telemetry.eventhouse.database"


@pytest.mark.telemetry
def test_nothing_configured_is_not_configured(monkeypatch):
    """Given no telemetry anywhere, should report unconfigured rather than empty strings."""
    monkeypatch.delenv(EVENTHOUSE_URI_VAR, raising=False)
    monkeypatch.delenv(EVENTHOUSE_DATABASE_VAR, raising=False)

    resolved = resolve_eventhouse_config({})

    assert resolved.configured is False
    assert resolved.uri == ""
    assert resolved.uri_origin == "default"


@pytest.mark.telemetry
def test_a_uri_without_a_database_is_not_configured(monkeypatch):
    """Given half an address, should not count as configured.

    Ingest needs both. Treating a half-set destination as ready is how a run
    reports success against a database nobody named.
    """
    monkeypatch.delenv(EVENTHOUSE_URI_VAR, raising=False)
    monkeypatch.delenv(EVENTHOUSE_DATABASE_VAR, raising=False)

    resolved = resolve_eventhouse_config({"telemetry": {"eventhouse": {"uri": _URI}}})

    assert resolved.configured is False


# --------------------------------------------------------------------------
# `fab-test config --show`
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_config_show_reports_the_eventhouse_address_and_its_layer(tmp_path, monkeypatch, capsys):
    """Given a configured Eventhouse, should appear in `config --show` with its origin."""
    import sys

    from fab_test.scripts import fab_test as fab_test_module

    monkeypatch.delenv(EVENTHOUSE_URI_VAR, raising=False)
    monkeypatch.delenv(EVENTHOUSE_DATABASE_VAR, raising=False)
    config = tmp_path / "fab-test.yml"
    config.write_text(
        f"telemetry:\n  eventhouse:\n    uri: {_URI}\n    database: fabric_ops\n",
        encoding="utf-8",
    )
    # --config rather than chdir: REPO_ROOT resolves once at import, so a test
    # that only changes directory reads the repository's own configuration.
    monkeypatch.setattr(
        sys,
        "argv",
        ["fab-test", "--config", str(config), "config", "--show", "--format", "json"],
    )

    fab_test_module.main()

    rows = {row["key"]: row for row in json.loads(capsys.readouterr().out)["settings"]}
    assert rows["telemetry.eventhouse.uri"]["value"] == _URI
    assert rows["telemetry.eventhouse.uri"]["origin"] == "fab-test.yml:telemetry.eventhouse.uri"
    assert rows["telemetry.eventhouse.database"]["value"] == "fabric_ops"


@pytest.mark.telemetry
def test_config_show_says_nothing_about_telemetry_when_it_is_not_configured(
    tmp_path, monkeypatch, capsys
):
    """Given no telemetry config, should add no rows — an absent optional section is a default."""
    import sys

    from fab_test.scripts import fab_test as fab_test_module

    monkeypatch.delenv(EVENTHOUSE_URI_VAR, raising=False)
    monkeypatch.delenv(EVENTHOUSE_DATABASE_VAR, raising=False)
    config = tmp_path / "fab-test.yml"
    config.write_text("jobs: 2\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["fab-test", "--config", str(config), "config", "--show", "--format", "json"],
    )

    fab_test_module.main()

    keys = {row["key"] for row in json.loads(capsys.readouterr().out)["settings"]}
    assert not any(key.startswith("telemetry.") for key in keys)


# --------------------------------------------------------------------------
# The published schema is what a user's editor validates against
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_published_schema_describes_the_telemetry_block():
    """Given the shipped JSON schema, should accept the same block validate_config does.

    The schema is what an editor autocompletes from. If it and
    `_config._VALID_KEYS` disagree, one of them refuses a file the other
    accepts — which is the drift `additionalProperties: false` makes loud.
    """
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "src/fab_test/schemas/fab-test.schema.json"
        ).read_text(encoding="utf-8")
    )

    eventhouse = schema["properties"]["telemetry"]["properties"]["eventhouse"]
    assert set(eventhouse["properties"]) == {"uri", "database"}
    assert eventhouse["additionalProperties"] is False
