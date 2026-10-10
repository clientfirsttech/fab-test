#!/usr/bin/env python3
"""Round-trip RDL rule fixtures through a Fabric workspace before committing them.

    python tools/generate_rdl_fixtures.py LAY-07 LAY-07-Pass
    python tools/deploy_rdl_fixtures.py --workspace "fab-test [Dev]" LAY-07 LAY-07-Pass

For each name, uploads ``fabric-artifacts/<name>.PaginatedReport/<name>.rdl``
as a PaginatedReport (creating the item, or updating it if one of that name
exists), reads it back with ``getDefinition``, and writes the returned
``.platform`` beside it. The service validating the upload is what makes a
generated fixture real: it rejects, for example, a parameter missing from the
layout grid or two groups with the same name. A fixture the service rejects,
or returns changed, fails the run and is left as it was. ``<RULE-ID>-Pass``
near-misses are deleted from the workspace afterwards, so a workspace's own
Playwright runs don't grow; the tripping fixtures stay deployed.

Credentials come from the same ``.fab-test/.env`` search order the CLI uses;
the token is never printed. Deliberately outside ``src/``: maintainer tooling
for committed fixtures, never invoked by fab-test itself (deployment is a
fab-test non-goal) and never packaged into the wheel.
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fab_test.scripts.playwright_validation.fabric_service_client import (  # noqa: E402
    build_fabric_service_client,
)

ARTIFACTS = REPO / "fabric-artifacts"
FABRIC_API = "https://api.fabric.microsoft.com/v1"

Call = Callable[..., Any]


class DeployError(Exception):
    """The service refused a request; the message names the fixture and the reply."""


def http_call(token: str) -> Call:
    """A ``call(method, path, body=None)`` against the Fabric REST API that waits
    out long-running operations and returns the JSON reply (None when empty)."""
    headers = {"Authorization": f"Bearer {token}"}

    def call(method: str, path: str, body: dict | None = None) -> Any:
        response = requests.request(method, FABRIC_API + path, headers=headers, json=body, timeout=60)
        while response.status_code == 202 and "Location" in response.headers:
            time.sleep(int(response.headers.get("Retry-After", 2)))
            operation = requests.get(response.headers["Location"], headers=headers, timeout=60)
            status = operation.json().get("status") if operation.content else None
            if status == "Succeeded":
                response = requests.get(response.headers["Location"] + "/result", headers=headers, timeout=60)
            elif status in ("Failed", "Cancelled"):
                raise DeployError(f"{method} {path}: operation {status.lower()}: {operation.text[:300]}")
        if response.status_code >= 400:
            raise DeployError(f"{method} {path}: HTTP {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else None

    return call


def _definition(name: str, rdl: bytes) -> dict:
    payload = base64.b64encode(rdl).decode()
    return {"parts": [{"path": f"{name}.rdl", "payload": payload, "payloadType": "InlineBase64"}]}


def _item_ids(workspace_id: str, call: Call) -> dict[str, str]:
    reply = call("GET", f"/workspaces/{workspace_id}/items?type=PaginatedReport")
    return {item["displayName"]: item["id"] for item in reply["value"]}


def _round_trip_one(name: str, folder: Path, workspace_id: str, call: Call) -> str:
    """Upload, read back, keep the .platform; return what happened, or raise DeployError."""
    rdl = (folder / f"{name}.rdl").read_bytes()
    items = f"/workspaces/{workspace_id}/items"
    item_id = _item_ids(workspace_id, call).get(name)
    if item_id:
        call("POST", f"{items}/{item_id}/updateDefinition", {"definition": _definition(name, rdl)})
    else:
        call("POST", items, {"displayName": name, "type": "PaginatedReport", "definition": _definition(name, rdl)})
        item_id = _item_ids(workspace_id, call)[name]
    parts = {
        part["path"]: base64.b64decode(part["payload"])
        for part in call("POST", f"{items}/{item_id}/getDefinition")["definition"]["parts"]
    }
    if parts.get(f"{name}.rdl") != rdl:
        raise DeployError(f"{name}: the service returned a different .rdl; regenerate from what it accepts")
    (folder / ".platform").write_bytes(parts[".platform"])
    if name.endswith("-Pass"):
        call("DELETE", f"{items}/{item_id}")
        return "accepted, saved, removed from the workspace"
    return "accepted, saved"


def round_trip(names: list[str], artifact_dir: Path, workspace_id: str, call: Call) -> int:
    """Round-trip each fixture; 0 when every one was accepted unchanged, else 1."""
    failed = False
    for name in names:
        try:
            outcome = _round_trip_one(name, artifact_dir / f"{name}.PaginatedReport", workspace_id, call)
        except DeployError as exc:
            failed = True
            outcome = f"FAILED: {exc}"
        print(f"{name}: {outcome}")
    return 1 if failed else 0


def _workspace_id(client: Any, name_or_id: str) -> str:
    for workspace in client.list_workspaces():
        if name_or_id in (workspace["id"], workspace["displayName"]):
            return workspace["id"]
    raise DeployError(f"workspace '{name_or_id}' not found, or the service principal can't see it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="+", help="fixtures to round-trip, e.g. LAY-07 LAY-07-Pass")
    parser.add_argument("--workspace", required=True, help="workspace name or GUID")
    parser.add_argument("--artifact-dir", type=Path, default=ARTIFACTS)
    parser.add_argument("--env-file", help="credentials file (default: the CLI's .fab-test/.env search)")
    args = parser.parse_args(argv)
    missing = [n for n in args.names if not (args.artifact_dir / f"{n}.PaginatedReport" / f"{n}.rdl").exists()]
    if missing:
        print(f"no such fixture: {', '.join(missing)} -- run python tools/generate_rdl_fixtures.py first")
        return 2
    client = build_fabric_service_client(env_file=args.env_file)
    try:
        workspace_id = _workspace_id(client, args.workspace)
    except DeployError as exc:
        print(exc)
        return 2
    return round_trip(args.names, args.artifact_dir, workspace_id, http_call(client.access_token))


if __name__ == "__main__":
    sys.exit(main())
