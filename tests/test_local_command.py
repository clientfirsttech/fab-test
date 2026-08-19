"""Contract tests for `fab-test local` (Local Desktop First Run §9).

Runs the local-Desktop analyzer subset (pql_lint, bpa, pbir, pql_test)
against every discovered project, skipping analyzers whose external tool
is missing rather than failing the run. No external tools, credentials,
or Fabric network access required for these tests.

    pytest -m fab_test tests/test_local_command.py
"""

import argparse
import subprocess

import pytest

from fabric_ci_cd_dataops.scripts.fab_test import _LOCAL_ANALYZERS, _run_local


class _Args(argparse.Namespace):
    pass


def _local_args(tmp_path, output_dir):
    return _Args(
        artifact_dir=str(tmp_path),
        output_dir=str(output_dir),
        dry_run=False,
        artifact=None,
        timeout=None,
        jobs=1,
        output_format="text",
        telemetry=False,
        no_telemetry=True,
        verbose=0,
    )


@pytest.mark.fab_test
def test_local_runs_every_analyzer_when_all_are_ready(tmp_path, monkeypatch):
    """Every analyzer in _LOCAL_ANALYZERS runs when its prerequisite is met."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    called = []
    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": True, "reason": "", "remediation": None},
    )
    monkeypatch.setattr(
        fab_test_module,
        "_run_analyzer",
        lambda name, args, output_dir, manifest: called.append(name) or 0,
    )

    output_dir = tmp_path / "results"
    exit_code = _run_local(_local_args(tmp_path, output_dir))

    assert exit_code == 0
    assert called == list(_LOCAL_ANALYZERS)


@pytest.mark.fab_test
def test_local_skips_analyzer_with_missing_prerequisite_without_failing(tmp_path, monkeypatch):
    """A missing prerequisite is skipped, not run, and doesn't fail the exit code."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    def _readiness(name, _args):
        if name == "bpa":
            return {"ready": False, "reason": "Tabular Editor not found", "remediation": "install it"}
        return {"ready": True, "reason": "", "remediation": None}

    called = []
    monkeypatch.setattr(fab_test_module, "_local_readiness", _readiness)
    monkeypatch.setattr(
        fab_test_module,
        "_run_analyzer",
        lambda name, args, output_dir, manifest: called.append(name) or 0,
    )

    output_dir = tmp_path / "results"
    exit_code = _run_local(_local_args(tmp_path, output_dir))

    assert exit_code == 0
    assert "bpa" not in called
    assert set(called) == set(_LOCAL_ANALYZERS) - {"bpa"}


@pytest.mark.fab_test
def test_local_exit_code_is_one_when_any_analyzer_fails(tmp_path, monkeypatch):
    """A real finding (nonzero exit from a ran analyzer) fails the run."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": True, "reason": "", "remediation": None},
    )
    monkeypatch.setattr(
        fab_test_module,
        "_run_analyzer",
        lambda name, args, output_dir, manifest: 1 if name == "pql_test" else 0,
    )

    output_dir = tmp_path / "results"
    exit_code = _run_local(_local_args(tmp_path, output_dir))

    assert exit_code == 1


@pytest.mark.fab_test
def test_local_exit_code_is_zero_when_every_analyzer_is_skipped(tmp_path, monkeypatch):
    """Every prerequisite missing degrades to a clean, successful no-op."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": False, "reason": "not installed", "remediation": None},
    )

    def _fail_if_called(*_a, **_k):
        raise AssertionError("_run_analyzer must not run a skipped analyzer")

    monkeypatch.setattr(fab_test_module, "_run_analyzer", _fail_if_called)

    output_dir = tmp_path / "results"
    exit_code = _run_local(_local_args(tmp_path, output_dir))

    assert exit_code == 0


@pytest.mark.fab_test
def test_local_writes_run_manifest(tmp_path, monkeypatch):
    """fab-test local still writes analyzer-results/run.json."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": True, "reason": "", "remediation": None},
    )
    monkeypatch.setattr(fab_test_module, "_run_analyzer", lambda name, args, output_dir, manifest: 0)

    output_dir = tmp_path / "results"
    _run_local(_local_args(tmp_path, output_dir))

    assert (output_dir / "run.json").exists()


@pytest.mark.fab_test
def test_local_help_exits_zero_and_never_mentions_workspace_id():
    """fab-test local --help exits 0; no workspace-id/service-principal flag is exposed."""
    result = subprocess.run(
        ["fab-test", "local", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--workspace-id" not in result.stdout


@pytest.mark.fab_test
def test_local_dry_run_exits_zero_with_no_projects(tmp_path):
    """fab-test local --dry-run against an empty directory exits 0."""
    result = subprocess.run(
        ["fab-test", "local", "--dry-run", "--artifact-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
