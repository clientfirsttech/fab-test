"""Telemetry payload: gating, schema validation, dry-run preview, regressions.

Scope
-----
_telemetry_enabled's flag/env/configured-destination gating,
_validate_telemetry_payload's required-field schema check, --telemetry
--dry-run's preview-not-sent behavior, and regression coverage for a
network failure never affecting the analyzer's own exit code.

    pytest -m fab_test
"""
import json
from pathlib import Path

import pytest

from fab_test.scripts.fab_test import (
    _git_context,
    _run_analyzer,
    _send_telemetry,
    _telemetry_enabled,
    _validate_telemetry_payload,
)
from tests.conftest import (
    _clear_github_env,
    _fake_git_run,
    _RunAnalyzerArgs,
    _stub_subprocess_run,
)

# --------------------------------------------------------------------------- #
# Telemetry gating
# --------------------------------------------------------------------------- #


class _TelemetryArgs:
    """Args carrying a configured destination unless a test says otherwise.

    Since Eventhouse Shipping §2, being enabled means having somewhere to
    send: a configured destination is what turns telemetry on, and the flags
    and ENABLE_EVENTHOUSE_LOGGING decide whether to use it. These tests are
    about that second half, so they supply the first.
    """

    def __init__(self, telemetry=None, configured=True):
        self.telemetry = telemetry
        self.file_config = (
            {
                "telemetry": {
                    "eventhouse": {
                        "uri": "https://trd-abc123.z9.kusto.fabric.microsoft.com",
                        "database": "fabric_ops",
                    }
                }
            }
            if configured
            else {}
        )


@pytest.mark.fab_test
def test_telemetry_enabled_false_arg_overrides_env(monkeypatch):
    """--no-telemetry suppresses telemetry even when env var is true."""
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    args = _TelemetryArgs(telemetry=False)
    assert _telemetry_enabled(args) is False


@pytest.mark.fab_test
def test_telemetry_enabled_true_arg_overrides_env(monkeypatch):
    """--telemetry forces telemetry even when env var is false."""
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "false")
    args = _TelemetryArgs(telemetry=True)
    assert _telemetry_enabled(args) is True


@pytest.mark.fab_test
def test_telemetry_enabled_defaults_to_env(monkeypatch):
    """When no arg is provided, telemetry follows ENABLE_EVENTHOUSE_LOGGING."""
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    args = _TelemetryArgs(telemetry=None)
    assert _telemetry_enabled(args) is True

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "false")
    assert _telemetry_enabled(args) is False


@pytest.mark.fab_test
def test_telemetry_needs_somewhere_to_send(monkeypatch):
    """Given no configured destination, should not be enabled however it was asked for.

    The legacy variable still *asks* for telemetry — it simply has nowhere to
    put it, which §6 reports rather than shipping into the void as the
    placeholder used to.
    """
    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    assert _telemetry_enabled(_TelemetryArgs(telemetry=None, configured=False)) is False


# --------------------------------------------------------------------------- #
# Validate telemetry payload schema
# --------------------------------------------------------------------------- #


def _valid_telemetry_payload(**overrides):
    payload = {
        "timestamp": "2026-08-18T12:00:00",
        "artifact_name": "SampleModel",
        "artifact_type": "SemanticModel",
        "analyzer": "bpa",
        "status": "passed",
        "commit_sha": "abc123",
        "workflow_run_id": "",
        "repository": "",
        "actor": "",
        "branch": "",
        "origin": "local",
    }
    payload.update(overrides)
    return payload


@pytest.mark.fab_test
def test_validate_telemetry_payload_passes_through_valid_payload():
    """A fully-formed payload is returned unchanged (aside from key order)."""
    payload = _valid_telemetry_payload()
    assert _validate_telemetry_payload(payload) == payload


@pytest.mark.fab_test
def test_validate_telemetry_payload_returns_none_when_required_field_missing(capsys):
    """A payload missing a required field is skipped, with a warning logged."""
    payload = _valid_telemetry_payload()
    del payload["status"]

    result = _validate_telemetry_payload(payload)
    captured = capsys.readouterr()

    assert result is None
    assert "status" in captured.out


@pytest.mark.fab_test
def test_validate_telemetry_payload_reports_all_missing_required_fields(capsys):
    """The warning lists every missing required field, not just the first."""
    payload = _valid_telemetry_payload()
    del payload["analyzer"]
    del payload["timestamp"]

    result = _validate_telemetry_payload(payload)
    captured = capsys.readouterr()

    assert result is None
    assert "analyzer" in captured.out
    assert "timestamp" in captured.out


@pytest.mark.fab_test
def test_validate_telemetry_payload_drops_malformed_optional_field():
    """A malformed (non-JSON-serializable) optional field is dropped, not fatal."""
    payload = _valid_telemetry_payload(weird_field={1, 2, 3})

    result = _validate_telemetry_payload(payload)

    assert result is not None
    assert "weird_field" not in result
    assert result["status"] == "passed"
    assert result["analyzer"] == "bpa"


