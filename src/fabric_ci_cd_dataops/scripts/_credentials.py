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


def _lookup(names: tuple[str, ...] | str, file_values: dict[str, str]) -> tuple[str, str | None]:
    """Return ``(value, origin)`` for the first of ``names`` that is set.

    Origin is ``"environment"`` or ``".env"``, or None when nothing
    supplies it. Environment variables win, matching the real chain.
    """
    candidates = (names,) if isinstance(names, str) else names
    for name in candidates:
        if os.environ.get(name, ""):
            return os.environ[name], "environment"
    for name in candidates:
        if file_values.get(name, ""):
            return file_values[name], ".env"
    return "", None


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


def probe_credentials(env_file: Path | str | None = None) -> CredentialStatus:
    """Resolve the credential chain without acquiring a token.

    ``env_file`` defaults to ``PLAYWRIGHT_ENV_FILE`` or ``.env`` in the
    current directory, matching how the Playwright config discovers it. A
    path that does not exist is not an error: it simply contributes
    nothing, the same as an absent file.
    """
    if env_file is None:
        env_file = Path(os.getenv("PLAYWRIGHT_ENV_FILE", ".env"))
    env_path = Path(env_file)
    file_values = _parse_env_file(env_path) if env_path.exists() else {}

    tenant, tenant_origin = _lookup(_TENANT_VAR, file_values)
    client_id, client_origin = _lookup(_CLIENT_ID_VARS, file_values)
    client_secret, secret_origin = _lookup(_CLIENT_SECRET_VARS, file_values)

    if tenant and client_id and client_secret:
        origins = {tenant_origin, client_origin, secret_origin}
        source = "environment" if origins == {"environment"} else ".env"
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
