"""Contract tests for `fab-test local` (Local Desktop First Run §9).

Runs the local-Desktop analyzer subset (pql_lint, bpa, pbir, pql_test)
against every discovered project, skipping analyzers whose external tool
is missing rather than failing the run. No external tools, credentials,
or Fabric network access required for these tests.

    pytest -m fab_test tests/test_local_command.py
"""

import argparse
import json
import subprocess

import pytest

from fabric_ci_cd_dataops.scripts.fab_test import _LOCAL_ANALYZERS, _run_local


def _write_pbip_project(root, name):
    (root / f"{name}.pbip").write_text(
        json.dumps({"artifacts": [{"report": {"path": f"{name}.Report"}}]}),
        encoding="utf-8",
    )
    report_dir = root / f"{name}.Report"
    report_dir.mkdir(parents=True)
    (report_dir / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}}),
        encoding="utf-8",
    )
    (root / f"{name}.SemanticModel").mkdir(parents=True)


class _Args(argparse.Namespace):
    pass


def _local_args(tmp_path, output_dir):
    return _Args(
        analyzer="local",
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
        lambda name, args, output_dir, manifest, telemetry=None: called.append(name) or 0,
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
        lambda name, args, output_dir, manifest, telemetry=None: called.append(name) or 0,
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
        lambda name, args, output_dir, manifest, telemetry=None: 1 if name == "pql_test" else 0,
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
    """fab-test local still writes fab-test-results/run.json."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": True, "reason": "", "remediation": None},
    )
    monkeypatch.setattr(fab_test_module, "_run_analyzer", lambda name, args, output_dir, manifest, telemetry=None: 0)

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


# --------------------------------------------------------------------------- #
# fab-test local --dry-run plan (Local Desktop First Run §10)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_local_dry_run_plan_lists_projects_and_ready_analyzers(tmp_path, monkeypatch):
    """The plan lists which projects were discovered and which analyzers would run."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _write_pbip_project(tmp_path, "SampleModel")
    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": True, "reason": "", "remediation": None},
    )

    args = _local_args(tmp_path, tmp_path / "results")
    args.dry_run = True
    args.output_format = "text"

    exit_code = _run_local(args)

    assert exit_code == 0


@pytest.mark.fab_test
def test_local_dry_run_emits_single_json_plan(tmp_path, monkeypatch, capsys):
    """--format json emits exactly one JSON document describing the plan."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _write_pbip_project(tmp_path, "SampleModel")

    def _readiness(name, _args):
        if name == "bpa":
            return {"ready": False, "reason": "Tabular Editor not found", "remediation": "install it"}
        return {"ready": True, "reason": "", "remediation": None}

    monkeypatch.setattr(fab_test_module, "_local_readiness", _readiness)

    args = _local_args(tmp_path, tmp_path / "results")
    args.dry_run = True
    args.output_format = "json"

    exit_code = _run_local(args)
    captured = capsys.readouterr()

    assert exit_code == 0
    plan = json.loads(captured.out)
    assert plan["analyzer"] == "local"
    assert plan["dry_run"] is True
    assert "SampleModel" in plan["projects"]
    by_name = {a["analyzer"]: a for a in plan["analyzers"]}
    assert by_name["bpa"]["status"] == "skipped"
    assert by_name["bpa"]["reason"] == "Tabular Editor not found"
    assert by_name["pql_test"]["status"] == "would_run"
    assert "SampleModel" in by_name["pql_test"]["projects"]


@pytest.mark.fab_test
def test_local_dry_run_never_spawns_a_subprocess(tmp_path, monkeypatch):
    """--dry-run never spawns a subprocess for any analyzer."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _write_pbip_project(tmp_path, "SampleModel")
    monkeypatch.setattr(
        fab_test_module,
        "_local_readiness",
        lambda name, args: {"ready": True, "reason": "", "remediation": None},
    )

    def _fail_if_called(*_a, **_k):
        raise AssertionError("dry-run must never spawn a subprocess")

    monkeypatch.setattr(fab_test_module.subprocess, "run", _fail_if_called)

    args = _local_args(tmp_path, tmp_path / "results")
    args.dry_run = True

    exit_code = _run_local(args)

    assert exit_code == 0


@pytest.mark.fab_test
def test_local_dry_run_never_detects_desktop_instances(tmp_path, monkeypatch):
    """--dry-run never touches Desktop detection."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry

    _write_pbip_project(tmp_path, "SampleModel")

    def _fail_if_called(*_a, **_k):
        raise AssertionError("dry-run must never call detect_desktop_instances")

    monkeypatch.setattr(fab_test_registry, "detect_desktop_instances", _fail_if_called)

    args = _local_args(tmp_path, tmp_path / "results")
    args.dry_run = True

    exit_code = _run_local(args)

    assert exit_code == 0


@pytest.mark.fab_test
def test_local_dry_run_real_cli_emits_valid_json_plan():
    """Real fab-test local --dry-run --format json against this repo is valid JSON."""
    result = subprocess.run(
        ["fab-test", "local", "--dry-run", "--format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["analyzer"] == "local"
