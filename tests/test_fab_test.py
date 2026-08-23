"""Contract tests for the fab-test CLI (vision §2.7).

Scope
-----
These tests validate the *fab-test command surface*:
subcommand structure, help output, and dry-run artifact discovery.
No external tools (Tabular Editor, PBIR Inspector, etc.) required.
Always passes on any machine.

    pytest -m fab_test       # all fab-test CLI contract tests

Real artifact execution is done via fab-test directly:
    python scripts/fab_test.py bpa
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.fab_test import (
    _SUBCOMMAND_ALIASES,
    _apply_environment_default,
    _clean_tools,
    _resolve_timeout,
    _run_analyzer,
    build_parser,
)
from tests.conftest import (
    _RunAnalyzerArgs,
    _stub_subprocess_run,
    _TimeoutArgs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FAB_TEST = "fab-test"
ARTIFACT_ROOT = REPO_ROOT / ".fabric" / "artifacts"

# pql_lint is deliberately absent: it is hidden from the advertised surface
# (see HIDDEN_ANALYZERS and tests/test_hidden_analyzers.py) while remaining
# fully invocable.
_ALL_SUBCOMMANDS = ("bpa", "pbir", "pql_test", "all")


# --------------------------------------------------------------------------- #
# Configuration file support (pyproject.toml [tool.fab-test])
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_common_flags_use_pyproject_config_as_default(monkeypatch):
    """--jobs/--format/--artifact-dir/--output-dir default from [tool.fab-test]."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_PYPROJECT_CONFIG",
        {
            "jobs": 4,
            "format": "json",
            "artifact_dir": "/configured/artifacts",
            "output_dir": "/configured/results",
        },
    )
    parser = fab_test_module.build_parser()
    ns = parser.parse_args(["bpa", "--dry-run"])
    assert ns.jobs == 4
    assert ns.output_format == "json"
    assert ns.artifact_dir == "/configured/artifacts"
    assert ns.output_dir == "/configured/results"


@pytest.mark.fab_test
def test_common_flags_cli_overrides_pyproject_config(monkeypatch):
    """An explicit CLI flag still wins over the config file default."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "_PYPROJECT_CONFIG", {"jobs": 4})
    parser = fab_test_module.build_parser()
    ns = parser.parse_args(["bpa", "--dry-run", "--jobs", "8"])
    assert ns.jobs == 8


@pytest.mark.fab_test
def test_backward_compat_real_command_with_only_pyproject_config(tmp_path):
    """A repository with only [tool.fab-test] and no fab-test.yml: a real
    fab-test invocation resolves --artifact-dir from pyproject.toml exactly
    as it did before this epic, with no fab-test.yml involved at all.
    """
    artifact_dir = tmp_path / "configured-artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[tool.fab-test]\nartifact_dir = "{artifact_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    assert not (tmp_path / "fab-test.yml").exists()

    result = subprocess.run(
        ["fab-test", "bpa", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "SampleModel" in result.stdout


@pytest.mark.fab_test
def test_resolve_timeout_uses_config_when_no_cli_or_env(monkeypatch):
    """A config-file timeout is used when neither --timeout nor the env is set."""
    monkeypatch.delenv("ANALYZER_TIMEOUT", raising=False)
    assert _resolve_timeout(_TimeoutArgs(timeout=None), config={"timeout": 300}) == 300


@pytest.mark.fab_test
def test_resolve_timeout_env_overrides_config(monkeypatch):
    """ANALYZER_TIMEOUT still overrides a config-file timeout."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    assert _resolve_timeout(_TimeoutArgs(timeout=None), config={"timeout": 300}) == 60


@pytest.mark.fab_test
def test_resolve_timeout_cli_overrides_config_and_env(monkeypatch):
    """An explicit --timeout wins over both env var and config file."""
    monkeypatch.setenv("ANALYZER_TIMEOUT", "60")
    assert _resolve_timeout(_TimeoutArgs(timeout=999), config={"timeout": 300}) == 999


@pytest.mark.fab_test
def test_apply_environment_default_uses_config_when_no_cli_or_env(monkeypatch):
    """--env falls back to [tool.fab-test].environment when unset."""
    monkeypatch.delenv("FABRIC_ENVIRONMENT", raising=False)
    ns = argparse.Namespace(environment="")
    _apply_environment_default(ns, {"environment": "DEV"})
    assert ns.environment == "DEV"


