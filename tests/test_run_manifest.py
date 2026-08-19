"""Contract tests for the fab-test run manifest (CLI Agent Ergonomics §11-12).

Scope
-----
`analyzer-results/run.json` is written once per invocation so a caller reads
one file instead of globbing result directories. Always passes on any
machine — no external tool or artifact required.

    pytest -m fab_test tests/test_run_manifest.py
    pytest -m fab_test tests/test_run_manifest.py -k abort
"""

import json
import subprocess
import sys

import pytest

from fabric_ci_cd_dataops.scripts._run_manifest import RunManifest, _sanitize_command

_REQUIRED_KEYS = {
    "schema_version",
    "fab_test_version",
    "command",
    "artifacts",
    "totals",
    "exit_code",
}


@pytest.mark.fab_test
def test_manifest_dict_has_required_keys():
    """to_dict() has every documented top-level key."""
    manifest = RunManifest("1.0.0", ["fab-test", "bpa"])
    manifest.record_artifact("bpa", "SampleModel", "passed", "results/bpa/SampleModel/envelope.json", 0, 0)

    data = manifest.to_dict(exit_code=0)

    assert set(data.keys()) == _REQUIRED_KEYS
    assert data["schema_version"] == 1
    assert data["fab_test_version"] == "1.0.0"
    assert data["exit_code"] == 0
    assert data["artifacts"][0]["analyzer"] == "bpa"
    assert data["artifacts"][0]["envelope_path"].endswith("envelope.json")


@pytest.mark.fab_test
def test_record_artifact_defaults_detail_to_none():
    """detail is null when the artifact completed normally."""
    manifest = RunManifest("1.0.0", ["fab-test", "bpa"])
    manifest.record_artifact("bpa", "SampleModel", "passed", "e.json", 0, 0)

    assert manifest.to_dict(exit_code=0)["artifacts"][0]["detail"] is None


@pytest.mark.fab_test
def test_record_artifact_stores_detail_when_provided():
    """detail carries the failure message through to the manifest."""
    manifest = RunManifest("1.0.0", ["fab-test", "bpa"])
    manifest.record_artifact(
        "bpa", "*", "preflight_failed", None, 0, 0, detail="tool not found"
    )

    assert manifest.to_dict(exit_code=127)["artifacts"][0]["detail"] == "tool not found"


@pytest.mark.fab_test
def test_manifest_totals_sum_across_artifacts():
    """totals.errors/warnings sum every recorded artifact."""
    manifest = RunManifest("1.0.0", ["fab-test", "all"])
    manifest.record_artifact("bpa", "A", "failed", "e1.json", 2, 1)
    manifest.record_artifact("pbir", "B", "passed", "e2.json", 0, 3)

    data = manifest.to_dict(exit_code=1)

    assert data["totals"] == {"errors": 2, "warnings": 4}


@pytest.mark.fab_test
def test_manifest_write_creates_run_json_under_output_dir(tmp_path):
    """write() creates run.json under the given output_dir and returns its path."""
    output_dir = tmp_path / "custom-results"
    manifest = RunManifest("1.0.0", ["fab-test", "bpa"])

    path = manifest.write(output_dir, exit_code=0)

    assert path == output_dir / "run.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["exit_code"] == 0


@pytest.mark.fab_test
def test_sanitize_command_redacts_sensitive_flag_value():
    """A --client-secret/--password/--token/--secret/--api-key value is redacted."""
    command = ["fab-test", "playwright", "--client-secret", "sup3r-s3cret-value"]

    sanitized = _sanitize_command(command)

    assert "sup3r-s3cret-value" not in sanitized
    assert sanitized[-1] == "<redacted>"
    assert sanitized[-2] == "--client-secret"


@pytest.mark.fab_test
def test_sanitize_command_redacts_key_equals_value_form():
    """A single 'token=VALUE'-shaped token has its value redacted."""
    command = ["fab-test", "playwright", "--conn-string", "token=abc123secret"]

    sanitized = _sanitize_command(command)

    assert "abc123secret" not in sanitized[-1]
    assert "token=" in sanitized[-1]


