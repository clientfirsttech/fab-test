"""Power BI REST API helpers for Playwright visual validation.

Authentication uses MSAL for Python with a service principal. Embed tokens and
embed URLs are fetched from the Power BI REST API so the runner never hard-codes
tenant-specific endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .config import PlaywrightValidationConfig, _api_root_for

# Power BI API authority mapping for supported Azure clouds.
_CLOUD_AUTHORITY = {
    "public": "https://login.microsoftonline.com",
    "germany": "https://login.microsoftonline.de",
    "china": "https://login.chinacloudapi.cn",
    "usgov": "https://login.microsoftonline.us",
    "usgovhigh": "https://login.microsoftonline.us",
    "usgovdod": "https://login.microsoftonline.us",
}

_POWER_BI_RESOURCE = "https://analysis.windows.net/powerbi/api"


def _authority_for(cloud: str) -> str:
    """Return the MSAL authority base URL for the named cloud."""
    return _CLOUD_AUTHORITY.get(cloud.lower(), _CLOUD_AUTHORITY["public"])


@dataclass(frozen=True)
class EmbedContext:
    """Embed context returned for a single report."""

    embed_url: str
    embed_token: str
    report_id: str
    dataset_id: str


@dataclass(frozen=True)
class ReportIdentity:
    """Which workspace, report, and dataset an embed token is scoped to.

    Grouped because every caller of ``generate_embed_token`` passes most of
    these together. ``dataset_workspace_id`` is optional and defaults to
    empty, meaning "same workspace as the report" -- the common case, and
    the only shape this ever supported until a report and its dataset
    living in different workspaces (a common practice for a dataset shared
    across several reports) surfaced the gap: ``GenerateToken`` needs every
    workspace involved named in ``targetWorkspaces``, or it cannot resolve
    the dataset and reports a misleading "XMLA permissions are off" instead
    of a workspace-resolution failure (confirmed live).
    """

    workspace_id: str
    report_id: str
    dataset_id: str
    dataset_workspace_id: str = ""


class PowerBiApiError(Exception):
    """Raised when a Power BI REST API call fails."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _acquire_access_token(config: PlaywrightValidationConfig) -> str:
    """Acquire a service-principal access token for the Power BI API."""
    try:
        import msal
    except ImportError as exc:
        raise PowerBiApiError(
            "msal package is required for Power BI authentication. "
            "Install it with: pip install msal"
        ) from exc

    authority = f"{_authority_for(config.cloud)}/{config.tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=config.client_id,
        client_credential=config.client_secret,
        authority=authority,
    )

    result = app.acquire_token_for_client(scopes=[f"{_POWER_BI_RESOURCE}/.default"])

    if "access_token" not in result:
        error = (
            result.get("error_description")
            or result.get("error")
            or "unknown MSAL error"
        )
        raise PowerBiApiError(f"Failed to acquire access token: {error}")

    return str(result["access_token"])


