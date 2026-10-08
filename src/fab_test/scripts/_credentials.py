"""Probe the Fabric credential chain (Artifact Targeting and Auth §7).

Answers "which identity would fab-test use, and where did it come from?"
without acquiring a token, so `doctor` can report honestly and cheaply and
`auth status` has one resolution path to describe rather than its own.

The precedence mirrors ``build_client_from_env`` in
``playwright_validation/fabric_service_client.py``, which is what actually
authenticates: environment variables, then a `.env` file, then an ambient
Azure credential. Ambient is attempted only when *no* service-principal
variable is set at all -- a partially-configured principal is a mistake to
surface, not something to silently override.

One honest limit. Whether an ambient credential actually works cannot be
known without acquiring a token, which means a network call or an ``az``
subprocess; `check_readiness` is contractually forbidden from both, and
`doctor` is supposed to run offline. So an available ambient credential
resolves as *unverified*: reported as usable, labelled as unproven, and
paired with the command that checks for real. The alternative readings
were both worse -- calling it not-ready reports red for every developer
signed in with `az login`, and calling it verified would reintroduce
exactly the false green §6 removed.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TENANT_VAR = "FABRIC_TENANT_ID"
# Either spelling of the client pair is accepted, matching
# playwright_validation/config.py. The first is the canonical one to suggest.
_CLIENT_ID_VARS = ("FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_CLIENT_ID")
_CLIENT_SECRET_VARS = ("FABRIC_SERVICE_PRINCIPAL_SECRET", "FABRIC_CLIENT_SECRET")

AMBIENT_SOURCE = "ambient:DefaultAzureCredential"

# Listed in the order the chain tries them, so a caller reading the
# remediation top to bottom learns the precedence for free.
_ACCEPTED_SOURCES = (
    f"set {_TENANT_VAR}, {_CLIENT_ID_VARS[0]}, and {_CLIENT_SECRET_VARS[0]}",
    "or put them in a .env file at the repository root (or PLAYWRIGHT_ENV_FILE)",
    "or sign in to Azure with `az login` (also covers managed identity and VS Code)",
)

# What to do when nothing is configured and the ambient sign-in fails. One
# sentence shared by the run-time error and `auth status`, so the two never
# give different advice. `az login` comes first: on a developer machine it is
# the likely fix, and a CI runner already knows it uses a service principal.
SIGN_IN_REMEDIATION = (
    f"Run `az login`, or set {_TENANT_VAR}, {_CLIENT_ID_VARS[0]} and "
    f"{_CLIENT_SECRET_VARS[0]} (or put them in .fab-test/.env)"
)


@dataclass(frozen=True)
class CredentialStatus:
    """What the credential chain would resolve to, and how sure we are.

    ``verified`` is False only for the ambient source; see the module
    docstring for why that state exists rather than being collapsed into
    ready or not-ready.
    """

    source: str | None
    tenant_id: str | None
    verified: bool
    detail: str
    remediation: str | None

    @property
    def resolved(self) -> bool:
        """Whether any source in the chain would supply a credential."""
        return self.source is not None


def ambient_credential_available() -> bool:
    """Whether an ambient Azure credential could be attempted at all.

    A spec lookup rather than an import: ``azure.identity`` pulls in a
    large dependency tree and `doctor` should not pay for it. Resolving
    the spec does import the ``azure`` namespace package itself, which is
    empty and effectively free; ``azure.identity`` is never imported. This
    says the *machinery* is installed, not that a credential will resolve
    -- that is the unverified part.
    """
    return importlib.util.find_spec("azure.identity") is not None


def redact_secrets(text: str) -> str:
    """Replace any live credential value found in ``text`` with a marker.

    Value-based, unlike `_sanitize_command`'s flag-name matching: a secret
    interpolated into prose has no flag in front of it. The values come
    from the environment, so this catches exactly the strings that would
    be damaging to print. Very short values are skipped -- redacting a
    two-character secret would blank unrelated text and make the output
    less trustworthy, not more.

    Only the client secret is redacted. A tenant or client ID names a
    directory and an application; `auth status` reports the tenant on
    purpose, and blanking it would remove the answer the caller came for.
    """
    for var in _CLIENT_SECRET_VARS:
        value = os.environ.get(var, "")
        if len(value) >= 8:
            text = text.replace(value, "<redacted>")
    return text


def _parse_env_file(env_file: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from ``env_file`` without mutating ``os.environ``."""
    from .playwright_validation.config import _parse_env_file as _parse

    return _parse(env_file)


