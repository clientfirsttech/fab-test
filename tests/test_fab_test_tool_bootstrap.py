"""Tool bootstrap: downloading, extracting, and checksum-verifying zip archives.

Scope
-----
resolve_executable's env-var/committed-URL precedence, platform-specific
install URLs and executable subpaths, requires_platform mismatches, and
_verify_checksum's install_sha256 verification before extraction.

    pytest -m fab_test
"""
import hashlib
import json
import unittest.mock
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import (
    UnsupportedPlatformError,
    _verify_checksum,
    resolve_executable,
)

# --------------------------------------------------------------------------- #
# Tool bootstrap with zip archives
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_resolve_executable_downloads_and_extracts_zip(tmp_path, monkeypatch):
    """Missing tool is downloaded from install URL and extracted from zip."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
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

    # Build a zip containing the expected executable.
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    exe = tool_dir / "PBIRInspectorCLI"
    exe.write_text("#!/bin/sh\necho hi", encoding="utf-8")
    zip_path = tmp_path / "tool.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(exe, arcname="PBIRInspectorCLI")

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI"


@pytest.mark.fab_test
def test_resolve_executable_prefers_existing_path(tmp_path, monkeypatch):
    """If the env-var path exists, resolve_executable uses it without downloading."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"
    existing = repo_root / "PBIRInspectorCLI"
    existing.write_text("existing", encoding="utf-8")
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
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

    monkeypatch.setenv("PBIR_INSPECTOR_PATH", str(existing))
    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", "http://example.com/tool.zip")
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved == existing.resolve()


@pytest.mark.fab_test
def test_resolve_executable_uses_committed_install_url(tmp_path, monkeypatch):
    """If no env var is set, a committed install_url in analyzers.json is used."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    # Build a local zip with the expected executable.
    tool_dir = tmp_path / "tool"
    tool_dir.mkdir()
    exe = tool_dir / "PBIRInspectorCLI"
    exe.write_text("#!/bin/sh\necho hi", encoding="utf-8")
    zip_path = tmp_path / "tool.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(exe, arcname="PBIRInspectorCLI")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_url": zip_path.as_uri(),
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    # Ensure no env var overrides are present.
    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI"


@pytest.mark.fab_test
def test_resolve_executable_env_install_url_wins_over_committed(tmp_path, monkeypatch):
    """The env-var install URL takes precedence over the committed install_url."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    # Committed zip contains the wrong executable name.
    committed_dir = tmp_path / "committed"
    committed_dir.mkdir()
    committed_exe = committed_dir / "PBIRInspectorCLI"
    committed_exe.write_text("committed", encoding="utf-8")
    committed_zip = tmp_path / "committed.zip"
    with zipfile.ZipFile(committed_zip, "w") as zf:
        zf.write(committed_exe, arcname="PBIRInspectorCLI")

    # Env-var zip contains a differently named executable.
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    env_exe = env_dir / "PBIRInspectorCLI-Env"
    env_exe.write_text("env", encoding="utf-8")
    env_zip = tmp_path / "env.zip"
    with zipfile.ZipFile(env_zip, "w") as zf:
        zf.write(env_exe, arcname="PBIRInspectorCLI-Env")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_url": committed_zip.as_uri(),
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI-Env",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", env_zip.as_uri())

    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI-Env"


@pytest.mark.fab_test
def test_resolve_executable_selects_platform_specific_url_and_subpath(tmp_path, monkeypatch):
    """Platform-specific install_urls and executable_subpaths are honored."""
    import zipfile

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    # Build a zip for each platform with a differently named executable.
    platform_assets = {}
    for platform in ("linux", "win32", "darwin"):
        asset_dir = tmp_path / platform
        asset_dir.mkdir()
        exe_name = f"fab-inspector-{platform}"
        if platform == "win32":
            exe_name += ".exe"
        exe = asset_dir / exe_name
        exe.write_text(f"#!/bin/sh\necho {platform}", encoding="utf-8")
        zip_path = tmp_path / f"{platform}.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(exe, arcname=exe_name)
        platform_assets[platform] = zip_path.as_uri()

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_urls": platform_assets,
                            "archive_type": "zip",
                            "executable_subpaths": {
                                "linux": "fab-inspector-linux",
                                "win32": "fab-inspector-win32.exe",
                                "darwin": "fab-inspector-darwin",
                            },
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    # Simulate running on Windows.
    with unittest.mock.patch("sys.platform", "win32"):
        resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "fab-inspector-win32.exe"

    # Simulate running on Linux.
    with unittest.mock.patch("sys.platform", "linux"):
        resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "fab-inspector-linux"


