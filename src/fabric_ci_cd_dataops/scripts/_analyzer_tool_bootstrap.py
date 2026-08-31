#!/usr/bin/env python3
"""Tool bootstrap helpers for fab-test analyzer wrappers.

Analyzers that depend on external binaries can declare a ``tool_install`` block
in ``.github/metadata/analyzers.json``. When the configured executable is missing
and an install URL is provided, this module downloads the archive, extracts it,
and returns the resolved executable path.

The cache directory is ``.fab-test-tools`` under the repository root. Each tool
gets a subfolder keyed by analyzer name. A marker file records the resolved
executable so subsequent runs reuse it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_READER_CHUNK_SIZE = 8192
_USER_AGENT = "fabric-ci-cd-dataops-fab-test/1.0"

# npm install can fetch a nontrivial dependency tree on a cold cache; build is
# just tsc over a small source tree and finishes in seconds once deps exist.
_NPM_INSTALL_TIMEOUT_SECONDS = 300
_NPM_BUILD_TIMEOUT_SECONDS = 120


class UnsupportedPlatformError(RuntimeError):
    """Raised when an analyzer's tool is not available on the current OS."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _is_ci() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def _cache_root(repo_root: Path) -> Path:
    return repo_root / ".fab-test-tools"


def _cache_dir(
    repo_root: Path, analyzer_name: str, platform: str, tool_install: dict[str, Any]
) -> Path:
    """Return this tool's cache directory, keyed by platform and, when declared,
    version.

    A ``tool_install.version`` bump changes this path, so a newer pin in
    analyzers.json is a cache miss rather than a silent reuse of the old
    binary -- the defect this module exists to fix. An entry with no
    ``version`` keeps the pre-existing unversioned (but still
    platform-keyed) path, so an override that predates this field keeps
    resolving exactly as it did before.
    """
    base = _cache_root(repo_root) / analyzer_name / platform
    version = tool_install.get("version")
    return (base / str(version)) if version else base


def _marker_path(cache_dir: Path) -> Path:
    return cache_dir / "resolved-executable.txt"


def _read_marker(cache_dir: Path) -> Path | None:
    marker = _marker_path(cache_dir)
    if not marker.exists():
        return None
    try:
        resolved = Path(marker.read_text(encoding="utf-8").strip())
        if resolved.exists():
            return resolved
    except (OSError, ValueError):
        pass
    return None


_ALLOWED_INSTALL_SCHEMES = frozenset({"https", "file"})


