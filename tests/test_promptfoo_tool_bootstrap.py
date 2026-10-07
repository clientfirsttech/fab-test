"""Tool bootstrap: the npm-registry acquisition method (`archive_type: npm_package`).

Scope
-----
promptfoo (the Data Agent Testing epic's Promptfoo Tool Seam) ships as a
published npm package rather than a release zip or a source archive, so it
gets its own acquisition method: `npm install <package>@<version>` into the
versioned cache, resolving the package's declared `bin` entry point. Also
covers the per-architecture `platform_limitations` doctor reports
(promptfoo's `@libsql/win32-arm64-msvc` dependency is unpublished) and the
`data-agent` readiness/preflight wiring.

    pytest -m fab_test tests/test_promptfoo_tool_bootstrap.py
"""
import argparse
import io
import json
import re
import tarfile
from pathlib import Path

import pytest

from fab_test.scripts import _analyzer_tool_bootstrap as bootstrap
from fab_test.scripts import fab_test_registry as registry
from fab_test.scripts._analyzer_tool_bootstrap import (
    UnsupportedPlatformError,
    probe_executable,
    resolve_executable,
)

_ANALYZER = "data_agent"
_ARM64_LIMITATION = "promptfoo needs @libsql/win32-arm64-msvc, which is not published."


def _write_package_tarball(tmp_path: Path, version: str = "1.0.0", marker: str = "ok") -> Path:
    """Write an npm-style tarball (everything under ``package/``) for a fake
    ``promptfoo`` whose ``bin`` points at a nested entry point, as the real one does.
    """
    files = {
        "package/package.json": json.dumps(
            {"name": "promptfoo", "version": version, "bin": {"promptfoo": "dist/src/entrypoint.js"}}
        ),
        "package/dist/src/entrypoint.js": f"// promptfoo {marker}\n",
    }
    tarball = tmp_path / f"promptfoo-{version}.tgz"
    with tarfile.open(tarball, "w:gz") as tf:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return tarball


