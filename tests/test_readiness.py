"""Contract tests for the fab-test readiness probe (CLI Agent Ergonomics §7).

Scope
-----
The probe answers "could this analyzer run?" without downloading anything,
touching artifacts, or spawning a subprocess — it is the engine behind
`fab-test doctor`. Always passes on any machine.
"""

import json

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import probe_executable
from fabric_ci_cd_dataops.scripts.fab_test_registry import check_readiness


def _write_metadata(metadata_path, analyzer_name, tool_install):
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps({"analyzer_registry": {analyzer_name: {"tool_install": tool_install}}}),
        encoding="utf-8",
    )


@pytest.mark.fab_test
def test_probe_ready_when_explicit_path_resolves(tmp_path):
    """A usable explicit_path reports ready with its resolved path and no remediation."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    existing = repo_root / "TabularEditor.exe"
    existing.write_text("binary", encoding="utf-8")
    _write_metadata(
        metadata,
        "tabular_editor_bpa",
        {"env_var": "TABULAR_EDITOR_PATH", "default_path": ""},
    )

    result = probe_executable(
        "tabular_editor_bpa", metadata, repo_root, explicit_path=str(existing)
    )

    assert result["ready"] is True
    assert result["resolved_path"] == str(existing.resolve())
    assert "CLI argument" in result["reason"]
    assert result["remediation"] is None


@pytest.mark.fab_test
def test_probe_ready_when_env_var_path_resolves(tmp_path, monkeypatch):
    """A usable env-var path reports ready without needing explicit_path."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    existing = repo_root / "PBIRInspectorCLI"
    existing.write_text("binary", encoding="utf-8")
    _write_metadata(
        metadata, "pbir_inspector", {"env_var": "PBIR_INSPECTOR_PATH", "default_path": ""}
    )
    monkeypatch.setenv("PBIR_INSPECTOR_PATH", str(existing))

    result = probe_executable("pbir_inspector", metadata, repo_root)

    assert result["ready"] is True
    assert result["resolved_path"] == str(existing.resolve())
    assert "PBIR_INSPECTOR_PATH" in result["reason"]


@pytest.mark.fab_test
def test_probe_reports_would_download_without_downloading(tmp_path, monkeypatch):
    """A tool that would need downloading reports the install URL, but never fetches it."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(
        metadata,
        "tabular_editor_bpa",
        {
            "env_var": "TABULAR_EDITOR_PATH",
            "default_path": "./TabularEditor/TabularEditor.exe",
            "install_url_env_var": "TABULAR_EDITOR_INSTALL_URL",
            "install_url": "https://cdn.tabulareditor.com/files/TabularEditor.2.28.0.zip",
        },
    )
    monkeypatch.delenv("TABULAR_EDITOR_PATH", raising=False)
    monkeypatch.delenv("TABULAR_EDITOR_INSTALL_URL", raising=False)

    from fabric_ci_cd_dataops.scripts import _analyzer_tool_bootstrap as bootstrap

    def _fail_if_called(*_a, **_k):
        raise AssertionError("probe must never download")

    monkeypatch.setattr(bootstrap, "urlopen", _fail_if_called)

    result = probe_executable("tabular_editor_bpa", metadata, repo_root)

    assert result["ready"] is False
    assert result["resolved_path"] is None
    assert "TabularEditor.2.28.0.zip" in result["remediation"]


@pytest.mark.fab_test
def test_probe_reports_unsupported_platform(tmp_path, monkeypatch):
    """A platform mismatch is reported as not-ready with the supported platform named."""
    import sys

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(
        metadata,
        "tabular_editor_bpa",
        {"env_var": "TABULAR_EDITOR_PATH", "requires_platform": "win32"},
    )
    monkeypatch.setattr(sys, "platform", "linux")

    result = probe_executable("tabular_editor_bpa", metadata, repo_root)

    assert result["ready"] is False
    assert result["resolved_path"] is None
    assert "linux" in result["reason"]
    assert "win32" in result["remediation"]


@pytest.mark.fab_test
def test_probe_not_ready_with_no_candidates_and_no_install_url(tmp_path):
    """No usable path and no install URL configured is a clear not-ready state."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(metadata, "tabular_editor_bpa", {"env_var": "TABULAR_EDITOR_PATH"})

    result = probe_executable("tabular_editor_bpa", metadata, repo_root)

    assert result["ready"] is False
    assert result["resolved_path"] is None
    assert "TABULAR_EDITOR_PATH" in result["remediation"]


@pytest.mark.fab_test
def test_probe_never_spawns_a_subprocess(tmp_path, monkeypatch):
    """The probe never invokes subprocess.run, regardless of outcome."""
    import subprocess

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(metadata, "tabular_editor_bpa", {"env_var": "TABULAR_EDITOR_PATH"})

    def _fail_if_called(*_a, **_k):
        raise AssertionError("probe must never spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", _fail_if_called)

    probe_executable("tabular_editor_bpa", metadata, repo_root)  # must not raise


@pytest.mark.fab_test
def test_check_readiness_bpa_delegates_to_probe(tmp_path, monkeypatch):
    """check_readiness('bpa', args) resolves via the CLI flag like preflight_error does."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    existing = tmp_path / "TabularEditor.exe"
    existing.write_text("binary", encoding="utf-8")

    class _Args:
        tabular_editor_path = str(existing)

    monkeypatch.setattr(registry, "ANALYZERS_JSON", registry.ANALYZERS_JSON)
    result = registry.check_readiness("bpa", _Args())

    assert result["ready"] is True
    assert result["resolved_path"] == str(existing.resolve())


@pytest.mark.fab_test
def test_check_readiness_non_bootstrapped_analyzer_is_always_ready():
    """Analyzers with no external tool (pql_lint, pql_test, ...) are always ready."""
    result = check_readiness("pql_lint", None)

    assert result["ready"] is True
    assert result["resolved_path"] is None
    assert "no external tool" in result["reason"]


@pytest.mark.fab_test
def test_check_readiness_returns_same_shape_for_every_analyzer():
    """Every analyzer's readiness dict has the same four keys (stable for `doctor`)."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import ANALYZER_REGISTRY

    expected_keys = {"ready", "resolved_path", "reason", "remediation"}
    for name in ANALYZER_REGISTRY:
        result = check_readiness(name, None)
        assert set(result.keys()) == expected_keys, f"{name} readiness shape mismatch"
