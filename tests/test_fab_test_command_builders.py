"""Command builders: Desktop instance binding and rule-overlay wiring.

Scope
-----
build_pql_test_command's Desktop-instance binding (port/model-name flags),
and build_bpa_command / build_pbir_command's rule-overlay resolution --
packaged defaults, a resolved overlay, and an explicit --rules-path
override.

    pytest -m fab_test
"""
import argparse
import json
import subprocess
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.fab_test_registry import (
    _DEFAULT_A11Y_PATH,
    _DEFAULT_BPA_RULES,
    _DEFAULT_PBIR_RULES,
    build_a11y_command,
    build_bpa_command,
    build_pbir_command,
    build_pql_test_command,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Binding pql_test to a detected Desktop instance
# --------------------------------------------------------------------------- #


def _pbip_project_dir(tmp_path, name):
    (tmp_path / f"{name}.pbip").write_text(
        json.dumps({"artifacts": [{"report": {"path": f"{name}.Report"}}]}),
        encoding="utf-8",
    )
    report_dir = tmp_path / f"{name}.Report"
    report_dir.mkdir(parents=True)
    (report_dir / "definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}}}),
        encoding="utf-8",
    )
    model_dir = tmp_path / f"{name}.SemanticModel"
    model_dir.mkdir(parents=True)
    return model_dir


@pytest.mark.fab_test
def test_build_pql_test_command_adds_desktop_flags_when_instance_matches(tmp_path, monkeypatch):
    """A matched Desktop instance's port and model name are added to the command."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry
    from fabric_ci_cd_dataops.scripts._desktop import DesktopInstance

    model_dir = _pbip_project_dir(tmp_path, "SampleModel")
    pbip_path = (tmp_path / "SampleModel.pbip").resolve()
    monkeypatch.setattr(
        fab_test_registry,
        "detect_desktop_instances",
        lambda: [DesktopInstance(port=51234, open_file_path=pbip_path)],
    )

    args = argparse.Namespace(workspace_id="", environment="")
    cmd = build_pql_test_command(model_dir, args, REPO_ROOT / "fab-test-results")

    assert "--desktop-port" in cmd
    assert cmd[cmd.index("--desktop-port") + 1] == "51234"
    assert "--desktop-model-name" in cmd
    assert cmd[cmd.index("--desktop-model-name") + 1] == "SampleModel"


@pytest.mark.fab_test
def test_build_pql_test_command_skips_detection_when_workspace_id_given(tmp_path, monkeypatch):
    """--workspace-id skips Desktop detection entirely, even if a match exists."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry

    model_dir = _pbip_project_dir(tmp_path, "SampleModel")

    def _fail_if_called():
        raise AssertionError("detect_desktop_instances must not be called with --workspace-id")

    monkeypatch.setattr(fab_test_registry, "detect_desktop_instances", _fail_if_called)

    args = argparse.Namespace(workspace_id="workspace-123", environment="")
    cmd = build_pql_test_command(model_dir, args, REPO_ROOT / "fab-test-results")

    assert "--desktop-port" not in cmd
    assert "--desktop-model-name" not in cmd


@pytest.mark.fab_test
def test_build_pql_test_command_omits_desktop_flags_when_no_instance_running(tmp_path, monkeypatch):
    """No running Desktop instance leaves the command unchanged from today."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry

    model_dir = _pbip_project_dir(tmp_path, "SampleModel")
    monkeypatch.setattr(fab_test_registry, "detect_desktop_instances", list)

    args = argparse.Namespace(workspace_id="", environment="")
    cmd = build_pql_test_command(model_dir, args, REPO_ROOT / "fab-test-results")

    assert "--desktop-port" not in cmd
    assert "--desktop-model-name" not in cmd


@pytest.mark.fab_test
def test_build_pql_test_command_omits_desktop_flags_when_artifact_has_no_pbip(tmp_path, monkeypatch):
    """An artifact with no paired .pbip never attempts Desktop matching."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry
    from fabric_ci_cd_dataops.scripts._desktop import DesktopInstance

    model_dir = tmp_path / "Orphan.SemanticModel"
    model_dir.mkdir(parents=True)
    monkeypatch.setattr(
        fab_test_registry,
        "detect_desktop_instances",
        lambda: [DesktopInstance(port=1, open_file_path=tmp_path / "Orphan.pbip")],
    )

    args = argparse.Namespace(workspace_id="", environment="")
    cmd = build_pql_test_command(model_dir, args, REPO_ROOT / "fab-test-results")

    assert "--desktop-port" not in cmd


# --------------------------------------------------------------------------- #
# Wiring rule overlays into bpa/pbir command builders
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_build_bpa_command_uses_default_rules_verbatim_when_no_overlay(tmp_path):
    """No overlay configured: --bpa-rules-path points at the packaged default, unchanged."""
    artifact = tmp_path / "Model.SemanticModel"
    artifact.mkdir()
    args = argparse.Namespace(file_config={})

    cmd = build_bpa_command(artifact, args, tmp_path / "results")

    idx = cmd.index("--bpa-rules-path")
    assert cmd[idx + 1] == _DEFAULT_BPA_RULES
    assert not (tmp_path / "results" / "bpa" / "_resolved-rules.json").exists()


@pytest.mark.fab_test
def test_build_bpa_command_writes_resolved_rules_when_overlay_configured(tmp_path):
    """An overlay writes a resolved ruleset under output_dir and points --bpa-rules-path at it."""
    artifact = tmp_path / "Model.SemanticModel"
    artifact.mkdir()
    args = argparse.Namespace(file_config={"rules": {"bpa": {"disable": ["AVOID_FLOATING_POINT_DATA_TYPES"]}}})
    output_dir = tmp_path / "results"

    cmd = build_bpa_command(artifact, args, output_dir)

    idx = cmd.index("--bpa-rules-path")
    resolved_path = Path(cmd[idx + 1])
    assert resolved_path == output_dir / "bpa" / "_resolved-rules.json"
    resolved_rules = json.loads(resolved_path.read_text(encoding="utf-8"))
    ids = {r["ID"] for r in resolved_rules}
    assert "AVOID_FLOATING_POINT_DATA_TYPES" not in ids


@pytest.mark.fab_test
def test_build_bpa_command_ignores_overlay_when_rules_path_passed_explicitly(tmp_path):
    """--bpa-rules-path explicit override wins verbatim, even with an overlay configured."""
    artifact = tmp_path / "Model.SemanticModel"
    artifact.mkdir()
    custom_rules = tmp_path / "custom-rules.json"
    custom_rules.write_text("[]", encoding="utf-8")
    args = argparse.Namespace(
        bpa_rules_path=str(custom_rules),
        file_config={"rules": {"bpa": {"disable": ["ANYTHING"]}}},
    )
    output_dir = tmp_path / "results"

    cmd = build_bpa_command(artifact, args, output_dir)

    idx = cmd.index("--bpa-rules-path")
    assert cmd[idx + 1] == str(custom_rules)
    assert not (output_dir / "bpa" / "_resolved-rules.json").exists()


@pytest.mark.fab_test
def test_build_pbir_command_uses_default_rules_verbatim_when_no_overlay(tmp_path):
    """No overlay configured: --rules-path points at the packaged default, unchanged."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    args = argparse.Namespace(file_config={})

    cmd = build_pbir_command(artifact, args, tmp_path / "results")

    idx = cmd.index("--rules-path")
    assert cmd[idx + 1] == _DEFAULT_PBIR_RULES


@pytest.mark.fab_test
def test_build_pbir_command_writes_resolved_rules_when_overlay_configured(tmp_path):
    """An overlay writes a resolved ruleset under output_dir and points --rules-path at it."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    args = argparse.Namespace(file_config={"rules": {"pbir": {"disable": ["REMOVE_CUSTOM_VISUALS_NOT_USED"]}}})
    output_dir = tmp_path / "results"

    cmd = build_pbir_command(artifact, args, output_dir)

    idx = cmd.index("--rules-path")
    resolved_path = Path(cmd[idx + 1])
    assert resolved_path == output_dir / "pbir" / "_resolved-rules.json"
    resolved_doc = json.loads(resolved_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in resolved_doc["rules"]}
    assert by_id["REMOVE_CUSTOM_VISUALS_NOT_USED"]["disabled"] is True


@pytest.mark.fab_test
def test_build_pbir_command_ignores_overlay_when_rules_path_passed_explicitly(tmp_path):
    """--rules-path explicit override wins verbatim, even with an overlay configured."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    custom_rules = tmp_path / "custom-rules.json"
    custom_rules.write_text('{"rules": []}', encoding="utf-8")
    args = argparse.Namespace(
        rules_path=str(custom_rules),
        file_config={"rules": {"pbir": {"disable": ["ANYTHING"]}}},
    )
    output_dir = tmp_path / "results"

    cmd = build_pbir_command(artifact, args, output_dir)

    idx = cmd.index("--rules-path")
    assert cmd[idx + 1] == str(custom_rules)
    assert not (output_dir / "pbir" / "_resolved-rules.json").exists()


@pytest.mark.fab_test
def test_build_a11y_command_uses_default_tool_path_when_unresolved(tmp_path):
    """No _resolved_tool_path / --a11y-path / env var: falls back to the packaged default."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    args = argparse.Namespace(a11y_path=None, fail_on=None)

    cmd = build_a11y_command(artifact, args, tmp_path / "results")

    idx = cmd.index("--a11y-path")
    assert cmd[idx + 1] == _DEFAULT_A11Y_PATH
    assert "--fail-on" not in cmd


@pytest.mark.fab_test
def test_build_a11y_command_prefers_the_resolved_tool_path(tmp_path):
    """resolve_tool's cached-build path wins over the packaged default."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    resolved = tmp_path / "cached" / "dist" / "cli.js"
    args = argparse.Namespace(a11y_path=None, fail_on=None, _resolved_tool_path=str(resolved))

    cmd = build_a11y_command(artifact, args, tmp_path / "results")

    idx = cmd.index("--a11y-path")
    assert cmd[idx + 1] == str(resolved)


@pytest.mark.fab_test
def test_build_a11y_command_forwards_fail_on(tmp_path):
    """A caller's --fail-on reaches the wrapper command verbatim."""
    artifact = tmp_path / "Model.Report"
    artifact.mkdir()
    args = argparse.Namespace(a11y_path=None, fail_on="warn")

    cmd = build_a11y_command(artifact, args, tmp_path / "results")

    assert cmd[-2:] == ["--fail-on", "warn"]


@pytest.mark.fab_test
def test_all_help_exits_zero():
    """fab-test all --help exits 0."""
    result = subprocess.run(
        ["fab-test", "all", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


