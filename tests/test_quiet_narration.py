"""-q narration: one line per artifact, failures still say why.

Terse CLI Output epic, "Quiet Parent Narration" task. The flag itself is
covered in test_quiet_flag.py.
"""

import json
import subprocess
from pathlib import Path

import pytest

from fab_test.scripts import fab_test_execution
from fab_test.scripts.fab_test import _print_all_summary, _run_analyzer
from tests.conftest import _RunAnalyzerArgs

pytestmark = pytest.mark.fab_test

_WARNING = {"rule": "R1", "severity": "Warning", "object": "T", "message": "m"}
_ERROR = {"rule": "R2", "severity": "Error", "object": "T", "message": "m"}


def _write_envelope(output_dir: Path, analyzer: str, stem: str, findings: list[dict]) -> None:
    path = output_dir / analyzer / stem / "envelope.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"status": "passed", "findings": findings}), encoding="utf-8")


def _project(tmp_path: Path, *stems: str) -> tuple[Path, Path]:
    artifact_dir = tmp_path / "artifacts"
    for stem in stems:
        (artifact_dir / f"{stem}.SemanticModel").mkdir(parents=True)
    return artifact_dir, tmp_path / "results"


def _quiet_args(artifact_dir: Path, output_dir: Path, **kwargs) -> _RunAnalyzerArgs:
    args = _RunAnalyzerArgs(artifact_dir, output_dir, **kwargs)
    args.quiet = True
    return args


def _fake_run(output_dir: Path, findings_by_stem: dict[str, list[dict]], *, returncode=0, stdout="", stderr=""):
    """A subprocess.run stand-in that writes the envelope the real analyzer would."""

    def _run(cmd, **_kwargs):
        stem = next(s for s in findings_by_stem if s in " ".join(map(str, cmd)))
        _write_envelope(output_dir, "bpa", stem, findings_by_stem[stem])
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    return _run


@pytest.fixture(autouse=True)
def _local_run(monkeypatch):
    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    # BPA is win32-only; the real preflight would exit 126 on a Linux runner before the fake runs.
    monkeypatch.setattr(fab_test_execution, "_preflight_error", lambda *a, **k: None)
    monkeypatch.chdir(Path.cwd())


def test_quiet_prints_exactly_one_line_per_artifact(tmp_path, monkeypatch, capsys):
    """Given -q and two artifacts, should print two lines and no banner, progress, or rule."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha", "Beta")
    findings = {"Alpha": [_WARNING, _WARNING], "Beta": []}
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        _fake_run(output_dir, findings, stdout="📊 noisy analyzer line\n"),
    )

    code = _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)
    lines = capsys.readouterr().out.splitlines()

    assert code == 0
    assert len(lines) == 2, lines
    assert lines[0].startswith("bpa warning e=0 w=2 ")
    assert lines[0].endswith("envelope.json")
    assert "Alpha" in lines[0]
    assert lines[1].startswith("bpa passed e=0 w=0 ")


def test_quiet_line_names_a_failing_artifact_with_its_error_count(tmp_path, monkeypatch, capsys):
    """Given an artifact with error findings, should report it failed and exit 1."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(
        fab_test_execution.subprocess, "run", _fake_run(output_dir, {"Alpha": [_ERROR, _WARNING]}, returncode=1)
    )

    code = _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)

    assert code == 1
    assert capsys.readouterr().out.splitlines()[0].startswith("bpa failed e=1 w=1 ")


def test_quiet_path_is_relative_to_the_working_directory(tmp_path, monkeypatch, capsys):
    """Given an output dir under the working directory, should print the short form."""
    monkeypatch.chdir(tmp_path)
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_run(output_dir, {"Alpha": []}))

    _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)

    line = capsys.readouterr().out.splitlines()[0]
    assert line.split(" ", 4)[4] == str(Path("results") / "bpa" / "Alpha" / "envelope.json")


