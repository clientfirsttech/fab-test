"""npm steps for the tool bootstrap's two Node acquisition methods.

``npm_build`` (pbir-a11y) builds a source archive; ``npm_package`` (promptfoo)
installs a published package. Both run npm as a subprocess and name the step
that failed. Split out of ``_analyzer_tool_bootstrap.py`` to keep that module
under its line budget.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

_NPM_INSTALL_TIMEOUT_SECONDS = 300
_NPM_BUILD_TIMEOUT_SECONDS = 120


def _node_requirement(tool_install: dict[str, Any]) -> str:
    """Name the Node.js version the tool declares, for remediation messages."""
    min_major = (tool_install.get("requires_runtime") or {}).get("min_major", 18)
    return f"Node.js (https://nodejs.org, >= {min_major})"


def _require_npm(analyzer_name: str, tool_install: dict[str, Any]) -> str:
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            f"{analyzer_name}: npm not found on PATH. Install {_node_requirement(tool_install)} "
            "and npm, or set the tool's env var to a manually built executable."
        )
    return npm


def run_build_step(
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


def find_build_root(extract_dir: Path) -> Path:
    """Return the directory holding ``package.json`` inside an extracted archive.

    GitHub's tag-archive zip nests everything under a single
    ``<repo>-<ref>/`` folder whose exact name isn't known in advance.
    """
    package_json = next(extract_dir.rglob("package.json"), None)
    if package_json is None:
        raise RuntimeError(f"No package.json found inside {extract_dir}")
    return package_json.parent


def run_npm_build(analyzer_name: str, build_root: Path, tool_install: dict[str, Any]) -> None:
    """Run ``npm install`` (plus any declared extra dependency) and ``npm run build``.

    Each step is named in its own failure message, per the requirement that a
    build failure says which step broke rather than surfacing a bare
    traceback -- npm absence included, since ``subprocess.run`` raises
    ``FileNotFoundError`` for a missing executable the same way it would for
    a missing tool binary elsewhere in the bootstrap.
    """
    npm = _require_npm(analyzer_name, tool_install)
    run_build_step(
        analyzer_name, "npm install", [npm, "install"], build_root, _NPM_INSTALL_TIMEOUT_SECONDS
    )
    extra_dependencies = tool_install.get("build_extra_dependencies") or []
    if extra_dependencies:
        run_build_step(
            analyzer_name,
            f"npm install {' '.join(extra_dependencies)}",
            [npm, "install", *extra_dependencies],
            build_root,
            _NPM_INSTALL_TIMEOUT_SECONDS,
        )
    run_build_step(
        analyzer_name, "npm run build", [npm, "run", "build"], build_root, _NPM_BUILD_TIMEOUT_SECONDS
    )


def _package_entrypoint(install_dir: Path, package: str) -> Path:
    """Return the file the installed package declares as its ``bin`` command."""
    package_dir = install_dir / "node_modules" / package
    manifest = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
    bin_field = manifest.get("bin")
    relative = bin_field.get(package) if isinstance(bin_field, dict) else bin_field
    entrypoint = package_dir / relative if relative else None
    if entrypoint is None or not entrypoint.is_file():
        raise RuntimeError(f"{package} declares no usable bin entry point in {package_dir}")
    return entrypoint


def install_npm_package(
    analyzer_name: str, tool_install: dict[str, Any], spec: str, install_dir: Path
) -> Path:
    """``npm install`` ``spec`` into ``install_dir`` and return its bin entry point.

    ``spec`` is ``<package>@<version>`` or, via the install-URL override, a
    tarball path or URL. Nothing is left behind on failure, so a later run
    never trusts a half-finished install.
    """
    npm = _require_npm(analyzer_name, tool_install)
    install_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_build_step(
            analyzer_name,
            f"npm install {spec}",
            [npm, "install", "--prefix", str(install_dir), "--no-save", "--no-audit", "--no-fund", spec],
            install_dir,
            _NPM_INSTALL_TIMEOUT_SECONDS,
        )
        return _package_entrypoint(install_dir, tool_install["package"]).resolve()
    except Exception:
        shutil.rmtree(install_dir, ignore_errors=True)
        raise
