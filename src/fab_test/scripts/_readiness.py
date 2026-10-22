"""Tool resolution and readiness for ``fab-test``: whether each analyzer can
run here, and the preflight error to stop on when it can't.

Split out of ``fab_test_registry.py`` (Core Module Split), which keeps the
registry tables and the bootstrapped/cloud/desktop analyzer sets read here.
``doctor``, ``explain``, ``local`` and every run reach readiness through
``check_readiness`` and ``preflight_error``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ._analyzer_tool_bootstrap import (
    UnsupportedPlatformError,
    probe_executable,
    resolve_executable,
)
from ._cloud_readiness import cloud_readiness
from ._credentials import probe_credentials
from ._desktop import desktop_ports
from ._feature_flags import is_enabled
from .fab_test_registry import (
    _BOOTSTRAP_REGISTRY_NAME,
    _BOOTSTRAPPED_ANALYZERS,
    _CLOUD_ANALYZERS,
    _DESKTOP_CAPABLE_ANALYZERS,
    ANALYZERS_JSON,
    REPO_ROOT,
)
from .playwright_validation.execution_runtime import execution_readiness


def resolve_tool(name: str, args: argparse.Namespace) -> Path | None:
    """Resolve the external executable for ``name`` and store it on ``args``.

    Returns the resolved Path, or None for analyzers without a declared tool.
    Raises RuntimeError with a helpful message if the tool cannot be resolved.
    """
    if name not in _BOOTSTRAPPED_ANALYZERS or not is_enabled(name):
        return None

    explicit = None
    if name == "bpa":
        explicit = getattr(args, "tabular_editor_path", None)
    elif name == "pbir":
        explicit = getattr(args, "inspector_path", None)
    elif name == "a11y":
        explicit = getattr(args, "a11y_path", None)

    resolved = resolve_executable(
        _BOOTSTRAP_REGISTRY_NAME.get(name, name),
        ANALYZERS_JSON,
        REPO_ROOT,
        explicit_path=explicit,
    )
    args._resolved_tool_path = str(resolved)
    return resolved


_TOOL_FLAG_HINTS = {
    "bpa": "--tabular-editor-path",
    "pbir": "--inspector-path",
    "a11y": "--a11y-path",
}


def _playwright_preflight_error(args: argparse.Namespace) -> tuple[str, int] | None:
    """Return (message, 127) when the pytest runner or the service principal is missing."""
    # Its "tool" is the pytest runner; without it every case read as a failed render.
    from .playwright_validation import execution_runtime

    missing = execution_runtime.missing_runner_message()
    if missing:
        return missing, 127
    # Every artifact would refuse at the same check; say it once, before fanning out.
    status = probe_credentials(getattr(args, "playwright_env_file", None))
    if status.verified:
        return None
    # Only a partial principal's remediation helps; the ambient-credential detail
    # ("would attempt DefaultAzureCredential") is not an option playwright has.
    partial = f" ({status.remediation})" if status.remediation else ""
    message = (
        f"playwright needs a full service principal to generate an embed token{partial}.\n"
        "  Set FABRIC_TENANT_ID, FABRIC_CLIENT_ID (or FABRIC_SERVICE_PRINCIPAL_ID), and "
        "FABRIC_CLIENT_SECRET (or FABRIC_SERVICE_PRINCIPAL_SECRET) in the environment, "
        "a .env file, or pass --env-file."
    )
    return message, 127


def preflight_error(name: str, args: argparse.Namespace) -> tuple[str, int] | None:
    """Return an (error message, exit code) pair if a required tool is missing.

    Exit code 126 signals the tool exists but is unsupported on this platform
    ("command found but not executable" — the closest POSIX convention);
    exit code 127 ("command not found") covers any other resolution failure,
    distinguishing an unconfigured machine from a real rule violation (1).
    """
    if name == "playwright" and not getattr(args, "plan_only", False):
        return _playwright_preflight_error(args)
    if name not in _BOOTSTRAPPED_ANALYZERS or not is_enabled(name):
        return None
    try:
        resolve_tool(name, args)
    except UnsupportedPlatformError as exc:
        return str(exc), 126
    except RuntimeError as exc:
        message = str(exc)
        flag = _TOOL_FLAG_HINTS.get(name)
        if flag:
            message = f"{message}\n  Or pass {flag} <path> on the command line."
        return message, 127
    else:
        return None


def _cloud_readiness(name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    """Readiness for an analyzer that needs a workspace or Desktop (see `_cloud_readiness.py`)."""
    return cloud_readiness(
        name,
        args,
        desktop_capable=name in _DESKTOP_CAPABLE_ANALYZERS,
        desktop_ports=desktop_ports,
    )


def check_readiness(name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    """Return a readiness dict for analyzer ``name`` (the engine behind `doctor`).

    Never reads an artifact or spawns a subprocess. Three cases: an
    analyzer needing a workspace or Desktop instance (`_CLOUD_ANALYZERS`)
    is probed by ``_cloud_readiness``; one needing neither a binary nor a
    workspace (pql_lint) is always ready; the rest resolve an external
    tool -- see ``probe_executable`` for that shape.

    Every branch's dict gets ``version`` and ``status`` keys here rather
    than in each of them, so the doctor row shape stays uniform (only
    ``probe_executable``'s bootstrapped-tool path ever has a version, and
    only ``_cloud_readiness`` ever says ``warning``).
    """
    result = execution_readiness(_readiness_without_version(name, args), name, args)
    result.setdefault("version", None)
    if result.get("status") in (None, "ready"):
        # Derived for every branch that sets none, and re-derived when
        # execution_readiness turned a ready row not-ready after the fact.
        result["status"] = {True: "ready", None: "info"}.get(result["ready"], "error")
    return result


def _readiness_without_version(name: str, args: argparse.Namespace | None) -> dict[str, Any]:
    if name in _CLOUD_ANALYZERS:
        return _cloud_readiness(name, args)

    if name not in _BOOTSTRAPPED_ANALYZERS or not is_enabled(name):
        return {
            "ready": True,
            "resolved_path": None,
            "reason": "no external tool required",
            "remediation": None,
        }

    explicit = None
    if args is not None:
        if name == "bpa":
            explicit = getattr(args, "tabular_editor_path", None)
        elif name == "pbir":
            explicit = getattr(args, "inspector_path", None)
        elif name == "a11y":
            explicit = getattr(args, "a11y_path", None)

    return probe_executable(
        _BOOTSTRAP_REGISTRY_NAME.get(name, name),
        ANALYZERS_JSON,
        REPO_ROOT,
        explicit_path=explicit,
    )
