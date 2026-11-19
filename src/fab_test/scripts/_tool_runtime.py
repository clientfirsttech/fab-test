"""Runtime checks for analyzer tools: is the language runtime a tool needs installed?

A resolved, executable, correctly-versioned binary is still unrunnable without
its runtime -- ``dotnet`` for PBIR Inspector's framework-dependent build,
``node`` for pbir-a11y. ``tool_install.requires_runtime`` in analyzers.json
declares it; these checks run a cheap, local, read-only subprocess
(``dotnet --list-runtimes`` / ``node --version``). Split out of
``_analyzer_tool_bootstrap`` at its 800-line budget.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any

_DOTNET_RUNTIME_PATTERN = re.compile(r"Microsoft\.NETCore\.App (\d+)\.")
_NODE_VERSION_PATTERN = re.compile(r"v?(\d+)\.")


def _installed_dotnet_majors() -> list[int]:
    """Return the major versions of every .NET *runtime* (not SDK) installed,
    via ``dotnet --list-runtimes``. Empty when dotnet is absent or unreadable.
    """
    exe = shutil.which("dotnet")
    if exe is None:
        return []
    try:
        proc = subprocess.run(
            [exe, "--list-runtimes"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted({int(m) for m in _DOTNET_RUNTIME_PATTERN.findall(proc.stdout or "")})


def _installed_node_major() -> int | None:
    """Return Node's major version via ``node --version``, or None if absent."""
    exe = shutil.which("node")
    if exe is None:
        return None
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _NODE_VERSION_PATTERN.search((proc.stdout or "").strip())
    return int(match.group(1)) if match else None


def _for_version(version: str | None) -> str:
    return f" to use {version}" if version else ""


def _dotnet_runtime_gap(min_major: int, version: str | None = None) -> dict[str, Any] | None:
    majors = _installed_dotnet_majors()
    if any(m >= min_major for m in majors):
        return None
    installed = ", ".join(f"{m}.x" for m in majors) if majors else "none found"
    return {
        "ready": False,
        "resolved_path": None,
        "version": None,
        "reason": f".NET {min_major}+ runtime not found (installed: {installed})",
        "remediation": f"Install the .NET {min_major} runtime{_for_version(version)}: "
        f"https://dotnet.microsoft.com/download/dotnet/{min_major}.0",
    }


def _node_runtime_gap(min_major: int, version: str | None = None) -> dict[str, Any] | None:
    major = _installed_node_major()
    if major is not None and major >= min_major:
        return None
    installed = str(major) if major is not None else "not found"
    return {
        "ready": False,
        "resolved_path": None,
        "version": None,
        "reason": f"Node.js {min_major}+ not found (installed: {installed})",
        "remediation": f"Install Node.js >= {min_major}{_for_version(version)} (https://nodejs.org).",
    }


_RUNTIME_GAP_CHECKS = {"dotnet": _dotnet_runtime_gap, "node": _node_runtime_gap}


def runtime_gap(tool_install: dict[str, Any], *, name_version: bool = False) -> dict[str, Any] | None:
    """Return a not-ready dict when ``tool_install``'s declared ``requires_runtime``
    is missing or older than its ``min_major``, else None.

    A resolved, executable, correctly-versioned binary is still unrunnable
    without its language runtime -- ``dotnet`` for the PBIR Inspector's
    framework-dependent build, ``node`` for pbir-a11y once already built.
    This is checked ahead of local-candidate/cache resolution so it applies
    whether the tool is on disk, cached, or would still need downloading.
    ``name_version`` says which version the runtime is for in the remediation.
    """
    requirement = tool_install.get("requires_runtime")
    if not requirement:
        return None
    check = _RUNTIME_GAP_CHECKS.get(requirement.get("name"))
    if check is None:
        return None
    return check(requirement.get("min_major"), tool_install.get("version") if name_version else None)


def select_tool_install(tool_install: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Return the ``tool_install`` to resolve and, when it's the runtime fallback, why.

    ``runtime_fallback`` declares an older pin (its ``version``, install URLs,
    sha256s and ``requires_runtime``) for a machine without the pin's runtime:
    fab-inspector 4.x needs .NET 10 and .NET never rolls back, so a .NET 8-only
    machine runs 3.4.0. Its keys are laid over the pin's only when the pin's
    runtime is missing and the fallback's is present; otherwise the pin is
    returned unchanged, so a machine with neither still hears about the pin's
    runtime. The note's ``reason`` and ``remediation`` say what ran and how to
    get the pin.
    """
    fallback = tool_install.get("runtime_fallback")
    if not fallback:
        return tool_install, None
    pin_gap = runtime_gap(tool_install, name_version=True)
    if pin_gap is None:
        return tool_install, None
    selected = {key: value for key, value in tool_install.items() if key != "runtime_fallback"} | fallback
    if runtime_gap(selected) is not None:
        return tool_install, None
    reason = f"using fallback version {selected.get('version')}; {pin_gap['reason']}"
    return selected, {"reason": reason, "remediation": pin_gap["remediation"]}