@pytest.mark.fab_test
def test_apply_environment_default_env_overrides_config(monkeypatch):
    """FABRIC_ENVIRONMENT still overrides a config-file environment default."""
    monkeypatch.setenv("FABRIC_ENVIRONMENT", "PROD")
    ns = argparse.Namespace(environment="")
    _apply_environment_default(ns, {"environment": "DEV"})
    assert ns.environment == "PROD"


@pytest.mark.fab_test
def test_apply_environment_default_cli_value_not_overwritten(monkeypatch):
    """An explicit --env value is never replaced by env var or config."""
    monkeypatch.setenv("FABRIC_ENVIRONMENT", "PROD")
    ns = argparse.Namespace(environment="STAGE")
    _apply_environment_default(ns, {"environment": "DEV"})
    assert ns.environment == "STAGE"


@pytest.mark.fab_test
def test_apply_environment_default_noop_when_no_environment_attr():
    """Subcommands without an --env flag are left untouched."""
    ns = argparse.Namespace()
    _apply_environment_default(ns, {"environment": "DEV"})
    assert not hasattr(ns, "environment")


@pytest.mark.fab_test
def test_main_applies_environment_default_before_dispatch(monkeypatch):
    """main() merges the config/env default for --env before running analyzers."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    calls = []
    monkeypatch.setattr(
        fab_test_module,
        "_apply_environment_default",
        lambda args, config: calls.append((args.analyzer, config)),
    )
    monkeypatch.setattr(sys, "argv", ["fab-test", "pql_test", "--dry-run"])
    fab_test_module.main()
    assert calls and calls[0][0] == "pql_test"


# --------------------------------------------------------------------------- #
# Tool-cache management command (clean-tools)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_clean_tools_help_exits_zero():
    """fab-test clean-tools --help exits 0."""
    result = subprocess.run(
        ["fab-test", "clean-tools", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fab_test
def test_clean_tools_removes_existing_cache_dir(tmp_path, capsys):
    """clean-tools deletes .fab-test-tools and prints a confirmation."""
    cache_dir = tmp_path / ".fab-test-tools"
    (cache_dir / "pbir_inspector").mkdir(parents=True)
    (cache_dir / "pbir_inspector" / "tool.exe").write_text("x", encoding="utf-8")

    code = _clean_tools(tmp_path, dry_run=False)
    captured = capsys.readouterr()

    assert code == 0
    assert not cache_dir.exists()
    assert "removed" in captured.out
    assert str(cache_dir) in captured.out


@pytest.mark.fab_test
def test_clean_tools_dry_run_lists_without_deleting(tmp_path, capsys):
    """--dry-run lists what would be removed without deleting anything."""
    cache_dir = tmp_path / ".fab-test-tools"
    (cache_dir / "pbir_inspector").mkdir(parents=True)
    (cache_dir / "pbir_inspector" / "tool.exe").write_text("x", encoding="utf-8")

    code = _clean_tools(tmp_path, dry_run=True)
    captured = capsys.readouterr()

    assert code == 0
    assert cache_dir.exists()
    assert (cache_dir / "pbir_inspector" / "tool.exe").exists()
    assert "tool.exe" in captured.out


@pytest.mark.fab_test
def test_clean_tools_nothing_to_clean_when_missing(tmp_path, capsys):
    """A missing .fab-test-tools cache exits cleanly with a clear message."""
    code = _clean_tools(tmp_path, dry_run=False)
    captured = capsys.readouterr()

    assert code == 0
    assert "nothing to clean" in captured.out


@pytest.mark.fab_test
def test_main_clean_tools_dispatches_correctly(tmp_path, monkeypatch, capsys):
    """main() routes the clean-tools subcommand to _clean_tools."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["fab-test", "clean-tools"])

    code = fab_test_module.main()
    captured = capsys.readouterr()

    assert code == 0
    assert "nothing to clean" in captured.out


# --------------------------------------------------------------------------- #
# Shell completions
# --------------------------------------------------------------------------- #

_SUBCOMMAND_NAMES = (
    "bpa",
    "pbir",
    "pql-test",
    "pql-lint",
    "playwright",
    "playwright-impact",
    "dependencies",
    "all",
    "clean-tools",
)


