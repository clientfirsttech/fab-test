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
    "origin",
    # The resolved target, or null for a discovery run (Artifact Targeting
    # and Auth §5). Additive: `origin` says local vs CI, this says whether
    # the run read files, a Desktop instance, or a workspace.
    "target",
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


# --------------------------------------------------------------------------- #
# origin: local vs CI (Local Desktop First Run §12)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_manifest_origin_defaults_to_unknown_when_not_specified():
    """origin defaults to 'unknown' for callers that don't specify it."""
    manifest = RunManifest("1.0.0", ["fab-test", "bpa"])

    assert manifest.to_dict(exit_code=0)["origin"] == "unknown"


@pytest.mark.fab_test
def test_manifest_records_specified_origin():
    """origin carries through to the manifest exactly as given."""
    manifest = RunManifest("1.0.0", ["fab-test", "bpa"], origin="local")

    assert manifest.to_dict(exit_code=0)["origin"] == "local"


@pytest.mark.fab_test
def test_main_writes_local_origin_outside_ci(tmp_path, monkeypatch):
    """A run with no CI env vars set records origin: local."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    for var in ("GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "AZURE_DEVOPS", "CI"):
        monkeypatch.delenv(var, raising=False)

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
            "--dry-run",
        ],
    )

    fab_test_module.main()

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["origin"] == "local"


@pytest.mark.fab_test
def test_main_writes_ci_origin_under_github_actions(tmp_path, monkeypatch):
    """A run with GITHUB_ACTIONS set records origin: github-actions."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "pql_lint",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
            "--dry-run",
        ],
    )

    fab_test_module.main()

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["origin"] == "github-actions"


@pytest.mark.fab_test
def test_local_missing_prerequisite_skips_without_failing_under_ci(tmp_path, monkeypatch):
    """A missing local prerequisite still degrades to a skip -- not a pipeline
    failure -- even when CI env vars are set.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": False, "reason": "not installed", "remediation": None},
    )

    import argparse

    args = argparse.Namespace(
        analyzer="local",
        artifact_dir=str(tmp_path),
        output_dir=str(tmp_path / "results"),
        dry_run=False,
        artifact=None,
        timeout=None,
        jobs=1,
        output_format="text",
        telemetry=False,
        no_telemetry=True,
        verbose=0,
    )

    exit_code = fab_test_module._run_local(args)

    assert exit_code == 0


# --------------------------------------------------------------------------
# Abort without an envelope (Standalone: run.json failure detail)
#
# An analyzer that exits non-zero before it can write an envelope leaves
# fab-test with nothing but the child's stderr. That message is the whole
# remediation -- "pass --env" -- and of vision's three callers the agent was
# the one left without it: a synthesized `failed` envelope carried no detail,
# so `run.json` as a sole CI artifact said the run failed and not why.
# --------------------------------------------------------------------------


def _stub_analyzer_run(monkeypatch, fab_test_module, *, stderr: str, returncode: int = 1):
    """Replace subprocess.run so the analyzer aborts without writing an envelope."""
    seen: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_run)
    return seen


@pytest.mark.fab_test
def test_manifest_records_stderr_detail_when_analyzer_writes_no_envelope(
    tmp_path, monkeypatch
):
    """Given an analyzer that aborts with no envelope, detail carries its message."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ThinReport.Report").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    _stub_analyzer_run(
        monkeypatch,
        fab_test_module,
        stderr=(
            "::error::No environment given, so there is nothing to resolve "
            "'ThinReport' against. Pass --env, set FABRIC_ENVIRONMENT, or set "
            "`environment:` in fab-test.yml.\n"
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "pbir",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
        ],
    )

    fab_test_module.main()

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    detail = manifest["artifacts"][0]["detail"]
    assert manifest["artifacts"][0]["status"] == "failed"
    assert detail is not None, "an abort with no envelope must say why"
    # The annotation prefix is transport, not message: run.json is read by an
    # agent, not by GitHub's log renderer.
    assert not detail.startswith("::")
    assert "Pass --env" in detail


@pytest.mark.fab_test
def test_manifest_records_detail_in_ci_where_run_json_is_the_only_artifact(
    tmp_path, monkeypatch
):
    """Given a CI run, detail is still captured -- stderr is piped, not inherited.

    This is the case the requirement is actually about. Inheriting stderr in
    CI sends the message to the log and nowhere else, which leaves the one
    file a pipeline uploads with `"detail": null`.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ThinReport.Report").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    seen = _stub_analyzer_run(
        monkeypatch, fab_test_module, stderr="::error::Pass --env to resolve it.\n"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "pbir",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
        ],
    )

    fab_test_module.main()

    assert seen["kwargs"]["stderr"] is subprocess.PIPE, "CI must capture stderr too"
    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"][0]["detail"] == "Pass --env to resolve it."


@pytest.mark.fab_test
def test_ci_annotations_survive_stderr_capture(tmp_path, monkeypatch, capsys):
    """Given a CI run, the child's `::error::` lines still reach the log verbatim.

    Capturing stderr to fill `detail` must not cost the human the annotation
    GitHub renders against the file. Both callers, one message.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ThinReport.Report").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    _stub_analyzer_run(
        monkeypatch, fab_test_module, stderr="::error::Pass --env to resolve it.\n"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "pbir",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
        ],
    )

    fab_test_module.main()

    captured = capsys.readouterr()
    assert "::error::Pass --env to resolve it." in captured.err


@pytest.mark.fab_test
def test_manifest_detail_stays_null_when_the_analyzer_wrote_an_envelope(
    tmp_path, monkeypatch
):
    """Given a normal failing run, detail stays null -- the envelope holds the findings."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ThinReport.Report").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"
    envelope_dir = output_dir / "pbir" / "ThinReport"
    envelope_dir.mkdir(parents=True)
    (envelope_dir / "envelope.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "analyzer": "pbir",
                "artifact_path": str(artifact_dir / "ThinReport.Report"),
                "findings": [{"severity": "error", "message": "a real finding"}],
            }
        ),
        encoding="utf-8",
    )

    _stub_analyzer_run(monkeypatch, fab_test_module, stderr="noise on stderr\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fab-test", "pbir",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
        ],
    )

    fab_test_module.main()

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"][0]["status"] == "failed"
    assert manifest["artifacts"][0]["detail"] is None
