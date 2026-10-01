"""Tool-bootstrap progress notes are workflow commands only under CI.

Terse CLI Output epic, "CI Notices Only In CI" task. `::notice::` is GitHub
Actions syntax; on a laptop it is a prefix that means nothing.
"""

import json
import zipfile
from pathlib import Path

import pytest

from fab_test.scripts._analyzer_tool_bootstrap import _notice, resolve_executable

pytestmark = pytest.mark.fab_test


def _downloadable_tool(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    "pbir_inspector": {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    exe = tmp_path / "PBIRInspectorCLI"
    exe.write_text("#!/bin/sh\necho hi", encoding="utf-8")
    archive = tmp_path / "tool.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(exe, arcname="PBIRInspectorCLI")
    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", archive.as_uri())
    return metadata, repo_root


def _outside_ci(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)


def test_a_local_download_says_what_it_is_doing_without_the_workflow_prefix(tmp_path, monkeypatch, capsys):
    """Given no CI variable, should narrate the download and resolve steps as plain text."""
    _outside_ci(monkeypatch)
    metadata, repo_root = _downloadable_tool(tmp_path, monkeypatch)

    resolve_executable("pbir_inspector", metadata, repo_root)
    out = capsys.readouterr().out

    assert "::notice::" not in out
    assert "pbir_inspector: executable not found; downloading" in out
    assert "pbir_inspector: resolved executable at" in out


@pytest.mark.parametrize("variable", ["GITHUB_ACTIONS", "CI"])
def test_a_ci_download_keeps_the_workflow_command(variable, tmp_path, monkeypatch, capsys):
    """Given GITHUB_ACTIONS or CI, should emit ::notice:: exactly as before."""
    _outside_ci(monkeypatch)
    monkeypatch.setenv(variable, "true")
    metadata, repo_root = _downloadable_tool(tmp_path, monkeypatch)

    resolve_executable("pbir_inspector", metadata, repo_root)
    out = capsys.readouterr().out

    assert "::notice::pbir_inspector: executable not found; downloading" in out
    assert "::notice::pbir_inspector: resolved executable at" in out


def test_notice_formats_by_environment(monkeypatch, capsys):
    """Given the same message, should prefix it only when CI is set."""
    _outside_ci(monkeypatch)
    _notice("hello")
    monkeypatch.setenv("CI", "1")
    _notice("hello")

    assert capsys.readouterr().out.splitlines() == ["hello", "::notice::hello"]