def _write_marker(cache_dir: Path, executable: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _marker_path(cache_dir).write_text(str(executable), encoding="utf-8")


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    """Download ``url`` to ``dest`` with a simple progress indicator in CI."""
    # https for real releases, file:// for the local-first and offline install paths.
    # Anything else (plain http, custom schemes) is refused rather than fetched.
    scheme = urlparse(url).scheme
    if scheme not in _ALLOWED_INSTALL_SCHEMES:
        raise RuntimeError(
            f"Refusing to download an analyzer from a {scheme or 'scheme-less'} URL: {url}"
        )
    request = Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 - scheme checked above
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(request, timeout=timeout) as response, open(dest, "wb") as fh:  # noqa: S310 - scheme checked above
        total = response.headers.get("Content-Length")
        total_int = int(total) if total else None
        downloaded = 0
        while True:
            chunk = response.read(_READER_CHUNK_SIZE)
            if not chunk:
                break
            fh.write(chunk)
            downloaded += len(chunk)
            if _is_ci() and total_int:
                pct = downloaded * 100 // total_int
                print(f"::notice::Downloading tool archive: {pct}%")


def _verify_checksum(path: Path, expected_sha256: str, analyzer_name: str) -> None:
    """Verify ``path``'s SHA-256 digest, deleting it and raising on mismatch."""
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual.lower() != expected_sha256.lower():
        path.unlink(missing_ok=True)
        raise RuntimeError(
            f"{analyzer_name}: downloaded archive checksum mismatch "
            f"(expected sha256={expected_sha256}, got {actual}). "
            "The download has been removed; check tool_install.install_sha256 "
            "in analyzers.json or the install URL."
        )


def _extract_zip(zip_path: Path, extract_dir: Path) -> None:
    """Extract a zip archive to ``extract_dir``."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)


def _find_executable(extract_dir: Path, subpath: str) -> Path | None:
    """Locate the executable inside the extracted archive.

    If ``subpath`` is provided, look for it directly. Otherwise do a shallow
    search for a file that matches the subpath basename or any executable file.
    """
    if subpath:
        candidate = extract_dir / subpath
        if candidate.exists():
            return candidate
        candidate = next(extract_dir.rglob(subpath), None)
        if candidate:
            return candidate

    # Fallback: first file with a known executable extension or executable bit.
    for child in extract_dir.rglob("*"):
        if not child.is_file():
            continue
        if child.suffix.lower() in {".exe", ".cmd", ".bat", ".sh"}:
            return child
        if os.access(child, os.X_OK):
            return child
    return None


def _clean_url_filename(url: str) -> str:
    """Derive a safe filename from a URL path."""
    parsed = urlparse(url)
    name = Path(parsed.path).name or "download.zip"
    # Strip query parameters and anchors that may have been included.
    return name.split("?")[0].split("#")[0]


def _current_platform() -> str:
    """Return a normalized platform key matching analyzers.json conventions.

    Values: ``linux``, ``win32``, ``darwin``.
    """
    plat = sys.platform
    if plat.startswith("linux"):
        return "linux"
    if plat == "darwin":
        return "darwin"
    if plat == "win32":
        return "win32"
    return plat


def _platform_specific(
    tool_install: dict[str, Any], key: str, platform: str
) -> str | None:
    """Return the platform-specific value for ``key`` if it exists.

    Falls back to the legacy single value when no platform-specific map exists.
    """
    mapping = tool_install.get(f"{key}s")
    if isinstance(mapping, dict):
        value = mapping.get(platform)
        if value:
            return str(value)
    return tool_install.get(key) or None


def _usable(path: Path) -> bool:
    return path.exists() and path.is_file()


def _local_candidates(
    tool_install: dict[str, Any], repo_root: Path, explicit_path: str | None
) -> list[tuple[str, Path]]:
    """Ordered non-download candidates: CLI argument, env var, default path."""
    env_var = tool_install.get("env_var", "")
    default_path = tool_install.get("default_path", "")
    candidates: list[tuple[str, Path]] = []
    if explicit_path:
        candidates.append(("CLI argument", Path(explicit_path)))
    if env_var and _env(env_var).strip():
        candidates.append((f"env var {env_var}", Path(_env(env_var).strip())))
    if default_path and default_path.strip():
        candidates.append(("default path", repo_root / default_path.strip()))
    return candidates


def _resolve_install_url(tool_install: dict[str, Any], platform: str) -> str:
    """Return the install URL to use: env var override, else the committed one."""
    install_url_env_var = tool_install.get("install_url_env_var", "")
    env_url = _env(install_url_env_var, "") if install_url_env_var else ""
    if env_url:
        return env_url
    return _platform_specific(tool_install, "install_url", platform) or ""


def load_analyzer_config(metadata_path: Path, analyzer_name: str) -> dict[str, Any] | None:
    """Load the analyzer registry entry from ``analyzers.json``."""
    if not metadata_path.exists():
        return None
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    registry = data.get("analyzer_registry", {})
    config = registry.get(analyzer_name)
    if not isinstance(config, dict):
        return None
    return config


def _shadow_note(source: str, tool_install: dict[str, Any]) -> tuple[str, str | None]:
    """Return a (reason suffix, remediation) pair when a local candidate shadows
    a declared pin.

    A CLI argument is a per-invocation choice, not a silent trap, so it never
    gets this note -- only an env var or a ``default_path`` file, which sit
    unnoticed indefinitely and never receive a version bump shipped in
    ``analyzers.json``.
    """
    version = tool_install.get("version")
    if not version or source == "CLI argument":
        return "", None
    if source.startswith("env var "):
        var_name = source[len("env var "):]
        return (
            f" (shadows pinned {version}; won't receive automatic updates)",
            f"Unset {var_name} to use the pinned {version} instead.",
        )
    if source == "default path":
        default_path = tool_install.get("default_path", "")
        return (
            f" (shadows pinned {version}; won't receive automatic updates)",
            f"Remove or move {default_path} to use the pinned {version} instead.",
        )
    return "", None


def _probe_pending_install(
    tool_install: dict[str, Any], install_url: str, pinned_version: str | None
) -> dict[str, Any]:
    """Return the not-ready-yet result for a tool with a resolvable install URL.

    Split out of ``probe_executable`` to keep its own return-statement count
    under the complexity ratchet -- the ``npm_build`` toolchain checks
    (Node/npm each reported as a distinct missing prerequisite) would
    otherwise push it over.
    """
    archive_type = tool_install.get("archive_type", "zip").lower()
    if archive_type == "npm_build":
        if shutil.which("node") is None:
            return {
                "ready": False,
                "resolved_path": None,
                "reason": "Node.js not found on PATH",
                "remediation": "Install Node.js >= 18 (https://nodejs.org), then re-run.",
                "version": None,
            }
        if shutil.which("npm") is None:
            return {
                "ready": False,
                "resolved_path": None,
                "reason": "npm not found on PATH",
                "remediation": "Node.js is present but npm is missing; reinstall Node.js "
                "(https://nodejs.org, >= 18) with npm included.",
                "version": None,
            }
        action = f"build version {pinned_version} from source at" if pinned_version else "build from source at"
    else:
        action = f"download version {pinned_version} from" if pinned_version else "download from"
    remediation = f"Would {action} {install_url} on first run."
    env_var = tool_install.get("env_var")
    if archive_type == "npm_build" and env_var:
        remediation += f" Or set {env_var}=<path> to a manually built executable to skip this."
    return {
        "ready": False,
        "resolved_path": None,
        "reason": "not yet built" if archive_type == "npm_build" else "not yet downloaded",
        "remediation": remediation,
        "version": None,
    }


def probe_executable(
    analyzer_name: str,
    metadata_path: Path,
    repo_root: Path,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    """Check whether ``analyzer_name``'s tool is (or would be) resolvable.

    Mirrors ``resolve_executable``'s resolution order but never downloads,
    extracts, or spawns a subprocess — it is the engine behind
    ``fab-test doctor``. When a download would be needed, the install URL
    that *would* be used is reported instead of being fetched.

    Returns a dict with:
      ready: bool
      resolved_path: str | None -- an already-usable path, if one exists
      reason: str               -- human explanation of the ready/not-ready state
      remediation: str | None   -- what to do (or what would happen) when not ready
      version: str | None       -- the declared version this result corresponds
                                    to, or None when unknown (e.g. a local
                                    candidate shadowing the pin)
    """
    config = load_analyzer_config(metadata_path, analyzer_name) or {}
    tool_install = config.get("tool_install") or {}
    env_var = tool_install.get("env_var", "")
    install_url_env_var = tool_install.get("install_url_env_var", "")
    pinned_version = tool_install.get("version")

    platform = _current_platform()
    requires_platform = tool_install.get("requires_platform")
    if requires_platform and platform != requires_platform:
        return {
            "ready": False,
            "resolved_path": None,
            "reason": f"not supported on {platform}",
            "remediation": (
                f"Supported platform: {requires_platform}. "
                f"Set {env_var}=<path> to use a manually provided executable."
            ),
            "version": None,
        }

    committed_install_url = _platform_specific(tool_install, "install_url", platform)

    for source, path in _local_candidates(tool_install, repo_root, explicit_path):
        if _usable(path):
            suffix, remediation = _shadow_note(source, tool_install)
            return {
                "ready": True,
                "resolved_path": str(path.resolve()),
                "reason": f"resolved via {source}{suffix}",
                "remediation": remediation,
                "version": None,
            }

    cache_dir = _cache_dir(repo_root, analyzer_name, platform, tool_install)
    cached = _read_marker(cache_dir)
    if cached:
        reason = "resolved via cached download"
        if pinned_version:
            reason += f" (version {pinned_version})"
        return {
            "ready": True,
            "resolved_path": str(cached.resolve()),
            "reason": reason,
            "remediation": None,
            "version": pinned_version,
        }

    install_url = _env(install_url_env_var, "") if install_url_env_var else ""
    if not install_url:
        install_url = committed_install_url or ""
    if install_url:
        return _probe_pending_install(tool_install, install_url, pinned_version)

    return {
        "ready": False,
        "resolved_path": None,
        "version": None,
        "reason": "no executable found and no install URL configured",
        "remediation": (
            f"Set {env_var}=<path> to a manually provided executable."
            if env_var
            else "No automatic resolution is configured for this analyzer."
        ),
    }


def resolve_executable(
    analyzer_name: str,
    metadata_path: Path,
    repo_root: Path,
    explicit_path: str | None = None,
) -> Path:
    """Resolve the executable for ``analyzer_name``.

    Resolution order:
      1. ``explicit_path`` if provided and exists.
      2. Path from ``tool_install.env_var`` if set and exists.
      3. ``tool_install.default_path`` relative to repo root if exists.
      4. Cached resolved executable in ``.fab-test-tools/<analyzer>``.
      5. Download from ``tool_install.install_url_env_var`` URL, extract zip,
         locate executable, cache the result.
      6. Download from ``tool_install.install_url`` (committed fallback) URL,
         extract zip, locate executable, cache the result.
      7. Raise ``RuntimeError`` with instructions.

    Args:
        analyzer_name: Registry name of the analyzer.
        metadata_path: Path to ``analyzers.json``.
        repo_root: Repository root used to resolve default/cache paths.
        explicit_path: Optional override path (e.g. from CLI flag).

    Returns:
        Absolute path to the resolved executable.

    Raises:
        RuntimeError: If the executable cannot be resolved.
    """
    config = load_analyzer_config(metadata_path, analyzer_name) or {}
    tool_install = config.get("tool_install") or {}
    archive_type = tool_install.get("archive_type", "zip")

    platform = _current_platform()
    _require_supported_platform(analyzer_name, tool_install, platform)

    for _source, path in _local_candidates(tool_install, repo_root, explicit_path):
        if _usable(path):
            return path.resolve()

    cache_dir = _cache_dir(repo_root, analyzer_name, platform, tool_install)
    cached = _read_marker(cache_dir)
    if cached:
        return cached.resolve()

    install_url = _resolve_install_url(tool_install, platform)
    if install_url and archive_type.lower() == "zip":
        return _download_and_cache(analyzer_name, tool_install, install_url, cache_dir, platform)
    if install_url and archive_type.lower() == "npm_build":
        return _download_build_and_cache(analyzer_name, tool_install, install_url, cache_dir)

    raise RuntimeError(
        _unresolved_message(analyzer_name, tool_install, explicit_path, platform)
    )


def _require_supported_platform(
    analyzer_name: str, tool_install: dict[str, Any], platform: str
) -> None:
    """Raise ``UnsupportedPlatformError`` when ``requires_platform`` doesn't match."""
    requires_platform = tool_install.get("requires_platform")
    if requires_platform and platform != requires_platform:
        env_var = tool_install.get("env_var", "")
        raise UnsupportedPlatformError(
            f"Analyzer '{analyzer_name}' is not supported on {platform}. "
            f"Supported platform: {requires_platform}. "
            f"Set {env_var}=<path> to use a manually provided executable."
        )


def _download_and_cache(
    analyzer_name: str,
    tool_install: dict[str, Any],
    install_url: str,
    cache_dir: Path,
    platform: str,
) -> Path:
    """Download ``install_url``, verify, extract, cache, and return the executable."""
    install_url_env_var = tool_install.get("install_url_env_var", "")
    source_name = install_url_env_var if _env(install_url_env_var, "") else "analyzers.json"
    print(f"::notice::{analyzer_name}: executable not found; downloading from {source_name}")
    expected_sha256 = _platform_specific(tool_install, "install_sha256", platform)
    executable_subpath = _platform_specific(tool_install, "executable_subpath", platform)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / _clean_url_filename(install_url)
        _download(install_url, zip_path)
        if expected_sha256:
            _verify_checksum(zip_path, expected_sha256, analyzer_name)
        extract_dir = cache_dir / "extracted"
        _extract_zip(zip_path, extract_dir)
        executable = _find_executable(extract_dir, executable_subpath or "")
        if executable is None:
            raise RuntimeError(
                f"Could not locate executable for {analyzer_name} inside "
                f"{extract_dir} (expected subpath: {executable_subpath!r})."
            )
        executable = executable.resolve()
        _write_marker(cache_dir, executable)
        print(f"::notice::{analyzer_name}: resolved executable at {executable}")
        return executable


def _find_build_root(extract_dir: Path) -> Path:
    """Return the directory holding ``package.json`` inside an extracted archive.

    GitHub's tag-archive zip nests everything under a single
    ``<repo>-<ref>/`` folder whose exact name isn't known in advance.
    """
    package_json = next(extract_dir.rglob("package.json"), None)
    if package_json is None:
        raise RuntimeError(f"No package.json found inside {extract_dir}")
    return package_json.parent


def _run_build_step(
    analyzer_name: str, step_name: str, command: list[str], cwd: Path, timeout: int
) -> None:
    """Run one build step, raising a ``RuntimeError`` naming the step on failure."""
    try:
        subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=True
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"{analyzer_name}: '{step_name}' failed -- {command[0]} not found on PATH. "
            "Install Node.js (https://nodejs.org, >= 18) and npm, "
            "or set the tool's env var to a manually built executable."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{analyzer_name}: '{step_name}' timed out after {timeout}s."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(
            f"{analyzer_name}: '{step_name}' failed (exit {exc.returncode}). {detail}"
        ) from exc