@pytest.mark.fab_test
def test_print_completion_bash_exits_zero_and_writes_to_stdout():
    """--print-completion bash writes a bash completion script to stdout."""
    result = subprocess.run(
        ["fab-test", "--print-completion", "bash"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "complete -F" in result.stdout
    assert "fab-test" in result.stdout


@pytest.mark.fab_test
def test_print_completion_zsh_exits_zero_and_writes_to_stdout():
    """--print-completion zsh writes a zsh completion script to stdout."""
    result = subprocess.run(
        ["fab-test", "--print-completion", "zsh"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "#compdef" in result.stdout


@pytest.mark.fab_test
def test_print_completion_invalid_shell_exits_2():
    """--print-completion only accepts bash or zsh."""
    result = subprocess.run(
        ["fab-test", "--print-completion", "fish"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout


@pytest.mark.fab_test
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_print_completion_lists_all_subcommands(shell):
    """Both completion scripts enumerate every fab-test subcommand."""
    result = subprocess.run(
        ["fab-test", "--print-completion", shell],
        capture_output=True,
        text=True,
        check=False,
    )
    for name in _SUBCOMMAND_NAMES:
        assert name in result.stdout, f"{name} missing from {shell} completion script"


@pytest.mark.fab_test
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_print_completion_completes_common_flags(shell):
    """Both completion scripts offer common flags like --artifact-dir."""
    result = subprocess.run(
        ["fab-test", "--print-completion", shell],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "--artifact-dir" in result.stdout
    assert "--dry-run" in result.stdout


@pytest.mark.fab_test
@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_print_completion_completes_artifact_stems_dynamically(shell):
    """Both scripts look up artifact stems from .fabric/artifacts at completion time."""
    result = subprocess.run(
        ["fab-test", "--print-completion", shell],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ".fabric/artifacts" in result.stdout


# --------------------------------------------------------------------------- #
# Normalize subcommand aliases
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_subcommand_alias_mapping():
    """Hyphen/underscore aliases resolve to their canonical analyzer name."""
    assert _SUBCOMMAND_ALIASES["pql-test"] == "pql_test"
    assert _SUBCOMMAND_ALIASES["pql-lint"] == "pql_lint"
    assert _SUBCOMMAND_ALIASES["playwright_impact"] == "playwright-impact"


@pytest.mark.fab_test
def test_pql_test_hyphen_alias_behaves_like_underscore():
    """fab-test pql-test behaves identically to fab-test pql_test."""
    canonical = subprocess.run(
        ["fab-test", "pql_test", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "pql-test", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0
    assert canonical.stdout == aliased.stdout


@pytest.mark.fab_test
def test_pql_lint_hyphen_alias_behaves_like_underscore():
    """fab-test pql-lint behaves identically to fab-test pql_lint."""
    canonical = subprocess.run(
        ["fab-test", "pql_lint", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "pql-lint", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0
    assert canonical.stdout == aliased.stdout


@pytest.mark.fab_test
def test_playwright_impact_underscore_alias_accepted():
    """playwright-impact remains canonical; playwright_impact is also accepted."""
    canonical = subprocess.run(
        ["fab-test", "playwright-impact", "--help"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "playwright_impact", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0


@pytest.mark.fab_test
def test_all_dry_run_output_unaffected_by_aliases():
    """`fab-test all` still lists the canonical pql_test name, not an alias."""
    result = subprocess.run(
        ["fab-test", "all", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fab-test pql_test" in result.stdout
    assert "fab-test pql-test" not in result.stdout


# --------------------------------------------------------------------------- #
# Canonicalize subcommand names (CLI Agent Ergonomics §13)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_help_displays_hyphenated_form_as_canonical():
    """--help shows the hyphenated spelling as primary, underscore as the alias."""
    result = subprocess.run(
        ["fab-test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pql-test (pql_test)" in result.stdout
    # playwright-impact stands in for pql-lint here, which is now hidden
    # from the listing; the point is that an aliased subcommand shows its
    # hyphenated form as canonical with the underscore form in parentheses.
    assert "playwright-impact (playwright_impact)" in result.stdout


@pytest.mark.fab_test
def test_pql_test_underscore_form_still_works_with_no_error():
    """The underscore spelling is still silently accepted (no warning/deprecation)."""
    result = subprocess.run(
        ["fab-test", "pql_test", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "deprecat" not in result.stdout.lower()
    assert "deprecat" not in result.stderr.lower()


@pytest.mark.fab_test
def test_list_reports_canonical_name_and_aliases():
    """`fab-test list --format json` reports the canonical name plus aliases."""
    result = subprocess.run(
        ["fab-test", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)

    pql_test_row = next(r for r in summary["analyzers"] if r["analyzer"] == "pql-test")
    assert pql_test_row["aliases"] == ["pql_test"]

    impact_row = next(
        r for r in summary["analyzers"] if r["analyzer"] == "playwright-impact"
    )
    assert impact_row["aliases"] == ["playwright_impact"]

    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["aliases"] == []


@pytest.mark.fab_test
def test_result_directory_name_unchanged_when_invoked_via_canonical_form(tmp_path):
    """Invoking via the new canonical 'pql-test' still writes under analyzer-results/pql_test/."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    result = subprocess.run(
        [
            "fab-test", "pql-test",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # The dry-run banner uses the internal registry key, unaffected by which
    # spelling the user typed — proving result-directory naming is unchanged.
    assert "fab-test pql_test" in result.stdout


# --------------------------------------------------------------------------- #
# Route CLI narration through the helper (CLI Agent Ergonomics §2)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_json_format_real_run_has_no_narration_on_stdout(tmp_path, monkeypatch, capsys):
    """A real (non-dry-run) analyzer run under --format json narrates only to
    stderr; stdout carries just the final JSON summary from _print_summary.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    for i in range(2):
        (artifact_dir / f"Model{i}.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

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
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_is_ci", lambda: False)
    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(fab_test_module.subprocess, "run", _stub_subprocess_run)

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
    output_dir = tmp_path / "analyzer-results"

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    code = _run_analyzer("bpa", args, output_dir)
    captured = capsys.readouterr()

    assert code == 0
    summary = json.loads(captured.out)
    assert summary == {"analyzer": "bpa", "artifacts": [], "skipped_checkouts": []}
    assert "no *.SemanticModel artifacts found" in captured.err


# --------------------------------------------------------------------------- #
# Empty discovery explains itself (Empty Discovery Diagnostics §2)
# --------------------------------------------------------------------------- #


def _sibling_checkout(parent: Path, name: str) -> Path:
    """A directory the scan will refuse to walk into, as a real repo would be."""
    checkout = parent / name
    (checkout / ".git").mkdir(parents=True)
    return checkout


@pytest.mark.fab_test
def test_empty_result_does_not_claim_a_pbip_would_have_helped(tmp_path, capsys):
    """Given an empty scan, the message should name the folder suffix it
    searched for and not offer a .pbip as an alternative route to being
    found -- it stopped being one when discovery went suffix-based.
    """
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    args = _RunAnalyzerArgs(artifact_dir, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")

    assert ".pbip" not in capsys.readouterr().out


@pytest.mark.fab_test
def test_empty_result_reports_the_checkouts_it_skipped(tmp_path, capsys):
    """Given a root holding only git checkouts, the scan finds nothing by
    design, so the message should say how many it skipped rather than
    report an absence the caller can neither see nor act on.
    """
    _sibling_checkout(tmp_path, "project-a")
    _sibling_checkout(tmp_path, "project-b")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")
    out = capsys.readouterr().out

    assert "2 git checkouts" in out
    assert "--artifact-dir" in out


@pytest.mark.fab_test
def test_the_skipped_checkouts_are_named_so_the_remedy_is_pasteable(tmp_path, capsys):
    """Given skipped checkouts, naming them turns the hint into a command."""
    checkout = _sibling_checkout(tmp_path, "project-a")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")

    assert str(checkout) in capsys.readouterr().out


@pytest.mark.fab_test
def test_only_the_first_few_skipped_checkouts_are_named(tmp_path, capsys):
    """Given many skipped checkouts, a warning should stay a warning --
    listing every repository on a developer's machine is not a remedy.
    """
    for index in range(9):
        _sibling_checkout(tmp_path, f"project-{index}")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")
    out = capsys.readouterr().out

    assert "9 git checkouts" in out
    assert sum(f"project-{i}" in out for i in range(9)) == 3


@pytest.mark.fab_test
def test_an_empty_repository_gains_no_checkout_note(tmp_path, capsys):
    """Given nothing was pruned, the in-repo case must not get noisier to
    serve the out-of-repo one.
    """
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    args = _RunAnalyzerArgs(artifact_dir, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")
    out = capsys.readouterr().out

    assert "checkout" not in out
    assert "--artifact-dir" not in out


@pytest.mark.fab_test
def test_a_path_target_gains_no_checkout_note(tmp_path, capsys):
    """Given the caller named a location, reporting what a scan elsewhere
    pruned answers a question they did not ask.
    """
    _sibling_checkout(tmp_path, "project-a")
    missing = tmp_path / "Nowhere.SemanticModel"

    args = _RunAnalyzerArgs(
        tmp_path, tmp_path / "out", artifact=str(missing), output_format="text"
    )
    _run_analyzer("bpa", args, tmp_path / "out")

    assert "checkout" not in capsys.readouterr().out


@pytest.mark.fab_test
def test_skipped_checkouts_reach_the_json_payload(tmp_path, capsys):
    """Given an agent caller, an empty `artifacts` list reads the same
    whether the repository was empty or every candidate was pruned, so the
    payload should carry the distinction and a remediation it can act on.
    """
    checkout = _sibling_checkout(tmp_path, "project-a")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="json")
    _run_analyzer("bpa", args, tmp_path / "out")
    summary = json.loads(capsys.readouterr().out)

    assert summary["artifacts"] == []
    assert summary["skipped_checkouts"] == [str(checkout)]
    assert "--artifact-dir" in summary["remediation"]


@pytest.mark.fab_test
def test_an_empty_payload_carries_no_remediation_key(tmp_path, capsys):
    """Given nothing was pruned, there is nothing to remediate."""
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    args = _RunAnalyzerArgs(artifact_dir, tmp_path / "out", output_format="json")
    _run_analyzer("bpa", args, tmp_path / "out")
    summary = json.loads(capsys.readouterr().out)

    assert summary["skipped_checkouts"] == []
    assert "remediation" not in summary


@pytest.mark.fab_test
def test_main_artifact_dir_missing_message_narrated_by_format(tmp_path):
    """main()'s --artifact-dir-missing message follows --format routing too."""
    missing = tmp_path / "does-not-exist"

    result = subprocess.run(
        ["fab-test", "bpa", "--artifact-dir", str(missing), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "does not exist" in result.stderr


# --------------------------------------------------------------------------- #
# Capture subprocess output under JSON (CLI Agent Ergonomics §3)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_json_format_passes_stdout_pipe_to_subprocess(tmp_path, monkeypatch):
    """--format json captures the analyzer subprocess's stdout via PIPE."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    _run_analyzer("pql_lint", args, output_dir)

    assert captured_kwargs.get("stdout") == subprocess.PIPE


@pytest.mark.fab_test
def test_text_format_does_not_capture_subprocess_stdout(tmp_path, monkeypatch):
    """--format text leaves subprocess stdout inherited: no capture, no added latency."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    _run_analyzer("pql_lint", args, output_dir)

    assert captured_kwargs.get("stdout") is None


@pytest.mark.fab_test
def test_json_format_reemits_captured_subprocess_stdout_to_stderr(tmp_path, monkeypatch, capsys):
    """The analyzer's own stdout banner is re-emitted on stderr under --format json,
    leaving stdout as a single parseable JSON document.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_module.subprocess,
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
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(
        fab_test_module.subprocess,
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
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    def _fake_subprocess(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1, output="partial banner\n")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(
        artifact_dir, output_dir, output_format="json", timeout=1
    )
    code = _run_analyzer("pql_lint", args, output_dir)
    captured = capsys.readouterr()

    assert code == 1
    assert "partial banner" in captured.err


# --------------------------------------------------------------------------- #
# Propagate output mode to wrapper scripts (CLI Agent Ergonomics §4)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_json_format_sets_analyzer_output_mode_env_for_subprocess(tmp_path, monkeypatch):
    """--format json sets ANALYZER_OUTPUT_MODE=json in the subprocess environment."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="json")
    _run_analyzer("pql_lint", args, output_dir)

    assert captured_kwargs["env"]["ANALYZER_OUTPUT_MODE"] == "json"


@pytest.mark.fab_test
def test_text_format_leaves_analyzer_output_mode_env_unset(tmp_path, monkeypatch):
    """--format text does not set ANALYZER_OUTPUT_MODE, matching direct invocation."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "analyzer-results"

    monkeypatch.setattr(fab_test_module, "_send_telemetry", lambda *a, **k: None)

    captured_kwargs = {}

    def _fake_subprocess(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fake_subprocess)

    args = _RunAnalyzerArgs(artifact_dir, output_dir, output_format="text")
    _run_analyzer("pql_lint", args, output_dir)

    assert "ANALYZER_OUTPUT_MODE" not in captured_kwargs["env"]


# --------------------------------------------------------------------------- #
# Prove stdout purity for every subcommand (CLI Agent Ergonomics §5)
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