def _resolve_env_path(env_file: Path | str | None) -> Path:
    """Return the ``.env`` file this probe would read.

    Delegates to `playwright_validation.config.resolve_env_file`, the one
    place the search order -- ``--env-file`` > ``PLAYWRIGHT_ENV_FILE`` >
    ``.fab-test/.env`` > ``./.env`` -- is defined, so this module and the
    Playwright config loader cannot disagree about which file supplied a
    credential.
    """
    from .playwright_validation.config import resolve_env_file

    return resolve_env_file(env_file)


def _env_file_label(env_path: Path) -> str:
    """Return the short label `auth status` and `probe_credentials` report.

    Distinguishes fab-test's own ``.fab-test/.env`` from a repository-root
    ``.env`` so a caller can see which one actually supplied a credential.
    """
    return ".fab-test/.env" if env_path.parent.name == ".fab-test" else ".env"


def _lookup(
    names: tuple[str, ...] | str, file_values: dict[str, str], file_label: str = ".env"
) -> tuple[str, str | None]:
    """Return ``(value, origin)`` for the first of ``names`` that is set.

    Origin is ``"environment"`` or ``file_label``, or None when nothing
    supplies it. Environment variables win, matching the real chain.
    """
    candidates = (names,) if isinstance(names, str) else names
    for name in candidates:
        if os.environ.get(name, ""):
            return os.environ[name], "environment"
    for name in candidates:
        if file_values.get(name, ""):
            return file_values[name], file_label
    return "", None


def configured_workspace(args: Any, *, playwright: bool) -> str:
    """Return the workspace a cloud analyzer's run would target, without a network call.

    Mirrors the run's own sources so `doctor` never reports ❌ for a run that
    succeeds: ``--workspace-id``, ``FABRIC_WORKSPACE_ID``, ``workspace:`` in
    fab-test.yml, and -- for the Playwright family only, whose config loader
    reads it -- ``PLAYWRIGHT_WORKSPACE_ID`` from the environment or `.env` file.
    """
    workspace = (
        getattr(args, "workspace_id", "")
        or os.getenv("FABRIC_WORKSPACE_ID", "")
        or (getattr(args, "file_config", None) or {}).get("workspace", "")
    )
    if workspace or not playwright:
        return workspace
    env_path = _resolve_env_path(getattr(args, "playwright_env_file", None))
    file_values = _parse_env_file(env_path) if env_path.exists() else {}
    return _lookup("PLAYWRIGHT_WORKSPACE_ID", file_values)[0]


def _missing_variable_remediation(
    tenant: str, client_id: str, client_secret: str
) -> str:
    """Name only the service-principal variables that are actually absent."""
    missing = []
    if not tenant:
        missing.append(_TENANT_VAR)
    if not client_id:
        missing.append(_CLIENT_ID_VARS[0])
    if not client_secret:
        missing.append(_CLIENT_SECRET_VARS[0])
    return (
        f"Service principal is partially configured; also set {', '.join(missing)}"
    )


class IncompleteServicePrincipalError(Exception):
    """Some service-principal variables are set and others are not.

    Its own type because the caller must not treat it as "no principal": a
    half-set principal is a mistake to report, not a cue to fall back to
    ambient auth and answer a different question than the one asked.
    """


@dataclass(frozen=True)
class ServicePrincipal:
    """A complete service principal, and where its values came from."""

    tenant_id: str
    client_id: str
    client_secret: str
    source: str


