"""Contract tests for Lakehouse telemetry wiring (Lakehouse Telemetry Sink §4).

Scope
-----
Config resolution (§1), schema (§2), and the sink itself (§3) all landed
already tested. What was still missing is the fan-out: `config --show` and
`doctor` never mentioned Lakehouse at all, and a real run's `_open_telemetry`
only ever built an `EventhouseSink` -- a configured `telemetry.lakehouse`
block was silently inert. These tests exercise the real CLI end to end,
mirroring test_telemetry_reporting.py's style, plus the `config --show`/
`doctor` row-shape contracts mirroring test_lakehouse_telemetry_config.py.

    pytest -m telemetry tests/test_lakehouse_telemetry_wiring.py
"""

from __future__ import annotations

import json
import sys

import pytest

from fab_test.scripts._telemetry import (
    ENABLE_VAR,
    EVENTHOUSE_DATABASE_VAR,
    EVENTHOUSE_URI_VAR,
    LAKEHOUSE_NAME_VAR,
    LAKEHOUSE_WORKSPACE_VAR,
    lakehouse_rows,
)

_EVENTHOUSE_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"
_WORKSPACE = "analytics-ws"
_LAKEHOUSE = "TelemetryLakehouse"

_EVENTHOUSE_ONLY_YAML = (
    f"telemetry:\n  eventhouse:\n    uri: {_EVENTHOUSE_URI}\n    database: fabric_ops\n"
)
_LAKEHOUSE_ONLY_YAML = f"telemetry:\n  lakehouse:\n    workspace: {_WORKSPACE}\n    lakehouse: {_LAKEHOUSE}\n"
_BOTH_YAML = (
    f"telemetry:\n"
    f"  eventhouse:\n    uri: {_EVENTHOUSE_URI}\n    database: fabric_ops\n"
    f"  lakehouse:\n    workspace: {_WORKSPACE}\n    lakehouse: {_LAKEHOUSE}\n"
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for var in (
        EVENTHOUSE_URI_VAR,
        EVENTHOUSE_DATABASE_VAR,
        LAKEHOUSE_WORKSPACE_VAR,
        LAKEHOUSE_NAME_VAR,
        ENABLE_VAR,
    ):
        monkeypatch.delenv(var, raising=False)


def _artifacts(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.SemanticModel").mkdir(parents=True)
    return artifact_dir


def _run(tmp_path, monkeypatch, *, config: str, argv_extra=()):
    """Run `fab-test pql_lint` over one artifact, returning (exit_code, output_dir)."""
    from fab_test.scripts import fab_test as fab_test_module

    artifact_dir = _artifacts(tmp_path)
    output_dir = tmp_path / "fab-test-results"
    config_path = tmp_path / "fab-test.yml"
    config_path.write_text(config, encoding="utf-8")
    argv = [
        "fab-test",
        "--config",
        str(config_path),
        "pql_lint",
        "--artifact-dir",
        str(artifact_dir),
        "--output-dir",
        str(output_dir),
        *argv_extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return fab_test_module.main(), output_dir


def _fail_eventhouse(monkeypatch, message="cluster unreachable"):
    from fab_test.scripts import eventhouse_logger

    monkeypatch.setattr(
        eventhouse_logger.EventhouseSink, "_ensure_destination", lambda self, table: None
    )

    def _boom(self, table, rows):
        raise RuntimeError(message)

    monkeypatch.setattr(eventhouse_logger.EventhouseSink, "_ingest", _boom)


def _fail_lakehouse(monkeypatch, message="onelake unreachable"):
    from fab_test.scripts import lakehouse_logger

    def _boom(self, table, rows):
        raise RuntimeError(message)

    monkeypatch.setattr(lakehouse_logger.LakehouseSink, "_write", _boom)


def _succeed_lakehouse(monkeypatch):
    from fab_test.scripts import lakehouse_logger

    monkeypatch.setattr(lakehouse_logger.LakehouseSink, "_write", lambda self, table, rows: None)


def _succeed_eventhouse(monkeypatch):
    from fab_test.scripts import eventhouse_logger

    monkeypatch.setattr(
        eventhouse_logger.EventhouseSink, "_ensure_destination", lambda self, table: None
    )
    monkeypatch.setattr(eventhouse_logger.EventhouseSink, "_ingest", lambda self, table, rows: None)


# --------------------------------------------------------------------------
# config --show
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_lakehouse_rows_are_empty_when_unconfigured():
    """Given no Lakehouse telemetry, should add no `config --show` rows."""
    assert lakehouse_rows({}) == []


@pytest.mark.telemetry
def test_lakehouse_rows_name_workspace_and_lakehouse_and_their_origin():
    """Given a configured Lakehouse, should show both keys with their resolution origin."""
    file_config = {"telemetry": {"lakehouse": {"workspace": _WORKSPACE, "lakehouse": _LAKEHOUSE}}}

    rows = lakehouse_rows(file_config)

    keys = {row["key"]: row for row in rows}
    assert keys["telemetry.lakehouse.workspace"]["value"] == _WORKSPACE
    assert keys["telemetry.lakehouse.workspace"]["origin"] == "fab-test.yml:telemetry.lakehouse.workspace"
    assert keys["telemetry.lakehouse.lakehouse"]["value"] == _LAKEHOUSE


@pytest.mark.telemetry
def test_config_show_includes_lakehouse_rows(tmp_path, monkeypatch, capsys):
    """Given a real `config --show` run, should print the Lakehouse rows too."""
    from fab_test.scripts import fab_test as fab_test_module

    config_path = tmp_path / "fab-test.yml"
    config_path.write_text(_LAKEHOUSE_ONLY_YAML, encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["fab-test", "--config", str(config_path), "config", "--show"]
    )

    fab_test_module.main()

    captured = capsys.readouterr().out
    assert "telemetry.lakehouse.workspace" in captured
    assert _WORKSPACE in captured


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_doctor_shows_a_lakehouse_row_and_no_eventhouse_row_when_only_lakehouse_is_configured(
    tmp_path, monkeypatch, capsys
):
    """Given only Lakehouse is configured, should print `telemetry-lakehouse` and not `telemetry-eventhouse`."""
    from fab_test.scripts import fab_test as fab_test_module

    config_path = tmp_path / "fab-test.yml"
    config_path.write_text(_LAKEHOUSE_ONLY_YAML, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["fab-test", "--config", str(config_path), "doctor"])

    fab_test_module.main()

    captured = capsys.readouterr().out
    assert "telemetry-lakehouse" in captured
    assert "telemetry-eventhouse" not in captured


@pytest.mark.telemetry
def test_doctor_shows_both_rows_when_both_are_configured(tmp_path, monkeypatch, capsys):
    """Given both destinations, should print one row for each."""
    from fab_test.scripts import fab_test as fab_test_module

    config_path = tmp_path / "fab-test.yml"
    config_path.write_text(_BOTH_YAML, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["fab-test", "--config", str(config_path), "doctor"])

    fab_test_module.main()

    captured = capsys.readouterr().out
    assert "telemetry-eventhouse" in captured
    assert "telemetry-lakehouse" in captured


@pytest.mark.telemetry
def test_doctor_still_shows_the_single_legacy_row_when_neither_is_configured(
    tmp_path, monkeypatch, capsys
):
    """Given neither destination, should keep the one plain `telemetry` row, not two."""
    from fab_test.scripts import fab_test as fab_test_module

    monkeypatch.setattr(sys, "argv", ["fab-test", "doctor"])

    fab_test_module.main()

    captured = capsys.readouterr().out
    assert "telemetry-eventhouse" not in captured
    assert "telemetry-lakehouse" not in captured
    assert "telemetry: not configured" in captured


# --------------------------------------------------------------------------
# A real run: both sinks, independent delivery
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_lakehouse_only_delivers_when_only_lakehouse_is_configured(tmp_path, monkeypatch):
    """Given only Lakehouse is configured, should deliver to it with no Eventhouse involved."""
    _succeed_lakehouse(monkeypatch)

    _, output_dir = _run(tmp_path, monkeypatch, config=_LAKEHOUSE_ONLY_YAML)

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["telemetry_error"] is None


@pytest.mark.telemetry
def test_one_failed_sink_does_not_block_the_other_from_delivering(tmp_path, monkeypatch, capsys):
    """Given both are configured and Eventhouse fails, should still deliver to Lakehouse.

    Two independent, optional destinations means one going down cannot take
    the other with it -- the whole point of the epic's "additive, not
    coupled" design.
    """
    _fail_eventhouse(monkeypatch, message="cluster unreachable")
    _succeed_lakehouse(monkeypatch)

    _, output_dir = _run(tmp_path, monkeypatch, config=_BOTH_YAML)

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert "cluster unreachable" in manifest["telemetry_error"]
    captured = capsys.readouterr()
    assert (captured.err + captured.out).count("cluster unreachable") == 1


@pytest.mark.telemetry
def test_both_sinks_failing_report_one_warning_each(tmp_path, monkeypatch, capsys):
    """Given both destinations fail, should name both failures, not just one."""
    _fail_eventhouse(monkeypatch, message="cluster unreachable")
    _fail_lakehouse(monkeypatch, message="onelake unreachable")

    _, output_dir = _run(tmp_path, monkeypatch, config=_BOTH_YAML)

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert "cluster unreachable" in manifest["telemetry_error"]
    assert "onelake unreachable" in manifest["telemetry_error"]
    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "cluster unreachable" in output
    assert "onelake unreachable" in output


@pytest.mark.telemetry
def test_a_single_configured_destination_keeps_the_original_unprefixed_error(
    tmp_path, monkeypatch
):
    """Given only Eventhouse is configured and it fails, should not change the existing message shape.

    Backward compatibility: `telemetry_error`'s documented contract is a
    plain failure string, and existing callers already parse this exact
    Eventhouse-only shape.
    """
    _fail_eventhouse(monkeypatch, message="cluster unreachable")

    _, output_dir = _run(tmp_path, monkeypatch, config=_EVENTHOUSE_ONLY_YAML)

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["telemetry_error"] == "cluster unreachable"


@pytest.mark.telemetry
def test_a_requested_run_with_neither_destination_names_both_ways_to_fix_it(
    tmp_path, monkeypatch, capsys
):
    """Given the legacy switch and no address at all, should name both destinations.

    Supersedes the single-destination wording test_telemetry_reporting.py
    pinned before a second destination existed.
    """
    monkeypatch.setenv(ENABLE_VAR, "true")

    _run(tmp_path, monkeypatch, config="")

    captured = capsys.readouterr()
    assert "no Eventhouse or Lakehouse destination is configured" in captured.err + captured.out


# --------------------------------------------------------------------------
# --telemetry --dry-run
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_dry_run_preview_names_both_destinations_when_both_are_configured(
    tmp_path, monkeypatch, capsys
):
    """Given both destinations and --dry-run, should preview both, not just Eventhouse."""
    _run(
        tmp_path,
        monkeypatch,
        config=_BOTH_YAML,
        argv_extra=("--telemetry", "--dry-run"),
    )

    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert _EVENTHOUSE_URI in output
    assert _WORKSPACE in output
    assert _LAKEHOUSE in output
