"""Output contract: stdout/stderr routing, and stdout purity across subcommands.

Scope
-----
--format json routing narration and captured subprocess output to stderr
while stdout carries only the final JSON summary, ANALYZER_OUTPUT_MODE
propagation to wrapper scripts, and a parser-driven sweep proving every
--format-capable subcommand emits a single parseable JSON document.

    pytest -m fab_test
"""
import argparse
import json
import subprocess

import pytest

from fabric_ci_cd_dataops.scripts.fab_test import _run_analyzer, build_parser
from tests.conftest import _RunAnalyzerArgs, _stub_subprocess_run

# --------------------------------------------------------------------------- #
# Route CLI narration through the helper
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_json_format_real_run_has_no_narration_on_stdout(tmp_path, monkeypatch, capsys):
    """A real (non-dry-run) analyzer run under --format json narrates only to
    stderr; stdout carries just the final JSON summary from _print_summary.
    """
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    for i in range(2):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution.subprocess, "run", _stub_subprocess_run)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    summary = json.loads(captured.out)
    assert summary["analyzer"] == "pql_lint"
    assert "artifact 1 of 2" in captured.err
    assert "fab-test pql_lint" in captured.err


@pytest.mark.fab_test
def test_text_format_narration_still_on_stdout(tmp_path, monkeypatch, capsys):
    """--format text keeps narration on stdout exactly as before (regression)."""
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
    assert "fab-test pql_lint" in captured.out
    assert captured.err == ""


@pytest.mark.fab_test
def test_missing_artifacts_warning_narrated_by_format(tmp_path, capsys):
    """The 'no artifacts found' warning follows the same json/stderr routing,
    while stdout still carries a valid (empty-artifacts) JSON summary.
    """
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()
    output_dir = tmp_path / "fab-test-results"

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    code = _run_analyzer("bpa", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    summary = json.loads(captured.out)
    assert summary == {"analyzer": "bpa", "artifacts": [], "skipped_checkouts": []}
    assert "no *.SemanticModel artifacts found" in captured.err


# --------------------------------------------------------------------------- #
# Capture subprocess output under JSON
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_json_format_passes_stdout_pipe_to_subprocess(tmp_path, monkeypatch):
    """--format json captures the analyzer subprocess's stdout via PIPE."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    _run_analyzer("pql_lint", args, output_dir)

    assert captured_kwargs.get("stdout") == subprocess.PIPE


@pytest.mark.fab_test
def test_text_format_does_not_capture_subprocess_stdout(tmp_path, monkeypatch):
    """--format text leaves subprocess stdout inherited: no capture, no added latency."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    _run_analyzer("pql_lint", args, output_dir)

    assert captured_kwargs.get("stdout") is None


@pytest.mark.fab_test
def test_json_format_reemits_captured_subprocess_stdout_to_stderr(tmp_path, monkeypatch, capsys):
    """The analyzer's own stdout banner is re-emitted on stderr under --format json,
    leaving stdout as a single parseable JSON document.
    """
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Tabular Editor BPA banner\n", stderr=""
        ),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "Tabular Editor BPA banner" in captured.err
    summary = json.loads(captured.out)
    assert summary["analyzer"] == "pql_lint"


@pytest.mark.fab_test
def test_json_format_verbose_still_narrates_and_stdout_stays_valid(tmp_path, monkeypatch, capsys):
    """--format json -v still narrates captured output to stderr; stdout still parses."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="debug banner\n", stderr=""
        ),
    )

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    args.verbose = 2
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    assert "debug banner" in captured.err
    summary = json.loads(captured.out)
    assert summary["analyzer"] == "pql_lint"


@pytest.mark.fab_test
def test_json_format_timeout_reemits_captured_stdout_before_timeout(
    tmp_path, monkeypatch, capsys
):
    """A subprocess timeout still re-emits whatever stdout was captured before it fired."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    def _fake_subprocess(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1, output="partial banner\n")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(
        artifact_dir, output_dir, output_format="json", timeout=1
    )
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 1
    assert "partial banner" in captured.err


# --------------------------------------------------------------------------- #
# Propagate output mode to wrapper scripts
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_json_format_sets_analyzer_output_mode_env_for_subprocess(tmp_path, monkeypatch):
    """--format json sets ANALYZER_OUTPUT_MODE=json in the subprocess environment."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    _run_analyzer("pql_lint", args, output_dir)

    assert captured_kwargs["env"]["ANALYZER_OUTPUT_MODE"] == "json"


@pytest.mark.fab_test
def test_text_format_leaves_analyzer_output_mode_env_unset(tmp_path, monkeypatch):
    """--format text does not set ANALYZER_OUTPUT_MODE, matching direct invocation."""
    from fabric_ci_cd_dataops.scripts import fab_test_execution

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    _run_analyzer("pql_lint", args, output_dir)

    assert "ANALYZER_OUTPUT_MODE" not in captured_kwargs["env"]


# --------------------------------------------------------------------------- #
# Prove stdout purity for every subcommand
# --------------------------------------------------------------------------- #

# dependencies is the only subcommand with a required flag beyond the common
# ones; every other --format-capable subcommand runs with just --dry-run.
_STDOUT_PURITY_EXTRA_ARGS = {
    "dependencies": ["--semantic-model", "TestModel"],
    "explain": ["bpa"],
}


# Admin/reporting subcommands (not part of the analyzer-run pipeline) don't
# necessarily narrate anything to stderr, and some don't take --dry-run.
_NO_NARRATION_SUBCOMMANDS = {"doctor", "list", "explain", "config"}
_EXPECTED_EXIT_CODES = {"doctor": (0, 1)}


def _subparser_for(subcommand: str):
    parser = build_parser()
    subparsers_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers_action.choices[subcommand]


def _subcommands_with_format_flag() -> list[str]:
    """Enumerate canonical (non-alias) subcommand names that support --format.

    Driven by the live parser, not a hardcoded list, so a new --format
    subcommand is automatically swept into the stdout-purity test below.
    """
    parser = build_parser()
    subparsers_action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    seen_subparsers = set()
    names = []
    for subcommand_name, subparser in subparsers_action.choices.items():
        if id(subparser) in seen_subparsers:
            continue  # an alias of an already-seen canonical name
        seen_subparsers.add(id(subparser))
        if any("--format" in action.option_strings for action in subparser._actions):
            names.append(subcommand_name)
    return names


@pytest.mark.fab_test
@pytest.mark.parametrize("subcommand", _subcommands_with_format_flag())
def test_stdout_is_pure_json_for_every_subcommand(subcommand):
    """Every --format json subcommand emits stdout that parses in one json.loads()
    call. Analyzer-run subcommands also narrate something to stderr (so silence
    wouldn't hide a dropped run); admin/reporting subcommands need not.
    """
    extra = list(_STDOUT_PURITY_EXTRA_ARGS.get(subcommand, []))
    args = ["fab-test", subcommand, "--format", "json"]
    if any(
        "--dry-run" in action.option_strings
        for action in _subparser_for(subcommand)._actions
    ):
        args.append("--dry-run")
    args.extend(extra)

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode in _EXPECTED_EXIT_CODES.get(subcommand, (0,)), result.stderr
    json.loads(result.stdout)  # must be a single, complete JSON document
    if subcommand not in _NO_NARRATION_SUBCOMMANDS:
        assert result.stderr.strip() != "", "narration should not be silently dropped"