def _metadata(repo_root: Path, version: str = "1.0.0", **extra) -> Path:
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    tool_install = {
        "env_var": "PROMPTFOO_PATH",
        "default_path": "",
        "install_url_env_var": "PROMPTFOO_INSTALL_URL",
        "archive_type": "npm_package",
        "package": "promptfoo",
        "version": version,
        **extra,
    }
    metadata.write_text(
        json.dumps({"analyzer_registry": {_ANALYZER: {"tool_install": tool_install}}}), encoding="utf-8"
    )
    return metadata


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPTFOO_PATH", raising=False)
    monkeypatch.delenv("PROMPTFOO_INSTALL_URL", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    return root


# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_resolve_executable_installs_the_package_and_resolves_its_bin(tmp_path, repo_root, monkeypatch):
    """A real `npm install` against the real npm on this machine, fed a local
    tarball through the install-URL override so no registry is contacted.
    """
    monkeypatch.setenv("PROMPTFOO_INSTALL_URL", str(_write_package_tarball(tmp_path)))

    resolved = resolve_executable(_ANALYZER, _metadata(repo_root), repo_root)

    assert resolved.name == "entrypoint.js"
    assert "promptfoo ok" in resolved.read_text(encoding="utf-8")
    assert (repo_root / ".fab-test-tools") in resolved.parents


@pytest.mark.fab_test
def test_npm_package_reuses_cache_without_reinstalling(tmp_path, repo_root, monkeypatch):
    """A second resolve at the same pinned version never runs npm again."""
    monkeypatch.setenv("PROMPTFOO_INSTALL_URL", str(_write_package_tarball(tmp_path)))
    metadata = _metadata(repo_root)
    first = resolve_executable(_ANALYZER, metadata, repo_root)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("must not reinstall when the versioned cache already has a hit")

    monkeypatch.setattr(bootstrap, "install_npm_package", _fail_if_called)

    assert resolve_executable(_ANALYZER, metadata, repo_root) == first


@pytest.mark.fab_test
def test_npm_package_installs_the_pinned_version_from_the_registry_by_default(repo_root, monkeypatch):
    """Without an override, the install spec is exactly `<package>@<pinned version>`."""
    specs: list[str] = []

    def _fake_install(_analyzer, _tool_install, spec, install_dir):
        specs.append(spec)
        entrypoint = install_dir / "entrypoint.js"
        entrypoint.parent.mkdir(parents=True, exist_ok=True)
        entrypoint.write_text("", encoding="utf-8")
        return entrypoint

    monkeypatch.setattr(bootstrap, "install_npm_package", _fake_install)

    resolve_executable(_ANALYZER, _metadata(repo_root, "0.124.0"), repo_root)

    assert specs == ["promptfoo@0.124.0"]


@pytest.mark.fab_test
def test_npm_package_failure_leaves_no_partial_cache(tmp_path, repo_root, monkeypatch):
    """A failed `npm install` names the step and leaves nothing a later run would trust."""
    monkeypatch.setenv("PROMPTFOO_INSTALL_URL", str(tmp_path / "does-not-exist.tgz"))

    with pytest.raises(RuntimeError, match="npm install"):
        resolve_executable(_ANALYZER, _metadata(repo_root), repo_root)

    cache_dir = repo_root / ".fab-test-tools" / _ANALYZER / bootstrap._current_platform() / "1.0.0"
    assert not (cache_dir / "extracted").exists()
    assert not (cache_dir / "resolved-executable.txt").exists()


@pytest.mark.fab_test
def test_npm_package_names_node_when_npm_is_missing(repo_root, monkeypatch):
    """No npm on PATH fails naming Node.js and the declared minimum, not a traceback."""
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _name: None)
    metadata = _metadata(repo_root, requires_runtime={"name": "node", "min_major": 22})

    with pytest.raises(RuntimeError, match=r"Node\.js.*>= 22"):
        resolve_executable(_ANALYZER, metadata, repo_root)


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_probe_reports_the_install_that_would_run(repo_root, monkeypatch):
    """Toolchain present, nothing cached: names the package and pin, installs nothing."""
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: f"/usr/bin/{name}")

    result = probe_executable(_ANALYZER, _metadata(repo_root, "0.124.0"), repo_root)

    assert result["ready"] is False
    assert result["reason"] == "not yet installed"
    assert "promptfoo@0.124.0" in result["remediation"]
    assert not (repo_root / ".fab-test-tools").exists()


@pytest.mark.fab_test
def test_probe_reports_node_missing_for_an_npm_package(repo_root, monkeypatch):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _name: None)

    result = probe_executable(_ANALYZER, _metadata(repo_root), repo_root)

    assert result["ready"] is False
    assert "Node.js" in result["reason"]


@pytest.mark.fab_test
def test_probe_names_a_declared_platform_limitation(repo_root, monkeypatch):
    """On an architecture the pinned install cannot support, doctor says why
    and what to do, rather than reporting an install that would fail opaquely.
    """
    monkeypatch.setattr(bootstrap, "_current_platform_key", lambda: "win32-arm64")
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: f"/usr/bin/{name}")
    metadata = _metadata(repo_root, platform_limitations={"win32-arm64": _ARM64_LIMITATION})

    result = probe_executable(_ANALYZER, metadata, repo_root)

    assert result["ready"] is False
    assert result["reason"] == "not supported on win32-arm64"
    assert "@libsql/win32-arm64-msvc" in result["remediation"]
    assert "PROMPTFOO_PATH" in result["remediation"]


@pytest.mark.fab_test
def test_a_platform_limitation_does_not_apply_elsewhere(repo_root, monkeypatch):
    monkeypatch.setattr(bootstrap, "_current_platform_key", lambda: "win32-x64")
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: f"/usr/bin/{name}")
    metadata = _metadata(repo_root, platform_limitations={"win32-arm64": _ARM64_LIMITATION})

    assert probe_executable(_ANALYZER, metadata, repo_root)["reason"] == "not yet installed"


