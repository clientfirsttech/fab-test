"""Default output states each fact once.

Terse CLI Output epic, "State Each Result Once" task. The wrappers used to
print the envelope and native paths in the banner and again after the run,
and the Rules and Tool paths -- identical for every artifact and already in
the envelope -- on every artifact.
"""

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from fab_test.scripts import fab_test_execution
from fab_test.scripts.fab_test import _run_analyzer
from fab_test.scripts.invoke_pbir_a11y import _log_a11y_outcome, _log_run_header
from fab_test.scripts.invoke_pbir_inspector import run_inspector
from fab_test.scripts.invoke_pql_test import run_pql_test
from fab_test.scripts.invoke_pqlint import run_pqlint
from fab_test.scripts.invoke_tabular_editor_bpa import run_bpa
from tests.conftest import _RunAnalyzerArgs

pytestmark = pytest.mark.fab_test


def _bpa(tmp_path: Path) -> dict:
    tmdl = tmp_path / "SalesModel.SemanticModel"
    tmdl.mkdir()
    rules, tool = tmp_path / "BPARules.json", tmp_path / "TabularEditor.exe"
    rules.write_text("[]", encoding="utf-8")
    tool.write_text("fake", encoding="utf-8")
    output, native = tmp_path / "out.json", tmp_path / "native.xml"
    native.write_text("[]", encoding="utf-8")

    class Args:
        tmdl_path, bpa_rules_path, tabular_editor_path = str(tmdl), str(rules), str(tool)
        output_path, native_output_path = str(output), str(native)

    with mock.patch(
        "fab_test.scripts._analyzer_process.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout="", stderr=""),
    ):
        code = run_bpa(Args())
    return {"code": code, "output": output, "native": native, "rules": rules, "tool": tool}


def _pbir(tmp_path: Path, monkeypatch) -> dict:
    monkeypatch.chdir(tmp_path)
    artifact = tmp_path / "SalesReport.Report"
    artifact.mkdir()
    rules, tool = tmp_path / "rules.json", tmp_path / "PBIRInspectorCLI"
    rules.write_text("[]", encoding="utf-8")
    tool.write_text("fake", encoding="utf-8")
    tool.chmod(0o755)
    output = tmp_path / "out.json"
    native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
    native_dir.mkdir(parents=True)
    native = native_dir / "native.json"
    native.write_text("[]", encoding="utf-8")

    class Args:
        artifact_path, rules_path, inspector_path = str(artifact), str(rules), str(tool)
        output_path, emit_html = str(output), False

    with mock.patch(
        "fab_test.scripts.invoke_pbir_inspector.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout="", stderr=""),
    ):
        code = run_inspector(Args())
    return {"code": code, "output": output, "native": native, "rules": rules, "tool": tool}


def _pql_test(tmp_path: Path) -> dict:
    artifact = tmp_path / "SalesModel.SemanticModel"
    artifact.mkdir()
    output = tmp_path / "out.json"

    class Args:
        artifact_path, artifact_name = str(artifact), artifact.stem
        output_path, workspace_id, env = str(output), "", ""

    with mock.patch(
        "fab_test.scripts._analyzer_process.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout='{"test_results": []}', stderr=""),
    ):
        code = run_pql_test(Args())
    return {"code": code, "output": output}


def _pqlint(tmp_path: Path) -> dict:
    artifact = tmp_path / "SalesModel.SemanticModel"
    artifact.mkdir()
    output = tmp_path / "out.json"

    class Args:
        artifact_path, output_path, subscription_key = str(artifact), str(output), ""

    with mock.patch(
        "fab_test.scripts.invoke_pqlint.subprocess.run",
        return_value=mock.Mock(returncode=0, stdout='{"findings": []}', stderr=""),
    ):
        code = run_pqlint(Args())
    return {"code": code, "output": output}


@pytest.mark.parametrize("wrapper", ["bpa", "pbir", "pql_test", "pqlint"])
def test_a_passing_run_names_its_envelope_once(wrapper, tmp_path, monkeypatch, capsys):
    """Given a passing run at default verbosity, should print the envelope path once, not in banner and outcome."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "default")
    ran = {
        "bpa": lambda: _bpa(tmp_path),
        "pbir": lambda: _pbir(tmp_path, monkeypatch),
        "pql_test": lambda: _pql_test(tmp_path),
        "pqlint": lambda: _pqlint(tmp_path),
    }[wrapper]()
    out = capsys.readouterr().out

    assert ran["code"] == 0
    assert out.count(str(ran["output"])) == 1, out


@pytest.mark.parametrize("wrapper", ["bpa", "pbir"])
def test_a_passing_run_names_its_native_output_once(wrapper, tmp_path, monkeypatch, capsys):
    """Given a passing run at default verbosity, should print the native output path once."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "default")
    ran = _bpa(tmp_path) if wrapper == "bpa" else _pbir(tmp_path, monkeypatch)
    out = capsys.readouterr().out

    assert out.count(ran["native"].name) == 1, out


