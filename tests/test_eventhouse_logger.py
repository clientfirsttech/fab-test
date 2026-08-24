"""Contract tests for the eventhouse_logger gate functions (Eventhouse Shipping §5).

Scope
-----
These validators decide what reaches the wire, and until this epic none of
them had a test: the module was on the coverage omit list as "needs a live
service", which was true of the ingest and never true of the checks in
front of it. Taking it off that list is what this file pays for.

No cluster, no credentials, no network.

    pytest -m telemetry tests/test_eventhouse_logger.py
"""

from __future__ import annotations

import json

import pytest

from fabric_ci_cd_dataops.scripts.eventhouse_logger import (
    VALID_TABLES,
    load_payload,
    main,
    publish_analyzer_telemetry,
    validate_feature_flag,
    validate_payload_schema,
    validate_table_name,
)


def _payload(**overrides) -> dict:
    """A schema-complete static-analysis payload, built fresh per test."""
    payload = {
        "timestamp": "2026-08-22T00:00:00+00:00",
        "artifact_name": "Sales",
        "artifact_type": "SemanticModel",
        "commit_sha": "abc123",
        "workflow_run_id": "42",
        "repository": "kerski/fab-test",
        "actor": "someone",
        "results": {"status": "passed"},
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# The feature flag
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_the_feature_flag_is_off_unless_explicitly_true(monkeypatch):
    """Given the flag unset, should report disabled — telemetry is never mandatory."""
    monkeypatch.delenv("ENABLE_EVENTHOUSE_LOGGING", raising=False)

    assert validate_feature_flag(terse=True) is False


@pytest.mark.telemetry
@pytest.mark.parametrize("value", ["true", "TRUE", "True"])
def test_the_feature_flag_is_case_insensitive(monkeypatch, value):
    """Given any casing of true, should enable — a config file is not a shell script."""
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", value)

    assert validate_feature_flag(terse=True) is True


# --------------------------------------------------------------------------
# The table name
# --------------------------------------------------------------------------


@pytest.mark.telemetry
@pytest.mark.parametrize("table", VALID_TABLES)
def test_every_declared_table_is_accepted(table):
    """Given a table this project declares, should accept it."""
    assert validate_table_name(table, terse=True) is True


@pytest.mark.telemetry
def test_an_unknown_table_is_refused(capsys):
    """Given a table nobody declared, should refuse and list the ones that exist.

    Ingest into a non-existent table fails at the cluster, long after the
    run that produced the record has finished.
    """
    assert validate_table_name("fabric_made_up", terse=False) is False
    assert "fabric_static_analysis" in capsys.readouterr().err


# --------------------------------------------------------------------------
# The payload schema
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_complete_static_payload_validates():
    """Given every required field, should validate."""
    assert validate_payload_schema(_payload(), "fabric_static_analysis", terse=True) is True


@pytest.mark.telemetry
@pytest.mark.parametrize(
    "missing",
    ["timestamp", "artifact_name", "artifact_type", "commit_sha", "workflow_run_id",
     "repository", "actor"],
)
def test_each_required_field_is_actually_required(missing):
    """Given one absent common field, should refuse — every field, not just the first."""
    payload = _payload()
    del payload[missing]

    assert validate_payload_schema(payload, "fabric_static_analysis", terse=True) is False


@pytest.mark.telemetry
def test_static_analysis_needs_results():
    """Given no results, should refuse a static-analysis record."""
    payload = _payload()
    del payload["results"]

    assert validate_payload_schema(payload, "fabric_static_analysis", terse=True) is False


@pytest.mark.telemetry
def test_dynamic_analysis_needs_an_environment_as_well():
    """Given a dynamic record with no environment, should refuse.

    A dynamic result without the environment it ran against cannot be
    correlated with anything, which is the whole point of recording it.
    """
    assert (
        validate_payload_schema(_payload(), "fabric_dynamic_analysis", terse=True) is False
    )
    assert (
        validate_payload_schema(
            _payload(environment="DEV"), "fabric_dynamic_analysis", terse=True
        )
        is True
    )


# --------------------------------------------------------------------------
# Loading a payload file
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_payload_file_round_trips(tmp_path):
    """Given a JSON file, should load it."""
    path = tmp_path / "telemetry.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    assert load_payload(path, terse=True)["artifact_name"] == "Sales"


@pytest.mark.telemetry
def test_a_missing_payload_file_exits_rather_than_returning_empty(tmp_path):
    """Given no file, should exit — an empty payload would ingest a meaningless row."""
    with pytest.raises(SystemExit):
        load_payload(tmp_path / "absent.json", terse=True)


@pytest.mark.telemetry
def test_malformed_json_exits_rather_than_returning_empty(tmp_path):
    """Given unparseable JSON, should exit rather than silently ingest nothing."""
    path = tmp_path / "telemetry.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit):
        load_payload(path, terse=True)


# --------------------------------------------------------------------------
# The gate in front of the wire
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_publishing_is_refused_when_the_flag_is_off(monkeypatch):
    """Given the flag off and no force, should not reach the wire at all."""
    monkeypatch.delenv("ENABLE_EVENTHOUSE_LOGGING", raising=False)

    assert publish_analyzer_telemetry("fabric_static_analysis", _payload(), terse=True) is False


@pytest.mark.telemetry
def test_publishing_a_bad_payload_is_refused_even_when_forced(monkeypatch):
    """Given force and an invalid payload, should still refuse.

    `force` bypasses the feature flag, which fab-test has already decided
    for itself. It does not bypass the schema.
    """
    monkeypatch.delenv("ENABLE_EVENTHOUSE_LOGGING", raising=False)

    assert (
        publish_analyzer_telemetry("fabric_static_analysis", {"nope": True}, force=True, terse=True)
        is False
    )


@pytest.mark.telemetry
def test_publishing_to_an_unknown_table_is_refused_even_when_forced(monkeypatch):
    """Given force and an undeclared table, should still refuse."""
    monkeypatch.delenv("ENABLE_EVENTHOUSE_LOGGING", raising=False)

    assert (
        publish_analyzer_telemetry("fabric_made_up", _payload(), force=True, terse=True) is False
    )


# --------------------------------------------------------------------------
# The standalone CLI
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_the_cli_refuses_an_undeclared_table(tmp_path, monkeypatch, capsys):
    """Given --table naming something undeclared, should exit non-zero before any network call."""
    path = tmp_path / "telemetry.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["eventhouse-logger", "--table", "fabric_made_up", "--payload", str(path)],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code != 0
    assert "fabric_made_up" in capsys.readouterr().err