def _run_npm_build(analyzer_name: str, build_root: Path, tool_install: dict[str, Any]) -> None:
    """Run ``npm install`` (plus any declared extra dependency) and ``npm run build``.

    Each step is named in its own failure message, per the requirement that a
    build failure says which step broke rather than surfacing a bare
    traceback -- npm absence included, since ``subprocess.run`` raises
    ``FileNotFoundError`` for a missing executable the same way it would for
    a missing tool binary elsewhere in this module.
    """
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            f"{analyzer_name}: npm not found on PATH. Install Node.js "
            "(https://nodejs.org, >= 18) and npm, or set the tool's env var "
            "to a manually built executable."
        )
    _run_build_step(
        analyzer_name, "npm install", [npm, "install"], build_root, _NPM_INSTALL_TIMEOUT_SECONDS
    )
    extra_dependencies = tool_install.get("build_extra_dependencies") or []
    if extra_dependencies:
        _run_build_step(
            analyzer_name,
            f"npm install {' '.join(extra_dependencies)}",
            [npm, "install", *extra_dependencies],
            build_root,
            _NPM_INSTALL_TIMEOUT_SECONDS,
        )
    _run_build_step(
        analyzer_name, "npm run build", [npm, "run", "build"], build_root, _NPM_BUILD_TIMEOUT_SECONDS
    )


