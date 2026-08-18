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
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_READER_CHUNK_SIZE = 8192
_USER_AGENT = "fabric-ci-cd-dataops-fab-test/1.0"


class UnsupportedPlatformError(RuntimeError):
    """Raised when an analyzer's tool is not available on the current OS."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _is_ci() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def _cache_root(repo_root: Path) -> Path:
    return repo_root / ".fab-test-tools"


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


def _write_marker(cache_dir: Path, executable: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _marker_path(cache_dir).write_text(str(executable), encoding="utf-8")


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    """Download ``url`` to ``dest`` with a simple progress indicator in CI."""
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(request, timeout=timeout) as response, open(dest, "wb") as fh:
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
    env_var = tool_install.get("env_var", "")
    default_path = tool_install.get("default_path", "")
    install_url_env_var = tool_install.get("install_url_env_var", "")
    archive_type = tool_install.get("archive_type", "zip")

    platform = _current_platform()
    requires_platform = tool_install.get("requires_platform")
    if requires_platform and platform != requires_platform:
        raise UnsupportedPlatformError(
            f"Analyzer '{analyzer_name}' is not supported on {platform}. "
            f"Supported platform: {requires_platform}. "
            f"Set {env_var}=<path> to use a manually provided executable."
        )

    committed_install_url = _platform_specific(
        tool_install, "install_url", platform
    )
    executable_subpath = _platform_specific(
        tool_install, "executable_subpath", platform
    )

    def _usable(path: Path) -> bool:
        return path.exists() and path.is_file()

    candidates: list[tuple[str, Path]] = []

    if explicit_path:
        candidates.append(("CLI argument", Path(explicit_path)))
    if env_var and _env(env_var).strip():
        candidates.append((f"env var {env_var}", Path(_env(env_var).strip())))
    if default_path and default_path.strip():
        candidates.append(("default path", repo_root / default_path.strip()))

    for source, path in candidates:
        if _usable(path):
            return path.resolve()

    cache_dir = _cache_root(repo_root) / analyzer_name / platform
    cached = _read_marker(cache_dir)
    if cached:
        return cached.resolve()

    install_url = _env(install_url_env_var, "") if install_url_env_var else ""
    if not install_url:
        install_url = committed_install_url or ""
    if install_url and archive_type.lower() == "zip":
        source_name = install_url_env_var if _env(install_url_env_var, "") else "analyzers.json"
        print(
            f"::notice::{analyzer_name}: executable not found; downloading from "
            f"{source_name}"
        )
        expected_sha256 = _platform_specific(tool_install, "install_sha256", platform)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_name = _clean_url_filename(install_url)
            zip_path = tmp_path / zip_name
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

    # Build a helpful error message.
    lines = [
        f"Could not resolve executable for analyzer '{analyzer_name}'."
    ]
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
    raise RuntimeError("\n".join(lines))


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
