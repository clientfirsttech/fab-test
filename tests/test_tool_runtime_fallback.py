"""`tool_install.runtime_fallback`: an older pin used when the pin's runtime is missing.

fab-inspector 4.x needs .NET 10 and won't start on .NET 8 (.NET never rolls
back), so a machine with only .NET 8 runs the last release that does, 3.4.0,
and says so every run. See the fab-inspector .NET 8 Fallback epic.
"""

from __future__ import annotations

import json
import unittest.mock
import zipfile
from pathlib import Path

import pytest

from fab_test.scripts._analyzer_tool_bootstrap import probe_executable, resolve_executable

ANALYZER = "pbir_inspector"


def _zip(path: Path, body: str) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("FabInspCLI/fab-inspector.exe", body)
    return path


def _metadata(tmp_path: Path, *, fallback: bool = True) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    tool_install = {
        "env_var": "PBIR_INSPECTOR_PATH",
        "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
        "install_urls": {"win32": _zip(tmp_path / "pin.zip", "4.0.1").as_uri()},
        "archive_type": "zip",
        "executable_subpaths": {"win32": "FabInspCLI/fab-inspector.exe"},
        "version": "4.0.1",
        "requires_runtime": {"name": "dotnet", "min_major": 10},
    }
    if fallback:
        tool_install["runtime_fallback"] = {
            "version": "3.4.0",
            "install_urls": {"win32": _zip(tmp_path / "fallback.zip", "3.4.0").as_uri()},
            "requires_runtime": {"name": "dotnet", "min_major": 8},
        }
    metadata.write_text(
        json.dumps({"analyzer_registry": {ANALYZER: {"tool_install": tool_install}}}), encoding="utf-8"
    )
    return metadata, repo_root


@pytest.fixture
def dotnet(monkeypatch):
    """Set the .NET runtime majors the machine reports, on Windows, outside CI."""
    for name in ("PBIR_INSPECTOR_PATH", "PBIR_INSPECTOR_INSTALL_URL", "GITHUB_ACTIONS", "CI"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("sys.platform", "win32")

    def _installed(*majors: int) -> None:
        monkeypatch.setattr(
            "fab_test.scripts._tool_runtime._installed_dotnet_majors", lambda: sorted(majors)
        )

    return _installed


@pytest.mark.pbir
def test_given_only_the_fallback_runtime_should_download_and_say_the_fallback(tmp_path, dotnet, capsys):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(8)

    resolved = resolve_executable(ANALYZER, metadata, repo_root)

    assert resolved.read_text(encoding="utf-8") == "3.4.0"
    assert repo_root / ".fab-test-tools" / ANALYZER / "win32" / "3.4.0" in resolved.parents
    err = capsys.readouterr().err
    assert "using fallback version 3.4.0" in err
    assert ".NET 10+ runtime not found (installed: 8.x)" in err
    assert "Install the .NET 10 runtime to use 4.0.1: https://dotnet.microsoft.com/download/dotnet/10.0" in err


@pytest.mark.pbir
def test_given_a_cached_fallback_should_still_say_it_on_every_run(tmp_path, dotnet, capsys):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(8)
    resolve_executable(ANALYZER, metadata, repo_root)
    capsys.readouterr()

    resolve_executable(ANALYZER, metadata, repo_root)

    assert "using fallback version 3.4.0" in capsys.readouterr().err


@pytest.mark.pbir
def test_given_the_pin_s_runtime_should_resolve_the_pin_without_a_fallback_line(tmp_path, dotnet, capsys):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(8, 10)

    resolved = resolve_executable(ANALYZER, metadata, repo_root)

    assert resolved.read_text(encoding="utf-8") == "4.0.1"
    assert "fallback" not in capsys.readouterr().err


@pytest.mark.pbir
def test_given_ci_should_annotate_the_fallback_as_a_warning(tmp_path, dotnet, capsys, monkeypatch):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(8)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    resolve_executable(ANALYZER, metadata, repo_root)

    assert "::warning::pbir_inspector: using fallback version 3.4.0" in capsys.readouterr().err


@pytest.mark.pbir
def test_given_an_explicit_binary_should_not_claim_a_fallback(tmp_path, dotnet, capsys, monkeypatch):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(8)
    own = tmp_path / "own" / "fab-inspector.exe"
    own.parent.mkdir()
    own.write_text("mine", encoding="utf-8")

    resolved = resolve_executable(ANALYZER, metadata, repo_root, explicit_path=str(own))
    probed = probe_executable(ANALYZER, metadata, repo_root, explicit_path=str(own))

    assert resolved == own.resolve()
    assert "fallback" not in capsys.readouterr().err
    assert "fallback" not in probed["reason"]


@pytest.mark.pbir
def test_doctor_given_a_cached_fallback_should_report_ready_with_the_fallback_note(tmp_path, dotnet):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(8)
    resolve_executable(ANALYZER, metadata, repo_root)

    result = probe_executable(ANALYZER, metadata, repo_root)

    assert result["ready"] is True
    assert result["status"] == "warning"  # doctor's ⚠: runs, but on an unsupported runtime; prints the remedy
    assert result["version"] == "3.4.0"
    assert "using fallback version 3.4.0" in result["reason"]
    assert result["remediation"] == (
        "Install the .NET 10 runtime to use 4.0.1: https://dotnet.microsoft.com/download/dotnet/10.0"
    )


@pytest.mark.pbir
def test_doctor_given_the_fallback_not_yet_downloaded_should_name_the_fallback_download(tmp_path, dotnet):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(8)

    result = probe_executable(ANALYZER, metadata, repo_root)

    assert "Would download version 3.4.0 from" in result["remediation"]
    assert "fallback.zip" in result["remediation"]
    assert "Install the .NET 10 runtime to use 4.0.1" in result["remediation"]
    assert "using fallback version 3.4.0" in result["reason"]


@pytest.mark.pbir
def test_doctor_given_neither_runtime_should_name_the_pin_s_runtime(tmp_path, dotnet):
    metadata, repo_root = _metadata(tmp_path)
    dotnet(6)

    result = probe_executable(ANALYZER, metadata, repo_root)

    assert result["ready"] is False
    assert result["reason"] == ".NET 10+ runtime not found (installed: 6.x)"
    assert "fallback" not in result["reason"]


@pytest.mark.pbir
def test_doctor_without_a_declared_fallback_should_be_unchanged(tmp_path, dotnet):
    metadata, repo_root = _metadata(tmp_path, fallback=False)
    dotnet(8)

    result = probe_executable(ANALYZER, metadata, repo_root)

    assert result["ready"] is False
    assert result["reason"] == ".NET 10+ runtime not found (installed: 8.x)"


@pytest.mark.pbir
def test_resolve_without_a_declared_fallback_should_resolve_the_pin(tmp_path, dotnet, capsys):
    metadata, repo_root = _metadata(tmp_path, fallback=False)
    dotnet(8)

    with unittest.mock.patch("sys.platform", "win32"):
        resolved = resolve_executable(ANALYZER, metadata, repo_root)

    assert resolved.read_text(encoding="utf-8") == "4.0.1"
    assert "fallback" not in capsys.readouterr().err