@pytest.mark.fab_test
def test_resolve_executable_requires_platform_mismatch_raises(tmp_path, monkeypatch):
    """If requires_platform does not match the current OS, raise RuntimeError."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "requires_platform": "linux",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)

    with (
        unittest.mock.patch("sys.platform", "win32"),
        pytest.raises(UnsupportedPlatformError, match="not supported on win32"),
    ):
        resolve_executable(analyzer_name, metadata, repo_root)


# --------------------------------------------------------------------------- #
# Verify downloaded tool archives (checksum)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_verify_checksum_mismatch_deletes_file_and_raises(tmp_path):
    """A checksum mismatch removes the downloaded file and raises clearly."""
    archive = tmp_path / "tool.zip"
    archive.write_bytes(b"archive-bytes")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _verify_checksum(archive, "0" * 64, "pbir_inspector")

    assert not archive.exists()


@pytest.mark.fab_test
def test_verify_checksum_match_leaves_file_in_place(tmp_path):
    """A matching checksum does not delete the file or raise."""
    archive = tmp_path / "tool.zip"
    archive.write_bytes(b"archive-bytes")
    expected = hashlib.sha256(b"archive-bytes").hexdigest()

    _verify_checksum(archive, expected, "pbir_inspector")

    assert archive.exists()


def _write_zip_with_executable(zip_path: Path, exe_path: Path, arcname: str) -> None:
    import zipfile

    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("#!/bin/sh\necho hi", encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(exe_path, arcname=arcname)


@pytest.mark.fab_test
def test_resolve_executable_verifies_checksum_before_extraction(tmp_path, monkeypatch):
    """A correct install_sha256 verifies and resolution proceeds normally."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    tool_dir = tmp_path / "tool"
    exe = tool_dir / "PBIRInspectorCLI"
    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, exe, "PBIRInspectorCLI")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_sha256": digest,
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()
    assert resolved.name == "PBIRInspectorCLI"


@pytest.mark.fab_test
def test_resolve_executable_checksum_mismatch_raises_before_extraction(
    tmp_path, monkeypatch
):
    """A wrong install_sha256 raises and never extracts the archive."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    tool_dir = tmp_path / "tool"
    exe = tool_dir / "PBIRInspectorCLI"
    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, exe, "PBIRInspectorCLI")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_sha256": "0" * 64,
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        resolve_executable(analyzer_name, metadata, repo_root)

    extracted = repo_root / ".fab-test-tools" / analyzer_name / "extracted"
    assert not extracted.exists(), "archive must not be extracted on checksum mismatch"


@pytest.mark.fab_test
def test_resolve_executable_no_install_sha256_skips_verification(tmp_path, monkeypatch):
    """No install_sha256 declared preserves today's download-and-extract behavior."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    tool_dir = tmp_path / "tool"
    exe = tool_dir / "PBIRInspectorCLI"
    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, exe, "PBIRInspectorCLI")

    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
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

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    resolved = resolve_executable(analyzer_name, metadata, repo_root)
    assert resolved.exists()


# --------------------------------------------------------------------------- #
# Version-keyed cache (Tool Version Currency epic)
# --------------------------------------------------------------------------- #


def _metadata_with_version(repo_root: Path, analyzer_name: str, install_url: str, version: str) -> Path:
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
                            "default_path": "./PBIR-Inspector/PBIRInspectorCLI",
                            "install_url_env_var": "PBIR_INSPECTOR_INSTALL_URL",
                            "install_url": install_url,
                            "archive_type": "zip",
                            "executable_subpath": "PBIRInspectorCLI",
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
def test_resolve_executable_caches_under_a_version_keyed_path(tmp_path, monkeypatch):
    """A declared `version` makes the cache directory `<analyzer>/<platform>/<version>/`."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_inspector"

    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, tmp_path / "tool" / "PBIRInspectorCLI", "PBIRInspectorCLI")
    metadata = _metadata_with_version(repo_root, analyzer_name, zip_path.as_uri(), "3.4.0")

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    with unittest.mock.patch("sys.platform", "win32"):
        resolved = resolve_executable(analyzer_name, metadata, repo_root)

    assert resolved.exists()
    expected_cache_dir = repo_root / ".fab-test-tools" / analyzer_name / "win32" / "3.4.0"
    assert expected_cache_dir in resolved.parents


@pytest.mark.fab_test
def test_a_version_bump_ignores_the_old_cache_and_redownloads(tmp_path, monkeypatch):
    """A newer `version` in analyzers.json is a cache miss, not a silent reuse.

    This is the defect the epic exists to fix: a shipped pin bump used to
    never reach an existing checkout because the cache carried no version.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_inspector"

    old_zip = tmp_path / "old.zip"
    _write_zip_with_executable(old_zip, tmp_path / "old" / "PBIRInspectorCLI", "PBIRInspectorCLI")
    metadata = _metadata_with_version(repo_root, analyzer_name, old_zip.as_uri(), "3.4.0")

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    with unittest.mock.patch("sys.platform", "win32"):
        first = resolve_executable(analyzer_name, metadata, repo_root)
    assert first.exists()
    old_cache_dir = repo_root / ".fab-test-tools" / analyzer_name / "win32" / "3.4.0"
    assert old_cache_dir.exists()

    # Ship a newer version, pointing at a different archive.
    new_zip = tmp_path / "new.zip"
    _write_zip_with_executable(new_zip, tmp_path / "new" / "PBIRInspectorCLI", "PBIRInspectorCLI")
    metadata = _metadata_with_version(repo_root, analyzer_name, new_zip.as_uri(), "3.5.0")

    with unittest.mock.patch("sys.platform", "win32"):
        second = resolve_executable(analyzer_name, metadata, repo_root)

    assert second.exists()
    assert second != first, "a version bump must not resolve the stale cached executable"
    new_cache_dir = repo_root / ".fab-test-tools" / analyzer_name / "win32" / "3.5.0"
    assert new_cache_dir in second.parents
    # The old version's cache is left alone -- clean-tools removes it, not a fresh resolve.
    assert old_cache_dir.exists()


