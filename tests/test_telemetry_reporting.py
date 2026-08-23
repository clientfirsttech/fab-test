"""Contract tests for how telemetry failure is reported (Eventhouse Shipping §6).

Scope
-----
Telemetry must not fail a run, and must not claim to have worked. The
placeholder did the second: it returned True for a send that never happened,
so even the handler that would have warned was told it succeeded.

    pytest -m telemetry tests/test_telemetry_reporting.py
    pytest -m telemetry tests/test_telemetry_reporting.py -k once
"""

from __future__ import annotations

import json
import sys

import pytest

from fabric_ci_cd_dataops.scripts._telemetry import (
    ENABLE_VAR,
    EVENTHOUSE_DATABASE_VAR,
    EVENTHOUSE_URI_VAR,
)

_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"
_CONFIG_YAML = f"telemetry:\n  eventhouse:\n    uri: {_URI}\n    database: fabric_ops\n"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for var in (EVENTHOUSE_URI_VAR, EVENTHOUSE_DATABASE_VAR, ENABLE_VAR):
        monkeypatch.delenv(var, raising=False)


def _artifacts(tmp_path):
    """Three semantic models, so a per-artifact warning is distinguishable."""
    artifact_dir = tmp_path / "artifacts"
    for name in ("Sales", "Finance", "Ops"):
        (artifact_dir / f"{name}.SemanticModel").mkdir(parents=True)
    return artifact_dir


def _run(tmp_path, monkeypatch, *, config: str | None = _CONFIG_YAML, argv_extra=()):
    """Run `fab-test pql_lint` over three artifacts, returning the output dir."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = _artifacts(tmp_path)
    output_dir = tmp_path / "analyzer-results"
    argv = ["fab-test"]
    if config is not None:
        config_path = tmp_path / "fab-test.yml"
        config_path.write_text(config, encoding="utf-8")
        argv += ["--config", str(config_path)]
    argv += [
        "pql_lint",
        "--artifact-dir", str(artifact_dir),
        "--output-dir", str(output_dir),
        *argv_extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return fab_test_module.main(), output_dir


def _fail_ingest(monkeypatch, message="cluster unreachable"):
    """Make every ingest attempt fail, without a network call."""
    from fabric_ci_cd_dataops.scripts import eventhouse_logger

    def _boom(self, table, rows):
        raise RuntimeError(message)

    # The destination check needs a cluster; whether the table exists has
    # its own tests in test_telemetry_bootstrap.py.
    monkeypatch.setattr(
        eventhouse_logger.EventhouseSink, "_ensure_destination", lambda self, table: None
    )
    monkeypatch.setattr(eventhouse_logger.EventhouseSink, "_ingest", _boom)


# --------------------------------------------------------------------------
# Non-blocking
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_an_ingest_failure_does_not_change_the_exit_code(tmp_path, monkeypatch):
    """Given telemetry fails, should let the analyzer's own exit code stand.

    Compared against the same run with telemetry off rather than against a
    literal: whatever pqlint decides about these artifacts is the analyzer's
    business, and the point is that telemetry does not alter it. A
    diagnostic feature must never be able to fail a build.
    """
    without_telemetry, _ = _run(tmp_path / "baseline", monkeypatch, config=None)

    _fail_ingest(monkeypatch)
    with_failed_telemetry, _ = _run(tmp_path / "failing", monkeypatch)

    assert with_failed_telemetry == without_telemetry


# --------------------------------------------------------------------------
# Once per run
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_an_unreachable_cluster_is_reported_once_not_once_per_artifact(
    tmp_path, monkeypatch, capsys
):
    """Given three artifacts and one unreachable cluster, should warn once.

    Three identical warnings for one problem is noise that hides the next
    one, and the count scales with the repository rather than the fault.
    """
    _fail_ingest(monkeypatch)

    _run(tmp_path, monkeypatch)

    captured = capsys.readouterr()
    assert (captured.err + captured.out).count("cluster unreachable") == 1


# --------------------------------------------------------------------------
# Never silent
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_requested_run_with_no_destination_says_so(tmp_path, monkeypatch, capsys):
    """Given the legacy switch and no address, should warn rather than do nothing quietly.

    This is the combination every existing caller has today. It cannot fail
    the run, and it must not silently discard records the way the
    placeholder did.
    """
    monkeypatch.setenv(ENABLE_VAR, "true")

    _run(tmp_path, monkeypatch, config=None)

    captured = capsys.readouterr()
    assert "no Eventhouse destination is configured" in captured.err + captured.out


@pytest.mark.telemetry
def test_a_run_that_never_asked_for_telemetry_says_nothing(tmp_path, monkeypatch, capsys):
    """Given no telemetry configured or requested, should add no telemetry output at all.

    Unconfigured is not broken, and a warning on every run of a laptop tool
    trains people to ignore warnings.
    """
    _run(tmp_path, monkeypatch, config=None)

    captured = capsys.readouterr()
    assert "elemetry" not in captured.err + captured.out


# --------------------------------------------------------------------------
# The manifest records it
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_the_manifest_records_that_telemetry_was_lost(tmp_path, monkeypatch):
    """Given an ingest failure, should record it in run.json.

    A pipeline reading only the manifest could otherwise not tell a run
    whose telemetry landed from one whose records were dropped.
    """
    _fail_ingest(monkeypatch)

    _, output_dir = _run(tmp_path, monkeypatch)

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert "cluster unreachable" in manifest["telemetry_error"]


@pytest.mark.telemetry
def test_the_manifest_says_nothing_when_no_telemetry_was_asked_for(tmp_path, monkeypatch):
    """Given no telemetry, should leave the field null rather than inventing a failure."""
    _, output_dir = _run(tmp_path, monkeypatch, config=None)

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["telemetry_error"] is None


# --------------------------------------------------------------------------
# stdout stays one JSON document
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_telemetry_warnings_never_touch_stdout_under_format_json(tmp_path, monkeypatch, capsys):
    """Given --format json, should keep telemetry narration on stderr.

    The JSON stdout guarantee is a contract with the agent caller; a warning
    in the middle of the document breaks every parser reading it.
    """
    _fail_ingest(monkeypatch)

    _run(tmp_path, monkeypatch, argv_extra=("--format", "json"))

    captured = capsys.readouterr()
    json.loads(captured.out)  # must parse: one document, nothing else
    assert "cluster unreachable" in captured.err
