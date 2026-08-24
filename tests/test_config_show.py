"""Contract tests for `fab-test config --show` (Config Consolidation §5).

Scope
-----
Answers "where did this value come from?" without reading source. Always
passes on any machine -- no external tool or artifact required.

    pytest -m fab_test tests/test_config_show.py
"""

import json
import os
import subprocess

import pytest

from fabric_ci_cd_dataops.scripts.fab_test_summary import _print_config_show

_EXPECTED_KEYS = {
    "artifact_dir",
    "output_dir",
    "jobs",
    "format",
    "timeout",
    "environment",
    "workspace",
}

# Resolved by metadata layer rather than by flag/env/config, so their origins
# name a directory (`.fab-test/metadata`, `.github/metadata`, `packaged`)
# instead of the flag/env vocabulary. Listed separately so the exact-equality
# assertion below stays a real guard against an accidental extra row.
_EXPECTED_RULESET_KEYS = {"rules.bpa", "rules.pbir"}


@pytest.mark.fab_test
def test_config_show_lists_every_setting_text_format():
    """fab-test config --show prints every effective setting."""
    result = subprocess.run(
        ["fab-test", "config", "--show"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for key in _EXPECTED_KEYS | _EXPECTED_RULESET_KEYS:
        assert key in result.stdout, f"missing '{key}' in:\n{result.stdout}"


@pytest.mark.fab_test
def test_config_show_json_has_every_setting_with_origin():
    """--format json emits one document; every setting has value + origin."""
    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    keys_seen = {row["key"] for row in data["settings"]}
    assert keys_seen == _EXPECTED_KEYS | _EXPECTED_RULESET_KEYS
    for row in data["settings"]:
        assert "value" in row
        assert "origin" in row


@pytest.mark.fab_test
def test_config_show_reports_env_origin_for_timeout(monkeypatch):
    """ANALYZER_TIMEOUT set: timeout's origin is env:ANALYZER_TIMEOUT."""
    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "ANALYZER_TIMEOUT": "77"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    timeout_row = next(row for row in data["settings"] if row["key"] == "timeout")
    assert timeout_row["value"] == 77
    assert timeout_row["origin"] == "env:ANALYZER_TIMEOUT"


@pytest.mark.fab_test
def test_config_show_reports_default_origin_when_nothing_set(tmp_path):
    """With no env vars and no config file, timeout's origin is 'default'."""
    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={k: v for k, v in os.environ.items() if k != "ANALYZER_TIMEOUT"},
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    timeout_row = next(row for row in data["settings"] if row["key"] == "timeout")
    assert timeout_row["origin"] == "default"
    assert timeout_row["value"] == 200


@pytest.mark.fab_test
def test_config_show_reports_config_file_origin(tmp_path):
    """A fab-test.yml value shows origin fab-test.yml:key."""
    (tmp_path / "fab-test.yml").write_text("timeout: 45\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    timeout_row = next(row for row in data["settings"] if row["key"] == "timeout")
    assert timeout_row["value"] == 45
    assert timeout_row["origin"] == "fab-test.yml:timeout"


@pytest.mark.fab_test
def test_config_show_reports_env_origin_for_workspace(monkeypatch):
    """FABRIC_WORKSPACE_ID set: workspace's origin names the env var, not the file.

    `workspace:` works today (Artifact Targeting §3) but was undiscoverable
    -- absent from `_SETTING_SPECS` and therefore from `config --show`. A
    setting that cannot be found is a setting that does not exist.
    """
    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "FABRIC_WORKSPACE_ID": "11111111-1111-1111-1111-111111111111"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    workspace_row = next(row for row in data["settings"] if row["key"] == "workspace")
    assert workspace_row["value"] == "11111111-1111-1111-1111-111111111111"
    assert workspace_row["origin"] == "env:FABRIC_WORKSPACE_ID"


@pytest.mark.fab_test
def test_config_show_reports_config_file_origin_for_workspace(tmp_path):
    """`workspace:` set in fab-test.yml shows origin fab-test.yml:workspace."""
    (tmp_path / "fab-test.yml").write_text("workspace: Sales Dev\n", encoding="utf-8")

    result = subprocess.run(
        ["fab-test", "config", "--show", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={k: v for k, v in os.environ.items() if k != "FABRIC_WORKSPACE_ID"},
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    workspace_row = next(row for row in data["settings"] if row["key"] == "workspace")
    assert workspace_row["value"] == "Sales Dev"
    assert workspace_row["origin"] == "fab-test.yml:workspace"


# --------------------------------------------------------------------------- #
# _print_config_show and secret redaction
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_print_config_show_json_shape(capsys):
    """_print_config_show emits {"settings": [...]} under --format json."""
    rows = [{"key": "jobs", "value": 1, "origin": "default"}]

    exit_code = _print_config_show(rows, output_format="json")

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"settings": rows}
    assert exit_code == 0


@pytest.mark.fab_test
def test_print_config_show_text_mentions_key_value_and_origin(capsys):
    """Text format shows the key, its value, and its origin."""
    rows = [{"key": "timeout", "value": 45, "origin": "fab-test.yml:timeout"}]

    _print_config_show(rows, output_format="text")

    captured = capsys.readouterr()
    assert "timeout" in captured.out
    assert "45" in captured.out
    assert "fab-test.yml:timeout" in captured.out


@pytest.mark.fab_test
def test_print_config_show_redacts_a_secret_valued_row(capsys):
    """A row already marked as a secret shows its origin but a redacted value."""
    rows = [{"key": "client_secret", "value": "<redacted>", "origin": "env:FABRIC_SERVICE_PRINCIPAL_SECRET"}]

    _print_config_show(rows, output_format="text")

    captured = capsys.readouterr()
    assert "<redacted>" in captured.out
    assert "env:FABRIC_SERVICE_PRINCIPAL_SECRET" in captured.out