def test_a_passing_bpa_run_still_prints_its_own_result_line(tmp_path, monkeypatch, capsys):
    """Given the standalone wrapper, should still say the run passed."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "default")
    _bpa(tmp_path)
    assert "✅" in capsys.readouterr().out


@pytest.mark.parametrize("wrapper", ["bpa", "pbir"])
def test_default_omits_rules_and_tool_paths(wrapper, tmp_path, monkeypatch, capsys):
    """Given default verbosity, should leave out the Rules and Tool paths every artifact shares."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "default")
    ran = _bpa(tmp_path) if wrapper == "bpa" else _pbir(tmp_path, monkeypatch)
    out = capsys.readouterr().out

    assert str(ran["rules"]) not in out
    assert str(ran["tool"]) not in out


@pytest.mark.parametrize("wrapper", ["bpa", "pbir"])
def test_verbose_restores_rules_and_tool_paths(wrapper, tmp_path, monkeypatch, capsys):
    """Given -v, should print the Rules and Tool paths for anyone debugging which ones ran."""
    monkeypatch.setenv("ANALYZER_VERBOSITY", "verbose")
    ran = _bpa(tmp_path) if wrapper == "bpa" else _pbir(tmp_path, monkeypatch)
    out = capsys.readouterr().out

    assert str(ran["rules"]) in out
    assert str(ran["tool"]) in out


def test_a11y_names_its_paths_once_and_keeps_the_tool_for_verbose(tmp_path, capsys):
    """Given a clean a11y run, should print the envelope once and the tool only at verbose."""
    artifact, tool = tmp_path / "R.Report", tmp_path / "cli.js"
    output, native = tmp_path / "out.json", tmp_path / "native.json"
    outcome = {"message": "no findings", "error_count": 0, "warning_count": 0}

    for level, tool_shown in ((1, False), (2, True)):
        _log_run_header(level, "R", artifact, tool, output, native)
        _log_a11y_outcome(outcome, [], level)
        out = capsys.readouterr().out
        assert out.count(str(output)) == 1, out
        assert out.count(str(native)) == 1, out
        assert (str(tool) in out) is tool_shown


def _failing_prerequisite(tmp_path: Path, monkeypatch, *, in_ci: bool, count: int) -> _RunAnalyzerArgs:
    artifact_dir = tmp_path / "artifacts"
    for i in range(count):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "results"
    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: in_ci)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_execution, "emit_workflow_annotations", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 127, stdout="", stderr="Set FABRIC_TENANT_ID to fix this\n"
        ),
    )
    return _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")


def test_one_shared_remediation_is_printed_once(tmp_path, monkeypatch, capsys):
    """Given every artifact failing the same check, should print that remediation once."""
    args = _failing_prerequisite(tmp_path, monkeypatch, in_ci=False, count=3)

    code = _run_analyzer("bpa", args, Path(args.output_dir))
    out = capsys.readouterr().out

    assert code == 127
    assert out.count("Set FABRIC_TENANT_ID to fix this") == 1


def test_a_remediation_naming_the_artifact_is_still_printed_for_each(tmp_path, monkeypatch, capsys):
    """Given messages that differ per artifact, should keep every one."""
    args = _failing_prerequisite(tmp_path, monkeypatch, in_ci=False, count=2)
    calls = iter(("first", "second"))
    monkeypatch.setattr(
        fab_test_execution.subprocess,
        "run",
        lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 127, stdout="", stderr=f"cannot open the {next(calls)} model\n"
        ),
    )

    _run_analyzer("bpa", args, Path(args.output_dir))
    out = capsys.readouterr().out

    assert "cannot open the first model" in out
    assert "cannot open the second model" in out


def test_ci_keeps_every_annotation_verbatim(tmp_path, monkeypatch, capsys):
    """Given CI, should not collapse repeated annotations: each belongs to its own artifact."""
    args = _failing_prerequisite(tmp_path, monkeypatch, in_ci=True, count=3)

    _run_analyzer("bpa", args, Path(args.output_dir))

    assert capsys.readouterr().err.count("Set FABRIC_TENANT_ID to fix this") == 3


def test_identical_result_lines_are_kept_for_artifacts_that_have_findings(tmp_path, monkeypatch, capsys):
    """Given two artifacts whose results read the same, should keep each line: only remediations collapse."""
    artifact_dir = tmp_path / "artifacts"
    for stem in ("Alpha", "Beta"):
        (artifact_dir / f"{stem}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "results"
    monkeypatch.setattr(fab_test_execution, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_execution, "_send_telemetry", lambda *a, **k: None)

    def _run(cmd, **_k):
        stem = "Alpha" if "Alpha" in " ".join(map(str, cmd)) else "Beta"
        envelope = output_dir / "bpa" / stem / "envelope.json"
        envelope.parent.mkdir(parents=True, exist_ok=True)
        envelope.write_text(
            '{"status": "failed", "findings": [{"severity": "Error", "rule": "R"}]}', encoding="utf-8"
        )
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="::error::found 1 finding(s)\n")

    monkeypatch.setattr(fab_test_execution.subprocess, "run", _run)

    _run_analyzer("bpa", _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text"), output_dir)

    assert capsys.readouterr().out.count("found 1 finding(s)") == 2