def _raise_entrypoint_not_found(analyzer_name: str, extract_dir: Path, build_entrypoint: str) -> None:
    raise RuntimeError(
        f"Could not locate built entry point for {analyzer_name} inside "
        f"{extract_dir} (expected: {build_entrypoint!r})."
    )


def _download_build_and_cache(
    analyzer_name: str,
    tool_install: dict[str, Any],
    install_url: str,
    cache_dir: Path,
) -> Path:
    """Download a source archive, build it with npm, cache, and return the entry point.

    Mirrors ``_download_and_cache``'s download/verify/extract steps, then adds
    a build step in place of directly locating a shipped binary. Never leaves
    a partially built cache for a later run to trust: the extracted directory
    is removed on any failure, and the marker (the only thing a later run
    consults) is written only after a working entry point is located.
    """
    install_url_env_var = tool_install.get("install_url_env_var", "")
    source_name = install_url_env_var if _env(install_url_env_var, "") else "analyzers.json"
    print(f"::notice::{analyzer_name}: executable not found; building from source ({source_name})")
    expected_sha256 = tool_install.get("install_sha256")
    build_entrypoint = tool_install.get("build_entrypoint", "")
    extract_dir = cache_dir / "extracted"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / _clean_url_filename(install_url)
            _download(install_url, archive_path)
            if expected_sha256:
                _verify_checksum(archive_path, expected_sha256, analyzer_name)
            _extract_zip(archive_path, extract_dir)
            build_root = _find_build_root(extract_dir)
            _run_npm_build(analyzer_name, build_root, tool_install)
            entrypoint = _find_executable(extract_dir, build_entrypoint)
            if entrypoint is None:
                _raise_entrypoint_not_found(analyzer_name, extract_dir, build_entrypoint)
    except Exception:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise
    entrypoint = entrypoint.resolve()
    _write_marker(cache_dir, entrypoint)
    print(f"::notice::{analyzer_name}: built entry point at {entrypoint}")
    return entrypoint