@pytest.mark.fab_test
def test_send_telemetry_skips_and_warns_on_invalid_payload(monkeypatch, capsys):
    """_send_telemetry skips sending and warns, without raising, on invalid payload."""
    from fab_test.scripts import fab_test_telemetry

    monkeypatch.setattr(fab_test_telemetry, "_telemetry_enabled", lambda args: True)
    monkeypatch.setattr(
        fab_test_telemetry,
        "_build_telemetry_payload",
        lambda *a, **k: _valid_telemetry_payload(status=""),  # falsy -> "missing"
    )
    calls = []
    monkeypatch.setattr(
        fab_test_telemetry,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    _send_telemetry("bpa", Path("SampleModel.SemanticModel"), {"findings": []}, _TelemetryArgs())
    captured = capsys.readouterr()

    assert calls == []
    assert "status" in captured.out


@pytest.mark.fab_test
def test_send_telemetry_sends_valid_payload(monkeypatch):
    """A valid payload still reaches publish_analyzer_telemetry as before."""
    from fab_test.scripts import fab_test_telemetry

    monkeypatch.setattr(fab_test_telemetry, "_telemetry_enabled", lambda args: True)
    monkeypatch.setattr(
        fab_test_telemetry,
        "_build_telemetry_payload",
        lambda *a, **k: _valid_telemetry_payload(),
    )
    calls = []
    monkeypatch.setattr(
        fab_test_telemetry,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    _send_telemetry("bpa", Path("SampleModel.SemanticModel"), {"findings": []}, _TelemetryArgs())

    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Telemetry dry-run inspection
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_dry_run_with_telemetry_prints_payload_preview_not_sent(tmp_path, monkeypatch, capsys):
    """--telemetry --dry-run prints the payload preview instead of sending it.

    Uses the default --format json, so the preview is narrated to stderr,
    while stdout carries only the dry-run JSON summary (CLI Agent Ergonomics).
    """
    from fab_test.scripts import fab_test_telemetry

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    calls = []
    monkeypatch.setattr(
        fab_test_telemetry,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=True, dry_run=True)
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert calls == [], "telemetry must never be transmitted during --dry-run"
    summary = json.loads(captured.out)
    assert summary["analyzer"] == "pql_lint"
    assert summary["dry_run"] is True
    assert "Telemetry preview" in captured.err
    assert '"analyzer": "pql_lint"' in captured.err
    assert '"artifact_name": "SampleModel"' in captured.err


@pytest.mark.fab_test
def test_dry_run_without_telemetry_flag_shows_no_preview(tmp_path, monkeypatch, capsys):
    """Plain --dry-run with telemetry unconfigured prints no telemetry preview.

    `configured_telemetry=False` is load-bearing since §2: a configured
    destination is itself the enablement, so "no --telemetry flag" alone no
    longer means telemetry is off.
    """
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.delenv("ENABLE_EVENTHOUSE_LOGGING", raising=False)
    args = _RunAnalyzerArgs(
        artifact_dir, output_dir, telemetry=None, dry_run=True, configured_telemetry=False
    )
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "Telemetry preview" not in captured.out
    assert "Telemetry preview" not in captured.err


@pytest.mark.fab_test
def test_dry_run_no_telemetry_flag_suppresses_preview_even_with_env(
    tmp_path, monkeypatch, capsys
):
    """--no-telemetry suppresses the dry-run preview even if the env flag is on."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=False, dry_run=True)
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "Telemetry preview" not in captured.out
    assert "Telemetry preview" not in captured.err


@pytest.mark.fab_test
def test_telemetry_sent_normally_when_not_dry_run(tmp_path, monkeypatch):
    """--telemetry with ENABLE_EVENTHOUSE_LOGGING=true still sends for real runs."""
    from fab_test.scripts import fab_test_execution, fab_test_telemetry

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    monkeypatch.setattr(
        fab_test_execution.subprocess, "run", _stub_subprocess_run
    )
    calls = []
    monkeypatch.setattr(
        fab_test_telemetry,
        "publish_analyzer_telemetry",
        lambda *a, **k: calls.append(a),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=None, dry_run=False)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Regression tests for telemetry context
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_git_context_mocked_local_git_returns_branch_and_actor(monkeypatch):
    """A mocked local git environment yields both branch and actor via git."""
    from fab_test.scripts import _git_context as _git_context_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        _git_context_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse HEAD": "deadbeef\n",
                "rev-parse --abbrev-ref HEAD": "feature/x\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )
    ctx = _git_context()
    assert ctx["branch"] == "feature/x"
    assert ctx["actor"] == "dev@example.com"


@pytest.mark.fab_test
def test_git_context_github_actions_env_preferred_over_local_git(monkeypatch):
    """GitHub Actions env vars win over local git output when both are present."""
    from fab_test.scripts import _git_context as _git_context_module

    _clear_github_env(monkeypatch)
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_ACTOR", "ci-bot")
    monkeypatch.setattr(
        _git_context_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse --abbrev-ref HEAD": "local-branch\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )
    ctx = _git_context()
    assert ctx["branch"] == "main"
    assert ctx["actor"] == "ci-bot"


@pytest.mark.fab_test
def test_telemetry_send_network_failure_does_not_affect_analyzer_exit_code(
    tmp_path, monkeypatch, capsys
):
    """A telemetry network failure is swallowed; the analyzer's own exit code stands."""
    from fab_test.scripts import fab_test_execution, fab_test_telemetry

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"
    envelope_dir = output_dir / "pql_lint" / "SampleModel"
    envelope_dir.mkdir(parents=True)
    envelope_dir_json = envelope_dir / "envelope.json"
    envelope_dir_json.write_text(
        json.dumps(
            {
                "status": "failed",
                "findings": [
                    {"rule": "R1", "severity": "Error", "object": "T", "message": "m"}
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ENABLE_EVENTHOUSE_LOGGING", "true")
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _stub_subprocess_run)
    monkeypatch.setattr(
        fab_test_telemetry,
        "publish_analyzer_telemetry",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("network unreachable")),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, telemetry=None, dry_run=False)
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 1  # driven by the Error-severity finding, not the telemetry failure
    assert "Telemetry failed" in captured.err  # default --format json narrates to stderr