@pytest.mark.fab_test
def test_resolve_refuses_to_install_on_a_limited_platform(repo_root, monkeypatch):
    """The run path refuses with the same remediation (exit 126 via preflight)."""
    monkeypatch.setattr(bootstrap, "_current_platform_key", lambda: "win32-arm64")
    metadata = _metadata(repo_root, platform_limitations={"win32-arm64": _ARM64_LIMITATION})

    with pytest.raises(UnsupportedPlatformError, match="@libsql/win32-arm64-msvc"):
        resolve_executable(_ANALYZER, metadata, repo_root)


@pytest.mark.fab_test
def test_an_explicit_path_bypasses_a_platform_limitation(tmp_path, repo_root, monkeypatch):
    """The limitation is the pinned install's, not the tool's: a promptfoo the
    user provides (e.g. under x64 emulation) is used as given.
    """
    provided = tmp_path / "entrypoint.js"
    provided.write_text("", encoding="utf-8")
    monkeypatch.setenv("PROMPTFOO_PATH", str(provided))
    monkeypatch.setattr(bootstrap, "_current_platform_key", lambda: "win32-arm64")
    metadata = _metadata(repo_root, platform_limitations={"win32-arm64": _ARM64_LIMITATION})

    assert resolve_executable(_ANALYZER, metadata, repo_root) == provided.resolve()
    assert probe_executable(_ANALYZER, metadata, repo_root)["ready"] is True


@pytest.mark.fab_test
def test_platform_key_normalizes_the_architecture(monkeypatch):
    monkeypatch.setattr(bootstrap, "_current_platform", lambda: "win32")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "ARM64")
    assert bootstrap._current_platform_key() == "win32-arm64"

    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "AMD64")
    assert bootstrap._current_platform_key() == "win32-x64"


# --------------------------------------------------------------------------- #
# The shipped pin and the data-agent wiring
# --------------------------------------------------------------------------- #


def _shipped_tool_install() -> dict:
    data = json.loads(registry.ANALYZERS_JSON.read_text(encoding="utf-8"))
    return data["analyzer_registry"][_ANALYZER]["tool_install"]


@pytest.mark.fab_test
def test_promptfoo_is_pinned_to_an_exact_version():
    """A range would let two installs of the same fab-test run different promptfoos."""
    tool_install = _shipped_tool_install()

    assert tool_install["archive_type"] == "npm_package"
    assert tool_install["package"] == "promptfoo"
    assert re.fullmatch(r"\d+\.\d+\.\d+", tool_install["version"])
    assert tool_install["release_source"] == {"type": "npm", "package": "promptfoo"}


@pytest.mark.fab_test
def test_promptfoo_declares_node_and_the_arm64_limitation():
    tool_install = _shipped_tool_install()

    assert tool_install["requires_runtime"]["name"] == "node"
    assert tool_install["requires_runtime"]["min_major"] >= 22  # promptfoo 0.124 engines: node >= 22.22
    assert "@libsql/win32-arm64-msvc" in tool_install["platform_limitations"]["win32-arm64"]


@pytest.mark.fab_test
def test_data_agent_readiness_probes_promptfoo(monkeypatch):
    """`doctor`'s engine resolves `data-agent` to the promptfoo tool, not "no tool required"."""
    monkeypatch.setenv("FAB_TEST_ENABLE_DATA_AGENT", "1")  # off by default (Feature Flags epic)
    calls: list[str] = []

    def _fake_probe(analyzer_name, *_a, **_k):
        calls.append(analyzer_name)
        return {"ready": True, "resolved_path": "x", "reason": "r", "remediation": None, "version": "1"}

    monkeypatch.setattr(registry, "probe_executable", _fake_probe)

    registry.check_readiness(_ANALYZER, None)

    assert calls == [_ANALYZER]


@pytest.mark.fab_test
def test_data_agent_preflight_exits_127_naming_node_when_npm_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("FAB_TEST_ENABLE_DATA_AGENT", "1")
    monkeypatch.setattr(registry, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("PROMPTFOO_PATH", raising=False)
    monkeypatch.delenv("PROMPTFOO_INSTALL_URL", raising=False)
    monkeypatch.setattr(bootstrap, "_current_platform_key", lambda: "linux-x64")
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _name: None)

    message, code = registry.preflight_error(_ANALYZER, argparse.Namespace())

    assert code == 127
    assert "Node.js" in message
