"""Tool bootstrap: the source-build acquisition method (`archive_type: npm_build`).

Scope
-----
Split out of test_fab_test_tool_bootstrap.py (module budget) once this
section grew large enough to push that file over its hard line budget.
Covers downloading a source archive, running npm install/build, resolving
the declared build entry point, version-keyed cache reuse/rebuild, build
failure cleanup, and doctor's Node/npm readiness reporting -- added for the
PBIR Accessibility Integration epic's Node Toolchain Bootstrap task.

    pytest -m fab_test tests/test_pbir_a11y_tool_bootstrap.py
"""
import json
import unittest.mock
import zipfile
from pathlib import Path

import pytest

from fab_test.scripts._analyzer_tool_bootstrap import (
    _current_platform,
    probe_executable,
    resolve_executable,
)
from fab_test.scripts._npm_toolchain import run_npm_build


def _write_npm_build_zip(zip_path: Path, nested_dir_name: str, build_script: str) -> None:
    """Write a zip mimicking a GitHub tag-archive: everything nested under one
    top-level folder whose name isn't known in advance, containing a
    ``package.json`` and a ``build.js`` the ``build`` script runs.
    """
    src_root = zip_path.parent / f"{zip_path.stem}-src"
    project_dir = src_root / nested_dir_name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "package.json").write_text(
        json.dumps({"name": "fake-a11y", "version": "1.0.0", "scripts": {"build": "node build.js"}}),
        encoding="utf-8",
    )
    (project_dir / "build.js").write_text(build_script, encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in project_dir.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(src_root)))


_BUILD_OK = (
    "const fs = require('fs');"
    "fs.mkdirSync('dist', {recursive: true});"
    "fs.writeFileSync('dist/cli.js', '// built ok\\n');"
)
_BUILD_FAILS = "process.exit(3);"


def _metadata_for_npm_build(
    repo_root: Path, analyzer_name: str, install_url: str, version: str = "1.0.0"
) -> Path:
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_A11Y_PATH",
                            "default_path": "",
                            "install_url_env_var": "PBIR_A11Y_INSTALL_URL",
                            "install_url": install_url,
                            "archive_type": "npm_build",
                            "build_entrypoint": "dist/cli.js",
                            "version": version,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return metadata


@pytest.mark.fab_test
def test_resolve_executable_builds_from_source_via_npm(tmp_path, monkeypatch):
    """`archive_type: npm_build` downloads a source archive, runs npm install/build,
    and resolves the declared build entry point -- a real subprocess call against
    the real npm/node on this machine, no dependencies fetched (empty package.json).
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"

    zip_path = tmp_path / "source.zip"
    _write_npm_build_zip(zip_path, "fake-a11y-1.0.0", _BUILD_OK)
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, zip_path.as_uri())

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.delenv("PBIR_A11Y_INSTALL_URL", raising=False)

    resolved = resolve_executable(analyzer_name, metadata, repo_root)

    assert resolved.exists()
    assert resolved.name == "cli.js"
    assert "built ok" in resolved.read_text(encoding="utf-8")


@pytest.mark.fab_test
def test_npm_build_reuses_cache_without_rebuilding(tmp_path, monkeypatch):
    """A second resolve at the same version never re-downloads or re-builds."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"

    zip_path = tmp_path / "source.zip"
    _write_npm_build_zip(zip_path, "fake-a11y-1.0.0", _BUILD_OK)
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, zip_path.as_uri())

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.delenv("PBIR_A11Y_INSTALL_URL", raising=False)

    first = resolve_executable(analyzer_name, metadata, repo_root)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("must not rebuild when the versioned cache already has a hit")

    monkeypatch.setattr(
        "fab_test.scripts._analyzer_tool_bootstrap._download", _fail_if_called
    )
    monkeypatch.setattr(
        "fab_test.scripts._analyzer_tool_bootstrap.run_npm_build", _fail_if_called
    )

    second = resolve_executable(analyzer_name, metadata, repo_root)

    assert second == first