def resolve_service_principal(env_file: Path | str | None = None) -> ServicePrincipal | None:
    """Return the configured service principal, or None to use ambient auth.

    The same variables, aliases, and precedence `probe_credentials` reports
    on -- environment first, then a `.env` file read without mutating
    ``os.environ``. Returning None means nothing was set at all, which is
    the documented cue for `DefaultAzureCredential`.

    Raises `IncompleteServicePrincipalError` when *some* variables are set:
    the rule `build_fabric_service_client` already applies, for the same
    reason.
    """
    env_path = _resolve_env_path(env_file)
    file_label = _env_file_label(env_path)
    file_values = _parse_env_file(env_path) if env_path.exists() else {}

    tenant, tenant_origin = _lookup(_TENANT_VAR, file_values, file_label)
    client_id, client_origin = _lookup(_CLIENT_ID_VARS, file_values, file_label)
    client_secret, secret_origin = _lookup(_CLIENT_SECRET_VARS, file_values, file_label)

    if tenant and client_id and client_secret:
        origins = {tenant_origin, client_origin, secret_origin}
        return ServicePrincipal(
            tenant_id=tenant,
            client_id=client_id,
            client_secret=client_secret,
            source="environment" if origins == {"environment"} else file_label,
        )
    if tenant or client_id or client_secret:
        raise IncompleteServicePrincipalError(
            _missing_variable_remediation(tenant, client_id, client_secret)
        )
    return None


def build_azure_credential(env_file: Path | str | None = None) -> Any:
    """Return an Azure credential for a caller that already resolves via `resolve_service_principal`.

    The service principal the CLI already resolves, or `DefaultAzureCredential`
    when none is set -- the rule `build_fabric_service_client` documents,
    applied to whichever endpoint the caller is about to authenticate
    against. A partially configured principal raises rather than falling
    back. Shared by every telemetry sink so a second destination is not a
    second credential-resolution path to get out of sync with the first.
    """
    principal = resolve_service_principal(env_file)
    if principal is None:
        from azure.identity import DefaultAzureCredential

        return DefaultAzureCredential()

    from azure.identity import ClientSecretCredential

    return ClientSecretCredential(
        tenant_id=principal.tenant_id,
        client_id=principal.client_id,
        client_secret=principal.client_secret,
    )


def probe_credentials(env_file: Path | str | None = None) -> CredentialStatus:
    """Resolve the credential chain without acquiring a token.

    ``env_file`` defaults to ``PLAYWRIGHT_ENV_FILE`` or ``.env`` in the
    current directory, matching how the Playwright config discovers it. A
    path that does not exist is not an error: it simply contributes
    nothing, the same as an absent file.
    """
    env_path = _resolve_env_path(env_file)
    file_label = _env_file_label(env_path)
    file_values = _parse_env_file(env_path) if env_path.exists() else {}

    tenant, tenant_origin = _lookup(_TENANT_VAR, file_values, file_label)
    client_id, client_origin = _lookup(_CLIENT_ID_VARS, file_values, file_label)
    client_secret, secret_origin = _lookup(_CLIENT_SECRET_VARS, file_values, file_label)

    if tenant and client_id and client_secret:
        origins = {tenant_origin, client_origin, secret_origin}
        source = "environment" if origins == {"environment"} else file_label
        return CredentialStatus(
            source=source,
            tenant_id=tenant,
            verified=True,
            detail=f"service principal from {source}",
            remediation=None,
        )

    if tenant or client_id or client_secret:
        return CredentialStatus(
            source=None,
            tenant_id=tenant or None,
            verified=False,
            detail="service principal is incomplete",
            remediation=_missing_variable_remediation(tenant, client_id, client_secret),
        )

    if ambient_credential_available():
        return CredentialStatus(
            source=AMBIENT_SOURCE,
            tenant_id=None,
            verified=False,
            detail=(
                "no service principal set; would attempt DefaultAzureCredential "
                "(unverified -- run `fab-test auth status` to confirm the sign-in)"
            ),
            remediation=None,
        )

    return CredentialStatus(
        source=None,
        tenant_id=None,
        verified=False,
        detail="no credentials resolved",
        remediation="; ".join(_ACCEPTED_SOURCES),
    )