def _api_headers(access_token: str) -> dict[str, str]:
    """Return standard Power BI REST API headers."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def get_report_embed_url(
    access_token: str,
    workspace_id: str,
    report_id: str,
    *,
    cloud: str = "public",
    timeout_seconds: int = 30,
) -> str:
    """Fetch the canonical embedUrl for a report from the Power BI REST API."""
    api_root = _api_root_for(cloud)
    url = f"{api_root}/v1.0/myorg/groups/{workspace_id}/reports/{report_id}"
    response = requests.get(
        url,
        headers=_api_headers(access_token),
        timeout=timeout_seconds,
    )

    if response.status_code != 200:
        raise PowerBiApiError(
            f"Failed to fetch report embed URL (HTTP {response.status_code})",
            status_code=response.status_code,
            body=response.text,
        )

    data = response.json()
    embed_url = data.get("embedUrl")
    if not embed_url:
        raise PowerBiApiError(
            "Power BI report response did not contain an embedUrl",
            body=response.text,
        )
    return str(embed_url)


def generate_embed_token(
    access_token: str,
    identity: ReportIdentity,
    *,
    use_rls: bool = False,
    user_name: str = "",
    role: str = "",
    cloud: str = "public",
    timeout_seconds: int = 30,
    report_type: str = "report",
) -> str:
    """Generate an embed token for a report via the Power BI REST API.

    The two report types send different payload shapes to ``GenerateToken``.
    An interactive report's has always included ``targetWorkspaces`` and
    ``accessLevel`` (verified live in the Playwright Embed Token Type epic),
    extended here to name the dataset's own workspace too when it differs
    from the report's -- a dataset shared across reports commonly lives
    elsewhere. A paginated report's payload is deliberately minimal --
    ``reports``/``datasets`` only, matching a validated reference
    implementation -- but its dataset entry needs one field an interactive
    report's never does: ``xmlaPermissions: "ReadOnly"``. Without it,
    ``GenerateToken`` succeeds but the token itself cannot connect to the
    dataset, and embedding fails with "XMLA permissions are off" regardless
    of ``targetWorkspaces``, ``accessLevel``, capacity tier, or which
    workspace anything lives in -- all tried and all irrelevant; only this
    field, confirmed live and matching Microsoft's own "Embed paginated
    reports" documentation, cleared it.
    """
    api_root = _api_root_for(cloud)
    url = f"{api_root}/v1.0/myorg/GenerateToken"

    payload: dict[str, Any] = {"reports": [{"id": identity.report_id}]}
    # A paginated report may have no bound semantic model the report-metadata
    # lookup can find -- omit the key rather than sending a dataset entry
    # with no id, which the GenerateToken API rejects.
    if identity.dataset_id:
        dataset_entry: dict[str, str] = {"id": identity.dataset_id}
        if report_type == "paginated":
            dataset_entry["xmlaPermissions"] = "ReadOnly"
        payload["datasets"] = [dataset_entry]

    if report_type != "paginated":
        target_workspace_ids = [identity.workspace_id]
        if (
            identity.dataset_workspace_id
            and identity.dataset_workspace_id != identity.workspace_id
        ):
            target_workspace_ids.append(identity.dataset_workspace_id)
        payload["targetWorkspaces"] = [{"id": wid} for wid in target_workspace_ids]
        payload["accessLevel"] = "View"

    if use_rls and user_name and role:
        # Tried dropping the `role` requirement here (attach an identity
        # with "roles": [] whenever a dataset's role couldn't be discovered)
        # to handle a mandatory-identity, no-named-role dataset -- reverted
        # after a live run proved it a net regression: Power BI rejected
        # every *non*-RLS dataset with "shouldn't have effective identity"
        # (6 reports that previously passed), while the RLS-secured
        # datasets this was meant to fix still failed, now with "requires
        # roles to be included in provided effective identity" instead --
        # they have real named roles that discovery isn't finding, so an
        # empty roles list was never going to satisfy them either. Fixing
        # this needs the role discovery itself, not a looser guard here --
        # see "Discover RLS roles for non-PBIP-enabled semantic models" in
        # tasks/playwright-ci-guide-epic.md.
        payload["identities"] = [
            {
                "username": user_name,
                "roles": [role],
                "datasets": [identity.dataset_id],
            }
        ]

    response = requests.post(
        url,
        headers=_api_headers(access_token),
        json=payload,
        timeout=timeout_seconds,
    )

    if response.status_code != 200:
        raise PowerBiApiError(
            f"Failed to generate embed token "
            f"(HTTP {response.status_code}): {response.text}",
            status_code=response.status_code,
            body=response.text,
        )

    data = response.json()
    token = data.get("token")
    if not token:
        raise PowerBiApiError(
            "GenerateToken response did not contain a token",
            body=response.text,
        )
    return str(token)


def get_embed_context(config: PlaywrightValidationConfig) -> EmbedContext:
    """Acquire an access token and embed context for the configured report."""
    access_token = _acquire_access_token(config)
    embed_url = get_report_embed_url(
        access_token,
        config.workspace_id,
        config.report_id,
        cloud=config.cloud,
        timeout_seconds=config.timeout_seconds,
    )
    embed_token = generate_embed_token(
        access_token,
        ReportIdentity(
            config.workspace_id,
            config.report_id,
            config.dataset_id,
            dataset_workspace_id=config.dataset_workspace_id,
        ),
        use_rls=config.use_rls,
        user_name=config.user_name,
        role=config.role,
        cloud=config.cloud,
        timeout_seconds=config.timeout_seconds,
        report_type=config.report_type,
    )
    return EmbedContext(
        embed_url=embed_url,
        embed_token=embed_token,
        report_id=config.report_id,
        dataset_id=config.dataset_id,
    )