@pytest.mark.fab_test
def test_sanitize_command_leaves_ordinary_args_unchanged():
    """Non-sensitive tokens pass through untouched."""
    command = ["fab-test", "bpa", "--artifact-dir", "/some/path", "--format", "json"]

    assert _sanitize_command(command) == command


@pytest.mark.fab_test
def test_manifest_never_contains_a_redacted_secret_after_write(tmp_path):
    """The written run.json file never contains the raw secret value anywhere."""
    manifest = RunManifest(
        "1.0.0", ["fab-test", "playwright", "--client-secret", "top-secret-xyz"]
    )
    manifest.record_artifact("playwright", "ReportOne", "passed", "e.json", 0, 0)

    path = manifest.write(tmp_path, exit_code=0)
    raw_text = path.read_text(encoding="utf-8")

    assert "top-secret-xyz" not in raw_text


# --------------------------------------------------------------------------- #
# Integration: main() writes the manifest for a real invocation
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_main_writes_run_manifest_for_single_analyzer_dry_run(tmp_path):
    """A real fab-test invocation writes analyzer-results/run.json."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    result = subprocess.run(
        [
            "fab-test", "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest_path = output_dir / "run.json"
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(data.keys()) == _REQUIRED_KEYS
    assert data["exit_code"] == 0


@pytest.mark.fab_test
def test_main_writes_run_manifest_under_custom_output_dir(tmp_path):
    """--output-dir DIR is where the manifest is written, not the default."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    custom_output = tmp_path / "custom" / "results"

    result = subprocess.run(
        [
            "fab-test", "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(custom_output),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (custom_output / "run.json").exists()


@pytest.mark.fab_test
def test_manifest_covers_every_analyzer_in_all_run(tmp_path, monkeypatch):
    """`fab-test all` accumulates manifest entries from every analyzer run,
    not just the last one in the loop.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    (artifact_dir / "SampleModel.Report").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_all_analyzers", lambda: ("bpa", "pbir"))
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module, "_preflight_error", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "all",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
        ],
    )

    fab_test_module.main()

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    analyzers_seen = {a["analyzer"] for a in manifest["artifacts"]}
    assert analyzers_seen == {"bpa", "pbir"}


@pytest.mark.fab_test
def test_manifest_records_preflight_failure_with_exit_code(tmp_path, monkeypatch):
    """A preflight tool-resolution abort still writes a manifest with the
    failure reason and the exit code preflight_error returned.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(
        fab_test_module, "_preflight_error", lambda name, args: ("tool not found", 127)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "bpa",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
        ],
    )

    exit_code = fab_test_module.main()

    assert exit_code == 127
    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["exit_code"] == 127
    assert manifest["artifacts"][0]["status"] == "preflight_failed"
    assert manifest["artifacts"][0]["detail"] == "tool not found"


@pytest.mark.fab_test
def test_manifest_records_timeout_status_for_artifact(tmp_path, monkeypatch):
    """A subprocess timeout is recorded with status 'timeout' for that artifact."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    def _raise_timeout(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(fab_test_module.subprocess, "run", _raise_timeout)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
            "--timeout", "1",
        ],
    )

    fab_test_module.main()

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"][0]["status"] == "timeout"
    assert "1" in manifest["artifacts"][0]["detail"]


@pytest.mark.fab_test
@pytest.mark.parametrize("argv_tail", [["doctor"], ["list"], ["explain", "bpa"]])
def test_main_does_not_construct_manifest_for_admin_subcommands(monkeypatch, argv_tail):
    """Admin/reporting subcommands (doctor, list, explain) never build a RunManifest."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    def _fail_if_constructed(*_a, **_k):
        raise AssertionError(f"RunManifest must not be built for {argv_tail}")

    monkeypatch.setattr(fab_test_module, "RunManifest", _fail_if_constructed)
    monkeypatch.setattr(sys, "argv", ["fab-test", *argv_tail])

    fab_test_module.main()  # must not raise