@pytest.mark.fab_test
def test_a_version_bump_triggers_a_fresh_build_for_npm_build(tmp_path, monkeypatch):
    """A newer pinned version is a cache miss for the source-build path too,
    same as the zip-extract path -- both share `_cache_dir`.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"

    old_zip = tmp_path / "old.zip"
    _write_npm_build_zip(old_zip, "fake-a11y-1.0.0", _BUILD_OK)
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, old_zip.as_uri(), "1.0.0")

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.delenv("PBIR_A11Y_INSTALL_URL", raising=False)

    first = resolve_executable(analyzer_name, metadata, repo_root)
    old_cache_dir = repo_root / ".fab-test-tools" / analyzer_name / _current_platform() / "1.0.0"
    assert old_cache_dir.exists()

    new_zip = tmp_path / "new.zip"
    _write_npm_build_zip(
        new_zip,
        "fake-a11y-2.0.0",
        "const fs = require('fs'); fs.mkdirSync('dist', {recursive: true}); "
        "fs.writeFileSync('dist/cli.js', '// built ok v2\\n');",
    )
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, new_zip.as_uri(), "2.0.0")

    second = resolve_executable(analyzer_name, metadata, repo_root)

    assert second != first
    assert "v2" in second.read_text(encoding="utf-8")
    # The old version's cache is left alone -- clean-tools removes it, not a fresh resolve.
    assert old_cache_dir.exists()


@pytest.mark.fab_test
def test_npm_build_failure_leaves_no_partial_cache(tmp_path, monkeypatch):
    """A failing `npm run build` names the step, and leaves nothing for a later
    run to mistake for a working install.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"

    zip_path = tmp_path / "source.zip"
    _write_npm_build_zip(zip_path, "fake-a11y-1.0.0", _BUILD_FAILS)
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, zip_path.as_uri())

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.delenv("PBIR_A11Y_INSTALL_URL", raising=False)

    with pytest.raises(RuntimeError, match="npm run build"):
        resolve_executable(analyzer_name, metadata, repo_root)

    cache_dir = repo_root / ".fab-test-tools" / analyzer_name / _current_platform() / "1.0.0"
    assert not (cache_dir / "extracted").exists()
    assert not (cache_dir / "resolved-executable.txt").exists()


@pytest.mark.fab_test
def test_npm_build_reports_npm_missing_with_install_instructions(tmp_path, monkeypatch):
    """npm absent fails clearly, naming Node.js as the fix, not a bare traceback."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"

    zip_path = tmp_path / "source.zip"
    _write_npm_build_zip(zip_path, "fake-a11y-1.0.0", _BUILD_OK)
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, zip_path.as_uri())

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.delenv("PBIR_A11Y_INSTALL_URL", raising=False)
    monkeypatch.setattr(
        "fab_test.scripts._analyzer_tool_bootstrap.shutil.which", lambda _name: None
    )

    with pytest.raises(RuntimeError, match="npm not found on PATH"):
        resolve_executable(analyzer_name, metadata, repo_root)


@pytest.mark.fab_test
def test_npm_build_installs_declared_extra_dependencies(tmp_path):
    """`build_extra_dependencies` becomes a second, distinct `npm install` call --
    the workaround for a tool whose committed package.json is missing a real
    dependency its build needs (discovered against pbir-a11y v0.3.2).
    """
    build_root = tmp_path / "project"
    build_root.mkdir()
    (build_root / "package.json").write_text("{}", encoding="utf-8")

    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(command, **_kwargs):
        calls.append(command)
        return _Result()

    with unittest.mock.patch(
        "fab_test.scripts._analyzer_tool_bootstrap.subprocess.run", _fake_run
    ), unittest.mock.patch(
        "fab_test.scripts._analyzer_tool_bootstrap.shutil.which",
        lambda name: f"/usr/bin/{name}",
    ):
        run_npm_build("pbir_a11y", build_root, {"build_extra_dependencies": ["docx@^9.6.1"]})

    assert calls[0][1:] == ["install"]
    assert calls[1][1:] == ["install", "docx@^9.6.1"]
    assert calls[2][1:] == ["run", "build"]


@pytest.mark.fab_test
def test_probe_executable_reports_node_missing_for_npm_build(tmp_path, monkeypatch):
    """`doctor`'s engine names Node.js specifically, distinct from npm being absent."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, "https://example.com/source.zip")

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.setattr(
        "fab_test.scripts._analyzer_tool_bootstrap.shutil.which", lambda _name: None
    )

    result = probe_executable(analyzer_name, metadata, repo_root)

    assert result["ready"] is False
    assert "Node.js" in result["reason"]
    assert "nodejs.org" in result["remediation"]


@pytest.mark.fab_test
def test_probe_executable_reports_npm_missing_distinctly_from_node(tmp_path, monkeypatch):
    """Node present but npm absent is a distinct, separately-named failure."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"
    metadata = _metadata_for_npm_build(repo_root, analyzer_name, "https://example.com/source.zip")

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.setattr(
        "fab_test.scripts._analyzer_tool_bootstrap.shutil.which",
        lambda name: ("/usr/bin/node" if name == "node" else None),
    )

    result = probe_executable(analyzer_name, metadata, repo_root)

    assert result["ready"] is False
    assert "npm" in result["reason"]
    assert "Node.js is present" in result["remediation"]


@pytest.mark.fab_test
def test_probe_executable_reports_not_yet_built_when_toolchain_is_ready(tmp_path, monkeypatch):
    """Node and npm both present, nothing cached yet: reports the build that
    *would* run, distinct from the zip path's "not yet downloaded" wording.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_a11y"
    metadata = _metadata_for_npm_build(
        repo_root, analyzer_name, "https://example.com/source.zip", "0.3.2"
    )

    monkeypatch.delenv("PBIR_A11Y_PATH", raising=False)
    monkeypatch.setattr(
        "fab_test.scripts._analyzer_tool_bootstrap.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    result = probe_executable(analyzer_name, metadata, repo_root)

    assert result["ready"] is False
    assert result["reason"] == "not yet built"
    assert "build version 0.3.2 from source" in result["remediation"]