def test_quiet_run_that_wrote_no_envelope_still_says_why(tmp_path, monkeypatch, capsys):
    """Given an analyzer that died before writing an envelope, should replay its stderr and name the artifact."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 127, stdout="", stderr="✗ Set TABULAR_EDITOR_PATH to the executable\n"
        ),
    )

    code = _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)
    out = capsys.readouterr().out

    assert code == 127
    assert "TABULAR_EDITOR_PATH" in out
    assert "bpa failed e=0 w=0 Alpha" in out


def test_quiet_timeout_still_reports(tmp_path, monkeypatch, capsys):
    """Given a timeout under -q, should still say which artifact timed out."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")

    def _timeout(cmd, **_k):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _timeout)

    code = _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)

    assert code == 1
    assert "timed out" in capsys.readouterr().out


def test_quiet_preflight_failure_still_prints_the_remediation(tmp_path, monkeypatch, capsys):
    """Given a missing prerequisite under -q, should still print the fix."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(fab_test_execution, "_preflight_error", lambda *a, **k: ("set FOO_PATH to fix", 127))

    code = _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)

    assert code == 127
    assert "set FOO_PATH to fix" in capsys.readouterr().out


def test_quiet_json_keeps_stdout_and_silences_stderr_for_a_passing_run(tmp_path, monkeypatch, capsys):
    """Given -q with --format json, should leave stdout equal to the non-quiet run and stderr empty."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    findings = {"Alpha": [_WARNING]}
    noise = {"stdout": "📊 noisy\n", "stderr": "::notice::something\n"}

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_run(output_dir, findings, **noise))
    loud = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    _run_analyzer("bpa", loud, output_dir)
    loud_out = capsys.readouterr()

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_run(output_dir, findings, **noise))
    _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="json"), output_dir)
    quiet_out = capsys.readouterr()

    assert loud_out.err != ""
    assert quiet_out.out == loud_out.out
    assert quiet_out.err == ""


def test_quiet_in_ci_keeps_stderr_annotations_verbatim(tmp_path, monkeypatch, capsys):
    """Given -q in CI, should still pass the analyzer's ::error:: annotations through."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: True)
    monkeypatch.setattr(fab_test_execution, "emit_workflow_annotations", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        _fake_run(output_dir, {"Alpha": [_ERROR]}, returncode=1, stderr="::error::rule R2 broke\n"),
    )

    _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)

    assert "::error::rule R2 broke" in capsys.readouterr().err


def test_quiet_all_summary_adds_nothing_beyond_the_per_artifact_lines(tmp_path, capsys):
    """Given -q, should leave `all`'s aggregate table out, since each artifact already has its line."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    _write_envelope(output_dir, "bpa", "Alpha", [_WARNING])
    args = _quiet_args(artifact_dir, output_dir, output_format="text")
    args.report = False

    code = _print_all_summary(output_dir, ("bpa",), [0], args)

    assert code == 0
    assert capsys.readouterr().out == ""


def test_default_output_is_unchanged_without_the_flag(tmp_path, monkeypatch, capsys):
    """Given no -q, should keep the progress line, header, and summary table."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_run(output_dir, {"Alpha": []}))

    _run_analyzer("bpa", _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text"), output_dir)
    out = capsys.readouterr().out

    assert "▶ fab-test bpa" in out
    assert "summary (1 artifact(s))" in out


def test_quiet_replays_stderr_when_a_crash_left_an_envelope_behind(tmp_path, monkeypatch, capsys):
    """Given a nonzero exit with no findings, should show stderr even though an envelope exists.

    A stale clean envelope from an earlier run makes a crashed analyzer look
    like it finished, which is exactly when the traceback is the only
    explanation. (A nonzero exit *with* warnings is BPA's normal exit and passes.)
    """
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        _fake_run(output_dir, {"Alpha": []}, returncode=1, stderr="Traceback: TabularEditor exploded\n"),
    )

    code = _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)
    out = capsys.readouterr().out

    assert code == 1
    assert "TabularEditor exploded" in out


def test_quiet_keeps_stderr_muted_when_error_findings_explain_the_exit(tmp_path, monkeypatch, capsys):
    """Given a nonzero exit that error findings explain, should still print only the summary line."""
    artifact_dir, output_dir = _project(tmp_path, "Alpha")
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        _fake_run(output_dir, {"Alpha": [_ERROR]}, returncode=1, stderr="routine finding chatter\n"),
    )

    _run_analyzer("bpa", _quiet_args(artifact_dir, output_dir, output_format="text"), output_dir)

    assert "chatter" not in capsys.readouterr().out