@pytest.mark.fab_test
def test_resolve_executable_reuses_cache_at_the_same_version_without_network(
    tmp_path, monkeypatch
):
    """A second resolve at the same declared version never calls the network."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_inspector"

    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, tmp_path / "tool" / "PBIRInspectorCLI", "PBIRInspectorCLI")
    metadata = _metadata_with_version(repo_root, analyzer_name, zip_path.as_uri(), "3.4.0")

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    with unittest.mock.patch("sys.platform", "win32"):
        first = resolve_executable(analyzer_name, metadata, repo_root)

    # Break the download path; a cache hit must never reach it.
    def _fail_if_called(*_a, **_k):
        raise AssertionError("must not download when the versioned cache already has a hit")

    monkeypatch.setattr(
        "fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap._download", _fail_if_called
    )

    with unittest.mock.patch("sys.platform", "win32"):
        second = resolve_executable(analyzer_name, metadata, repo_root)

    assert second == first


@pytest.mark.fab_test
def test_no_declared_version_uses_the_pre_epic_unversioned_cache_path(tmp_path, monkeypatch):
    """A `tool_install` with no `version` keeps resolving its pre-existing cache path."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    metadata.parent.mkdir(parents=True)
    analyzer_name = "pbir_inspector"

    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, tmp_path / "tool" / "PBIRInspectorCLI", "PBIRInspectorCLI")
    metadata.write_text(
        json.dumps(
            {
                "analyzer_registry": {
                    analyzer_name: {
                        "tool_install": {
                            "env_var": "PBIR_INSPECTOR_PATH",
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

    monkeypatch.setenv("PBIR_INSPECTOR_INSTALL_URL", zip_path.as_uri())
    with unittest.mock.patch("sys.platform", "win32"):
        resolved = resolve_executable(analyzer_name, metadata, repo_root)

    unversioned_cache_dir = repo_root / ".fab-test-tools" / analyzer_name / "win32"
    assert unversioned_cache_dir in resolved.parents
    # No stray version-named segment directly under the platform directory.
    assert resolved.relative_to(unversioned_cache_dir).parts[0] == "extracted"


@pytest.mark.fab_test
def test_probe_executable_reports_the_declared_version_on_a_cache_hit(tmp_path, monkeypatch):
    """`doctor`'s engine names the resolved version alongside a cached-download hit."""
    from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import probe_executable

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_inspector"

    zip_path = tmp_path / "tool.zip"
    _write_zip_with_executable(zip_path, tmp_path / "tool" / "PBIRInspectorCLI", "PBIRInspectorCLI")
    metadata = _metadata_with_version(repo_root, analyzer_name, zip_path.as_uri(), "3.4.0")

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)
    monkeypatch.delenv("PBIR_INSPECTOR_INSTALL_URL", raising=False)

    with unittest.mock.patch("sys.platform", "win32"):
        resolve_executable(analyzer_name, metadata, repo_root)
        result = probe_executable(analyzer_name, metadata, repo_root)

    assert result["ready"] is True
    assert result["version"] == "3.4.0"
    assert "3.4.0" in result["reason"]


@pytest.mark.fab_test
def test_probe_executable_names_the_env_var_shadowing_a_pinned_version(tmp_path, monkeypatch):
    """A local env-var override says so and names the variable to unset."""
    from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import probe_executable

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_inspector"
    shadow = tmp_path / "PBIRInspectorCLI"
    shadow.write_text("shadow", encoding="utf-8")
    metadata = _metadata_with_version(repo_root, analyzer_name, "https://example.com/tool.zip", "3.4.0")

    monkeypatch.setenv("PBIR_INSPECTOR_PATH", str(shadow))

    result = probe_executable(analyzer_name, metadata, repo_root)

    assert result["ready"] is True
    assert result["version"] is None
    assert "shadows pinned 3.4.0" in result["reason"]
    assert "PBIR_INSPECTOR_PATH" in result["remediation"]


@pytest.mark.fab_test
def test_probe_executable_cli_argument_never_gets_a_shadow_note(tmp_path, monkeypatch):
    """An explicit --path flag is a per-invocation choice, not a silent trap."""
    from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import probe_executable

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    analyzer_name = "pbir_inspector"
    explicit = tmp_path / "PBIRInspectorCLI"
    explicit.write_text("explicit", encoding="utf-8")
    metadata = _metadata_with_version(repo_root, analyzer_name, "https://example.com/tool.zip", "3.4.0")

    monkeypatch.delenv("PBIR_INSPECTOR_PATH", raising=False)

    result = probe_executable(analyzer_name, metadata, repo_root, explicit_path=str(explicit))

    assert result["ready"] is True
    assert "shadows" not in result["reason"]
    assert result["remediation"] is None


