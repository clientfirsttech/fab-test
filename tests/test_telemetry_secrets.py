"""Contract tests for secrets and telemetry (Eventhouse Shipping §8).

Scope
-----
The secrets constraint puts telemetry on the same footing as stdout, the
result envelopes, and the run manifest: a credential never appears in any of
them. Telemetry adds two new places one could leak — the payload on the
wire, and an SDK error quoting the connection string that produced it.

    pytest -m telemetry tests/test_telemetry_secrets.py
"""

from __future__ import annotations

import json
import sys

import pytest

from fab_test.scripts._telemetry import (
    ENABLE_VAR,
    EVENTHOUSE_DATABASE_VAR,
    EVENTHOUSE_URI_VAR,
)
from fab_test.scripts.eventhouse_logger import describe_ingest_failure

_SECRET = "s3cret-client-secret-value"
_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"
_CONFIG_YAML = f"telemetry:\n  eventhouse:\n    uri: {_URI}\n    database: fabric_ops\n"


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    """A live-looking service principal, so redaction has something to find."""
    for var in (EVENTHOUSE_URI_VAR, EVENTHOUSE_DATABASE_VAR, ENABLE_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_ID", "client-1")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", _SECRET)


# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_no_credential_value_reaches_the_payload(tmp_path, monkeypatch):
    """Given a run with credentials set, should queue no record containing the secret.

    Inspected at the sink rather than after a send, because a leak that only
    a real cluster would witness is the one nobody catches.
    """
    from fab_test.scripts import eventhouse_logger
    from fab_test.scripts import fab_test as fab_test_module

    queued: list[dict] = []
    monkeypatch.setattr(
        eventhouse_logger.EventhouseSink, "_ensure_destination", lambda self, table: None
    )
    monkeypatch.setattr(
        eventhouse_logger.EventhouseSink,
        "_ingest",
        lambda self, table, rows: queued.extend(rows),
    )

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.SemanticModel").mkdir(parents=True)
    config = tmp_path / "fab-test.yml"
    config.write_text(_CONFIG_YAML, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "--config", str(config), "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(tmp_path / "fab-test-results"),
        ],
    )

    fab_test_module.main()

    assert queued, "the test proves nothing if no record was queued"
    assert _SECRET not in json.dumps(queued)


# --------------------------------------------------------------------------
# The error path
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_an_sdk_error_quoting_the_connection_string_is_redacted():
    """Given an error containing the secret, should not repeat it.

    Kusto builds its connection string from the credential and can quote it
    back in a failure.
    """
    described = describe_ingest_failure(
        Exception(f"auth failed: Data Source=...;AppKey={_SECRET};Authority Id=tenant-1")
    )

    assert _SECRET not in described
    assert "<redacted>" in described


@pytest.mark.telemetry
def test_the_redacted_failure_reaches_the_manifest_and_the_log_already_redacted(
    tmp_path, monkeypatch, capsys
):
    """Given a failing ingest whose error quotes the secret, should leak it nowhere.

    Both destinations in one test on purpose: redacting for the console and
    forgetting the manifest is exactly the shape of leak this guards.
    """
    from fab_test.scripts import eventhouse_logger
    from fab_test.scripts import fab_test as fab_test_module

    def _boom(self, table, rows):
        raise RuntimeError(f"connection refused for AppKey={_SECRET}")

    monkeypatch.setattr(
        eventhouse_logger.EventhouseSink, "_ensure_destination", lambda self, table: None
    )
    monkeypatch.setattr(eventhouse_logger.EventhouseSink, "_ingest", _boom)

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.SemanticModel").mkdir(parents=True)
    config = tmp_path / "fab-test.yml"
    config.write_text(_CONFIG_YAML, encoding="utf-8")
    output_dir = tmp_path / "fab-test-results"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "--config", str(config), "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
        ],
    )

    fab_test_module.main()

    captured = capsys.readouterr()
    manifest = (output_dir / "run.json").read_text(encoding="utf-8")
    assert _SECRET not in captured.out + captured.err
    assert _SECRET not in manifest
    assert "AppKey=<redacted>" in manifest, "the failure should still be reported, just redacted"


# --------------------------------------------------------------------------
# The dry-run preview
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_the_dry_run_names_the_destination_but_never_the_secret(tmp_path, monkeypatch, capsys):
    """Given --dry-run, should print where it would go without printing how it gets in."""
    from fab_test.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "Sales.SemanticModel").mkdir(parents=True)
    config = tmp_path / "fab-test.yml"
    config.write_text(_CONFIG_YAML, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "--config", str(config), "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(tmp_path / "fab-test-results"),
            "--dry-run",
        ],
    )

    fab_test_module.main()

    captured = capsys.readouterr()
    assert _URI in captured.out + captured.err, "the destination is the point of the preview"
    assert _SECRET not in captured.out + captured.err


# --------------------------------------------------------------------------
# config --show
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_config_show_never_prints_a_credential(tmp_path, monkeypatch, capsys):
    """Given credentials in the environment, should report the address and not the secret."""
    from fab_test.scripts import fab_test as fab_test_module

    config = tmp_path / "fab-test.yml"
    config.write_text(_CONFIG_YAML, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["fab-test", "--config", str(config), "config", "--show", "--format", "json"],
    )

    fab_test_module.main()

    assert _SECRET not in capsys.readouterr().out