def _unresolved_message(
    analyzer_name: str, tool_install: dict[str, Any], explicit_path: str | None, platform: str
) -> str:
    """Build the ``RuntimeError`` message when no resolution source worked."""
    env_var = tool_install.get("env_var", "")
    install_url_env_var = tool_install.get("install_url_env_var", "")
    committed_install_url = _platform_specific(tool_install, "install_url", platform)
    executable_subpath = _platform_specific(tool_install, "executable_subpath", platform)

    lines = [f"Could not resolve executable for analyzer '{analyzer_name}'."]
    if explicit_path:
        lines.append(f"  CLI path: {explicit_path}")
    if env_var:
        lines.append(f"  Set {env_var}=<path>")
    if install_url_env_var:
        lines.append(
            f"  Or set {install_url_env_var}=<zip-url> to download automatically."
        )
    if committed_install_url:
        lines.append(
            f"  Or set tool_install.install_url in analyzers.json to a zip URL "
            f"(current value: {committed_install_url})."
        )
    lines.append(
        "  Executable subpath inside zip: "
        f"{executable_subpath or '(any executable)'!r}"
    )
    return "\n".join(lines)


def print_resolution_help(analyzer_name: str, metadata_path: Path) -> None:
    """Print a non-failing help message showing how to resolve the tool."""
    config = load_analyzer_config(metadata_path, analyzer_name) or {}
    tool_install = config.get("tool_install") or {}
    env_var = tool_install.get("env_var", "")
    install_url_env_var = tool_install.get("install_url_env_var", "")
    committed_install_url = tool_install.get("install_url", "")
    print(f"fab-test {analyzer_name}: tool resolution options:")
    if env_var:
        print(f"  export {env_var}=<path-to-executable>")
    if install_url_env_var:
        print(f"  export {install_url_env_var}=<zip-url>")
    if committed_install_url:
        print(f"  analyzers.json tool_install.install_url: {committed_install_url}")


if __name__ == "__main__":
    # Simple CLI for diagnostics: python _analyzer_tool_bootstrap.py <analyzer>
    if len(sys.argv) < 2:
        print("Usage: python _analyzer_tool_bootstrap.py <analyzer_name>", file=sys.stderr)
        sys.exit(1)
    repo = Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve()
    try:
        exe = resolve_executable(
            sys.argv[1],
            repo / ".github" / "metadata" / "analyzers.json",
            repo,
        )
        print(exe)
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)
