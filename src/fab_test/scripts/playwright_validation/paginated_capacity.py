"""Why a paginated report failed to render, when its workspace has no capacity.

Power BI renders a paginated report only on a capacity (Fabric, Premium or
Premium Per User). In a workspace without one, the embedded report opens
with "Query execution failed for dataset ...", which the render scan records
as an RDL error and which points at the report and its data rather than at
the workspace's licence. So when a paginated case fails that way, the
workspace is looked up once and, if it has no capacity, each such case says
so with the fix. Best-effort: a lookup that fails adds nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import PlaywrightValidationConfig

RDL_ERROR = "RDL error modal detected"
NO_CAPACITY = ("the workspace isn't on a capacity, and Power BI renders a paginated report only on one "
               "(Fabric, Premium or Premium Per User); assign one in the workspace's settings, under License info")


def _workspace_on_capacity(config: PlaywrightValidationConfig) -> bool | None:
    from .fabric_service_client import build_fabric_service_client
    from .service_client import FabricRestClient, FabricToken

    client = build_fabric_service_client(tenant_id=config.tenant_id, client_id=config.client_id,
                                         client_secret=config.client_secret, cloud=config.cloud)
    rest = FabricRestClient(FabricToken(access_token=client.access_token, cloud=config.cloud))
    return rest.workspace_on_capacity(config.workspace_id)


def capacity_hint(config: PlaywrightValidationConfig,
                  on_capacity: Callable[[PlaywrightValidationConfig], bool | None] = _workspace_on_capacity) -> str:
    """`NO_CAPACITY` when the report's workspace is known to have no capacity, else ""."""
    try:
        return NO_CAPACITY if on_capacity(config) is False else ""
    except Exception:  # noqa: BLE001 - an explanation is a convenience; it must never fail the run
        return ""


def explain_paginated_failures(rows: list[dict[str, Any]], config: PlaywrightValidationConfig,
                               hint: Callable[[PlaywrightValidationConfig], str] | None = None) -> list[dict[str, Any]]:
    """``rows`` with the capacity hint added to each RDL-error case, when the workspace has no capacity."""
    failed = [row for row in rows if row.get("status") != "pass" and str(row.get("actual", "")).startswith(RDL_ERROR)]
    if config.report_type != "paginated" or not failed:
        return rows
    text = (hint or capacity_hint)(config)
    if not text:
        return rows
    return [{**row, "actual": f"{row['actual']}: {text}"} if row in failed else row for row in rows]
