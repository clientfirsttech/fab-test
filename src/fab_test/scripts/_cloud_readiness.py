"""Readiness for analyzers that need a workspace or Desktop (Doctor Severity epic).

Split from `fab_test_registry.py`, which is over its size budget. The
answer is one of four statuses, chosen by intent as well as consequence:
❌ ``error`` only when something was set up (a workspace, part of a service
principal) and the run would fail; ⚠ ``warning`` when one more setting
would make it work; ℹ ``info`` when the service was never set up, which is
not a broken install. Stays as cheap as the rest of the probe: no
subprocess, no network call, and no secret value in any field.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from . import _pql_identity
from ._credentials import SIGN_IN_REMEDIATION, configured_workspace, probe_credentials

# Playwright always calls MSAL with a service-principal secret to generate an
# embed token, so an ambient credential (az login, managed identity) cannot
# stand in for it the way it does for pql_test.
_PLAYWRIGHT_CREDENTIALS = (
    "set FABRIC_TENANT_ID, FABRIC_SERVICE_PRINCIPAL_ID, and FABRIC_SERVICE_PRINCIPAL_SECRET "
    "(or put them in .fab-test/.env); playwright cannot use `az login`"
)


def _row(status: str, reason: str, remediation: str | None) -> dict[str, Any]:
    ready = {"ready": True, "info": None}.get(status, False)
    return {
        "ready": ready,
        "status": status,
        "resolved_path": None,
        "reason": reason,
        "remediation": remediation,
    }


def _workspace_hint(name: str) -> str:
    hint = "Set FABRIC_WORKSPACE_ID or `workspace:` in fab-test.yml, or pass --workspace"
    if name != "pql_test":
        return f"{hint}, or set PLAYWRIGHT_WORKSPACE_ID in .fab-test/.env"
    return f"{hint}; or open the .pbip in Power BI Desktop to run locally"


def cloud_readiness(
    name: str,
    args: argparse.Namespace | None,
    *,
    desktop_capable: bool,
    desktop_ports: Callable[[], list[int]],
) -> dict[str, Any]:
    """Return readiness for a cloud analyzer, naming only what is missing."""
    needs_principal = name == "playwright"
    status = probe_credentials()
    if configured_workspace(args, playwright=name != "pql_test"):
        if name == "pql_test" and status.resolved and not status.verified:
            identity = _pql_identity_row()
            if identity:
                return identity
        return _with_workspace(status, needs_principal)

    if desktop_capable and desktop_ports():
        return _row("ready", "no workspace set; would bind to a running Power BI Desktop instance", None)
    if status.incomplete:
        return _row("error", f"no workspace set, and the {status.detail}", status.remediation)
    if status.verified:
        return _row(
            "warning",
            f"credentials from {status.source}; no workspace set",
            _workspace_hint(name),
        )
    credentials = _PLAYWRIGHT_CREDENTIALS if needs_principal else SIGN_IN_REMEDIATION
    return _row(
        "info",
        "service mode not configured",
        f"{_workspace_hint(name)}. Then: {credentials[0].lower()}{credentials[1:]}",
    )


def _pql_identity_row() -> dict[str, Any] | None:
    """pql-test connects with its own saved login, which must be the az login account (see `_pql_identity`)."""
    checked = _pql_identity.identity_check()
    if checked is None:
        return None
    account, mismatch = checked
    if mismatch:
        return _row("error", f"workspace configured; pql-test would not connect as {account}", mismatch)
    return _row("ready", f"workspace configured; az login and pql-test both signed in as {account}", None)


def _with_workspace(status: Any, needs_principal: bool) -> dict[str, Any]:
    if needs_principal and status.incomplete:
        return _row("error", f"workspace configured but the {status.detail}", status.remediation)
    if needs_principal and not status.verified:
        return _row("error", "workspace configured; playwright needs a service principal", _PLAYWRIGHT_CREDENTIALS)
    if status.resolved:
        reason = (
            f"workspace configured, credentials from {status.source}"
            if status.verified
            else f"workspace configured; {status.detail}"
        )
        return _row("ready", reason, None)
    return _row("error", f"workspace configured but {status.detail}", status.remediation)
