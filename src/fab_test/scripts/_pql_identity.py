"""Refuse a service-mode pql-test run that would connect as a different account.

fab-test lists a workspace's models with its own credential, then pql-test
connects to each one over XMLA with *its* credential. A service principal
is shared (fab-test maps it onto ``PQL_TENANT_ID``/``PQL_CLIENT_ID``/
``PQL_CLIENT_SECRET``), but an ambient sign-in such as ``az login`` cannot be
handed over: pql-test falls back to whatever ``pql-test auth login`` saved.
When those are different people, the second account may not see the
workspace and pql-test reports "No tests found" for a model full of tests.
This check names both accounts and stops before that happens.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess

_PQL_CREDENTIAL_VARS = ("PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET")
# Claims that carry a signed-in person's name; an app-only token has none.
_ACCOUNT_CLAIMS = ("upn", "unique_name", "preferred_username")


def token_account(token: str) -> str:
    """Return the account a Fabric access token was issued to, or "" for an app or unreadable token.

    Reads the JWT payload without verifying it: the token is our own, just
    acquired, and only its name is compared -- never trusted for access.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return ""
    return next((str(claims[c]) for c in _ACCOUNT_CLAIMS if claims.get(c)), "")


def _pql_auth_status() -> dict[str, str] | None:
    """Parse ``pql-test auth status`` into its ``Status``/``Method``/``Account`` lines, or None if it cannot run."""
    from .invoke_pql_test import _resolve_pql_command

    try:
        proc = subprocess.run(
            _resolve_pql_command(["pql-test", "auth", "status"]),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    fields: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep and key in {"Status", "Method", "Account"}:
            fields[key] = value.strip()
    return fields or None


def pql_identity_mismatch(fabric_token: str) -> str | None:
    """Return why pql-test would not connect as fab-test's signed-in account, or None to proceed.

    Proceeds whenever the comparison cannot be made -- an app-only token,
    ``PQL_*`` credentials that pql-test will use instead of its saved login,
    or a pql-test that will not run (reported by the run itself) -- so the
    check only ever stops a run it can name a reason for.
    """
    account = token_account(fabric_token)
    if not account or any(os.getenv(v) for v in _PQL_CREDENTIAL_VARS):
        return None
    status = _pql_auth_status()
    if status is None:
        return None
    login = f"Run `pql-test auth login` and sign in as {account}"
    if status.get("Status") != "Authenticated":
        return f"pql-test is not signed in, so it cannot reach the models fab-test listed as {account}. {login}."
    method = status.get("Method", "")
    pql_account = status.get("Account", "")
    if method == "interactive" and pql_account and pql_account.lower() != account.lower():
        return f"fab-test is signed in as {account} but pql-test as {pql_account}. {login}."
    if method and method != "interactive":
        return f"fab-test is signed in as {account} but pql-test uses its saved {method} login. {login}."
    return None
