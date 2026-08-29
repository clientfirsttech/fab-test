"""Execution: subprocess timeout, parallel runs, per-artifact progress, regressions.

Scope
-----
_resolve_timeout's CLI/env precedence, --jobs parallelizing per-artifact
subprocess runs while still writing one envelope each, per-artifact
progress narration (plain text and CI ::notice::), and regression coverage
for warning-level PR review comments and the playwright impact-manifest
scope. Kept as one module rather than split further: several of these
tests share the `_stub_subprocess_run` stand-in from tests/conftest.py.

    pytest -m fab_test
"""
import argparse
import json
import subprocess
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.fab_test import _resolve_timeout, _run_analyzer, build_parser
from fabric_ci_cd_dataops.scripts.fab_test_registry import build_pbir_command
from tests.conftest import _RunAnalyzerArgs, _stub_subprocess_run, _TimeoutArgs

# --------------------------------------------------------------------------- #
# Configurable subprocess timeout
# --------------------------------------------------------------------------- #




@pytest.mark.fab_test
def test_resolve_timeout_uses_cli_flag_over_env(monkeypatch):
    """--timeout takes precedence over ANALYZER_TIMEOUT."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    assert _resolve_timeout(_TimeoutArgs(timeout=300)) == 300


@pytest.mark.fab_test
def test_resolve_timeout_uses_env_when_no_cli_flag(monkeypatch):
    """ANALYZER_TIMEOUT overrides the default when --timeout is not passed."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "200")
    assert _resolve_timeout(_TimeoutArgs(timeout=None)) == 200


@pytest.mark.fab_test
def test_resolve_timeout_defaults_to_200(monkeypatch):
    """With neither --timeout nor ANALYZER_TIMEOUT set, the default is 200.

    200 must stay above PLAYWRIGHT_TIMEOUT_SECONDS's default (180) plus
    auth/startup overhead -- this is the outer subprocess timeout that
    wraps every analyzer invocation, and killing the playwright wrapper
    before its own render-wait budget elapses would be worse than the
    render timeout it is meant to catch.
    """
    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)
    assert _resolve_timeout(_TimeoutArgs(timeout=None)) == 200


@pytest.mark.fab_test
def test_bpa_help_shows_timeout_flag():
    """--timeout must be documented on subcommand help."""
    result = subprocess.run(
        ["fab-test", "bpa", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--timeout" in result.stdout


@pytest.mark.fab_test
def test_run_analyzer_passes_resolved_timeout_to_subprocess(tmp_path, monkeypatch):
    """_run_analyzer forwards the resolved timeout to subprocess.run."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    captured_timeouts = []

    def _fake_subprocess(*args, **kwargs):
        captured_timeouts.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel", timeout=45)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    assert captured_timeouts == [45]


# --------------------------------------------------------------------------- #
# Parallelize per-artifact runs
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_jobs_flag_default_is_one():
    """--jobs defaults to 1 (sequential) when not passed."""
    parser = build_parser()
    ns = parser.parse_args(["bpa", "--dry-run"])
    assert ns.jobs == 1


@pytest.mark.fab_test
def test_jobs_flag_parses_requested_value():
    """--jobs 4 is parsed as an int."""
    parser = build_parser()
    ns = parser.parse_args(["bpa", "--jobs", "4", "--dry-run"])
    assert ns.jobs == 4


@pytest.mark.fab_test
def test_run_analyzer_default_jobs_runs_artifacts_sequentially(tmp_path, monkeypatch):
    """With --jobs 1 (default), only one artifact's subprocess runs at a time."""
    import threading
    import time

    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    for i in range(3):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    lock = threading.Lock()
    active = 0
    max_active = 0

    def _fake_subprocess(*_args, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, jobs=1)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    assert max_active == 1


@pytest.mark.fab_test
def test_run_analyzer_jobs_n_runs_artifacts_concurrently(tmp_path, monkeypatch):
    """--jobs 3 runs up to 3 artifacts of the same analyzer in parallel."""
    import threading

    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    for i in range(3):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    # A 3-party barrier only completes if all three subprocess calls are
    # in flight at once; sequential execution would deadlock and time out.
    barrier = threading.Barrier(3, timeout=2)

    def _fake_subprocess(*_args, **_kwargs):
        barrier.wait()
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, jobs=3)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0


@pytest.mark.fab_test
def test_run_analyzer_parallel_writes_one_envelope_per_artifact(tmp_path, monkeypatch):
    """Each artifact still writes its own envelope; the summary waits for all."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    stems = [f"Model{i}" for i in range(3)]
    for stem in stems:
        (artifact_dir / f"{stem}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    def _fake_subprocess(cmd, **_kwargs):
        # Locate the artifact stem this invocation targets and write its
        # envelope, mirroring what the real analyzer wrapper would do.
        stem = next(s for s in stems if s in " ".join(cmd))
        envelope_dir = output_dir / "pql_lint" / stem
        envelope_dir.mkdir(parents=True, exist_ok=True)
        (envelope_dir / "envelope.json").write_text(
            json.dumps({"status": "passed", "findings": []}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, jobs=3)
    code = _run_analyzer("pql_lint", args, output_dir)

    assert code == 0
    for stem in stems:
        assert (output_dir / "pql_lint" / stem / "envelope.json").exists()


# --------------------------------------------------------------------------- #
# Show per-artifact progress
# --------------------------------------------------------------------------- #




@pytest.mark.fab_test
def test_progress_shown_non_ci_multiple_artifacts(tmp_path, monkeypatch, capsys):
    """A non-CI run with multiple artifacts shows 'artifact N of M'."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    for i in range(3):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "artifact 1 of 3" in captured.out
    assert "artifact 2 of 3" in captured.out
    assert "artifact 3 of 3" in captured.out


@pytest.mark.fab_test
def test_progress_not_shown_for_single_artifact(tmp_path, monkeypatch, capsys):
    """A single-artifact run shows no 'N of 1' progress noise."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "of 1" not in captured.out


@pytest.mark.fab_test
def test_progress_emitted_as_ci_notice(tmp_path, monkeypatch, capsys):
    """In CI (GITHUB_ACTIONS), progress is a ::notice:: annotation, not plain text."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    for i in range(2):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: True)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution, "emit_workflow_annotations", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "::notice::" in captured.out
    assert "artifact 1 of 2" in captured.out
    assert "artifact 2 of 2" in captured.out
    assert "\n  artifact 1 of 2" not in captured.out  # not the plain-text form


@pytest.mark.fab_test
def test_artifact_start_line_still_printed_alongside_progress(tmp_path, monkeypatch, capsys):
    """The per-artifact '▶ fab-test ... → stem' line still prints as artifacts start."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    args.verbose = 1
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "fab-test pql_lint" in captured.out
    assert "SampleModel" in captured.out


# --------------------------------------------------------------------------- #
# Regression: per-artifact warning handling
# --------------------------------------------------------------------------- #




def _make_warning_envelope(output_dir: Path, analyzer: str, stem: str) -> None:
    envelope = output_dir / analyzer / stem / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
        json.dumps(
            {
                "status": "failed",
                "findings": [
                    {"rule": "R1", "severity": "Warning", "object": "T", "message": "m"}
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.fab_test
def test_run_analyzer_warning_no_name_error_outside_ci(tmp_path, monkeypatch):
    """Regression: warning-level findings must not raise NameError outside CI."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"
    _make_warning_envelope(output_dir, "pql_lint", "SampleModel")

    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("pql_lint", args, output_dir)
    assert code == 0


@pytest.mark.fab_test
def test_run_analyzer_warning_emits_pr_review_comment_in_ci(tmp_path, monkeypatch):
    """Warning-level findings trigger PR review comments when running in CI."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"
    _make_warning_envelope(output_dir, "pql_lint", "SampleModel")

    calls = []
    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: True)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_execution,
        "emit_workflow_annotations",
        lambda *a, **k: calls.append("annotation"),
    )
    monkeypatch.setattr(
        fab_test_execution,
        "emit_pr_review_comments",
        lambda *a, **k: calls.append("pr_comment"),
    )
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("pql_lint", args, output_dir)
    assert code == 0
    assert "annotation" in calls
    assert "pr_comment" in calls


@pytest.mark.fab_test
def test_run_analyzer_playwright_with_impact_manifest_is_repository_scoped(
    tmp_path, monkeypatch
):
    """Playwright with --impact-manifest runs once, not per local Report artifact."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ReportOne.Report").mkdir(parents=True)
    (artifact_dir / "ReportTwo.Report").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"
    impact_manifest = tmp_path / "impact-manifest.json"
    impact_manifest.write_text(json.dumps({"reports": []}), encoding="utf-8")

    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    commands: list[list[str]] = []

    def _fake_subprocess(*args, **kwargs):
        commands.append(list(args[0]))
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(
        artifact_dir,
        output_dir,
        impact_manifest=str(impact_manifest),
    )
    code = _run_analyzer("playwright", args, output_dir)

    assert code == 0
    assert len(commands) == 1
    assert "--impact-manifest" in commands[0]


@pytest.mark.fab_test
def test_run_analyzer_error_does_not_emit_pr_review_comment(tmp_path, monkeypatch):
    """Error-level findings are annotations only; PR comments are reserved for warnings."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"
    envelope = output_dir / "pql_lint" / "SampleModel" / "envelope.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_text(
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

    calls = []
    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: True)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_execution,
        "emit_workflow_annotations",
        lambda *a, **k: calls.append("annotation"),
    )
    monkeypatch.setattr(
        fab_test_execution,
        "emit_pr_review_comments",
        lambda *a, **k: calls.append("pr_comment"),
    )
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, artifact="SampleModel")
    code = _run_analyzer("pql_lint", args, output_dir)
    assert code == 1
    assert "annotation" in calls
    assert "pr_comment" not in calls


@pytest.mark.fab_test
def test_build_pbir_command_omits_emit_html_without_report(tmp_path):
    """No --report: pbir is JSON-only, matching bpa and pql_test."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    args = argparse.Namespace(file_config={}, report=None)

    cmd = build_pbir_command(artifact, args, tmp_path / "results")

    assert "--emit-html" not in cmd


@pytest.mark.fab_test
def test_build_pbir_command_adds_emit_html_under_report(tmp_path):
    """--report asks the inspector for its own HTML page alongside the JSON."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    args = argparse.Namespace(file_config={}, report=True)

    cmd = build_pbir_command(artifact, args, tmp_path / "results")

    assert "--emit-html" in cmd
    # JSON is never traded away for HTML -- the envelope's findings parse
    # out of it, so a report must add a format, not swap one.
    assert "--output-path" in cmd
