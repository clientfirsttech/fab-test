"""Export deployed items as the on-disk shape the analyzers already read.

Service Targeting epic: `bpa`, `pbir`, `a11y` and `rdl` (and `pql-test`
under `all --workspace`) never learn about the service. A deployed
semantic model, report or paginated report is materialized through Fabric
`getDefinition` into a folder or `.rdl` file, and the existing invoke path
runs on that -- a facade, not a fork.

Read-only and ephemeral: exports are deleted after the run unless
`--keep-export` is passed, in which case they are redacted in place.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

from ._credentials import (
    IncompleteServicePrincipalError,
    probe_credentials,
    redact_secrets,
    resolve_service_principal,
)
from ._mode import ResolvedMode

# Which Fabric item type each service-capable analyzer reads.
SERVICE_ITEM_TYPES: dict[str, str] = {
    "bpa": "SemanticModel",
    "pbir": "Report",
    "a11y": "Report",
    "rdl": "PaginatedReport",
    "pql_test": "SemanticModel",
    "data_agent": "DataAgent",
}
_EXPORTED_SERVICE_ANALYZERS = frozenset({"bpa", "pbir", "a11y", "rdl", "pql_test"})

_DEFINITION_FORMATS = {"SemanticModel": "TMDL", "Report": "PBIR"}
ENUMERATION_LIMIT = 50
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_UNSAFE = re.compile(r"[^\w.\- ]")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|pwd|accountkey|sharedaccesskey|client_?secret)\s*=\s*[^;\"'\r\n]+"
)
_JSON_SECRET = re.compile(r'(?i)("(?:password|pwd|accountkey|sharedaccesskey|client_?secret)"\s*:\s*")[^"]*')
_CI_VARIABLES = ("CI", "GITHUB_ACTIONS", "TF_BUILD")
_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"


class ServiceExportError(Exception):
    """A service export that cannot proceed; ``code`` is the CLI exit code."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(redact_secrets(message))
        self.code = code


def service_item_type(name: str) -> str | None:
    """Return the Fabric item type ``name`` reads in service mode, if any."""
    return SERVICE_ITEM_TYPES.get(name)


def is_service_run(name: str, args: argparse.Namespace) -> bool:
    """True when ``name`` should materialize deployed items for this run.

    `pql-test` does so under `all` or an explicit `--workspace`: otherwise
    its `--workspace-id` keeps meaning "run the repository's models over
    XMLA", and a typed workspace target keeps its XMLA path, as before.
    """
    if getattr(args, "mode", "repo") != "service" or name not in _EXPORTED_SERVICE_ANALYZERS:
        return False
    return (
        name != "pql_test"
        or getattr(args, "analyzer", None) == "all"
        or bool(getattr(args, "service_workspace", ""))
    )


def service_target_refusal(name: str, args: argparse.Namespace) -> str | None:
    """Refuse a path TARGET combined with a service-mode export."""
    target = getattr(args, "resolved_target", None)
    if (
        name == "data_agent"
        and getattr(args, "mode", "repo") == "service"
        and target is not None
        and target.path is not None
    ):
        return (
            f"'{target.raw.strip()}' is a path but --workspace asks for the service; "
            "name the Data Agent (Sales Agent or WORKSPACE.Workspace/Sales Agent.DataAgent) "
            "or drop --workspace"
        )
    if is_service_run(name, args) and target is not None and target.path is not None:
        return (
            f"'{target.raw.strip()}' is a path but --workspace asks for the service; "
            "name the item (Sales.SemanticModel or WORKSPACE.Workspace/Sales.SemanticModel) "
            "or drop --workspace"
        )
    return None


def interactive_refusal(args: argparse.Namespace) -> str | None:
    """Return why ``--interactive`` is not allowed here, or None when it is."""
    if not getattr(args, "interactive", False):
        return None
    if any(os.environ.get(var) for var in _CI_VARIABLES):
        return "--interactive never prompts in CI; use a service principal or `az login`"
    if os.environ.get("FAB_TEST_INTERACTIVE_AUTH", "") == "0":
        return "--interactive is disabled by FAB_TEST_INTERACTIVE_AUTH=0"
    configured = (getattr(args, "file_config", None) or {}).get("interactive_auth", "on")
    if configured is False or str(configured).strip().lower() in ("off", "false", "0"):
        return "--interactive is disabled by interactive_auth: off in fab-test.yml"
    return None


def service_readiness(args: argparse.Namespace) -> str:
    """One `doctor` line on service-mode readiness; never acquires a token."""
    env_file = getattr(args, "data_agent_env_file", None) or getattr(args, "playwright_env_file", None)
    status = probe_credentials(env_file)
    detail = redact_secrets(status.detail or "")
    if status.verified:
        return f"service mode: {detail} (unverified until a run; see `fab-test auth status`)"
    fix = redact_secrets(status.remediation or "")
    interactive = "" if interactive_refusal(_probe_args(args)) else "; or pass --interactive"
    return f"service mode: {detail}. {fix}{interactive}".strip()


def _probe_args(args: argparse.Namespace) -> argparse.Namespace:
    probe = argparse.Namespace(**vars(args))
    probe.interactive = True
    return probe


def _interactive_client() -> Any:
    from azure.identity import InteractiveBrowserCredential

    from .playwright_validation.fabric_service_client import FabricServiceClient

    # No cache_persistence_options: the token lives in memory only.
    token = InteractiveBrowserCredential().get_token(_FABRIC_SCOPE).token
    return FabricServiceClient.from_access_token(token, credential_source="interactive")


def build_service_client(args: argparse.Namespace) -> Any:
    """Return one Fabric client for the run, built through the one credential chain.

    A partially configured service principal is a mistake to report, never
    a cue to fall back to a browser sign-in.
    """
    cached = getattr(args, "_service_client", None)
    if cached is not None:
        return cached
    from .playwright_validation.fabric_service_client import (
        FabricServiceClientError,
        build_fabric_service_client,
    )
    from .playwright_validation.resolver import ServiceResolutionError

    env_file = getattr(args, "data_agent_env_file", None) or getattr(args, "playwright_env_file", None)
    try:
        client = build_fabric_service_client(env_file=env_file)
    except (ServiceResolutionError, FabricServiceClientError) as exc:
        if not getattr(args, "interactive", False):
            raise ServiceExportError(
                f"{exc} Run `fab-test auth status` to see which credential is resolved.", 127
            ) from exc
        try:
            resolve_service_principal(env_file)
        except IncompleteServicePrincipalError as incomplete:
            raise ServiceExportError(
                f"{incomplete}. Run `fab-test auth status`.", 127
            ) from incomplete
        client = _interactive_client()
    args._service_client = client
    return client


def _remediation(exc: Exception, label: str) -> ServiceExportError:
    """Turn a Fabric API failure into a named remediation, never a raw HTTP error."""
    status = getattr(exc, "status_code", None)
    if status == 404:
        text = (
            f"cannot export {label}: getDefinition returned 404 -- the item is not in "
            "enhanced/Git-integration format, or it no longer exists"
        )
    elif status in (401, 403):
        text = (
            f"cannot export {label}: this identity may not read its definition "
            f"(HTTP {status}); it needs read access plus Fabric API access. "
            "Run `fab-test auth status`"
        )
    else:
        text = f"cannot export {label}: Fabric getDefinition failed ({status or exc})"
    return ServiceExportError(text, 1)


def _safe(name: str) -> str:
    """A single path segment: no separators, and never ``.``/``..``."""
    return _UNSAFE.sub("_", name).strip().lstrip(".") or "item"


def _write_parts(parts: list[dict[str, str]], dest: Path, item_type: str, name: str) -> Path:
    """Write definition parts under ``dest`` and return the artifact path."""
    if item_type == "PaginatedReport":
        rdl = next((p for p in parts if p["path"].lower().endswith(".rdl")), None)
        if rdl is None:
            raise ServiceExportError(f"'{name}' has no .rdl definition part to analyze", 1)
        dest.mkdir(parents=True, exist_ok=True)
        artifact = dest / f"{_safe(name)}.rdl"
        artifact.write_bytes(base64.b64decode(rdl["payload"]))
        return artifact
    artifact = dest / f"{_safe(name)}.{item_type}"
    artifact.mkdir(parents=True, exist_ok=True)
    root = artifact.resolve()
    for part in parts:
        relative = PurePosixPath(part["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ServiceExportError(f"refusing unsafe definition path '{part['path']}'", 1)
        target = artifact.joinpath(*relative.parts)
        if root not in target.resolve().parents:
            raise ServiceExportError(f"refusing unsafe definition path '{part['path']}'", 1)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(part["payload"]))
    return artifact


def _select_items(
    name: str, args: argparse.Namespace, client: Any, workspace_id: str
) -> list[dict[str, Any]]:
    from .playwright_validation.resolver import ResolvedEnvironment, resolve_item

    item_type = SERVICE_ITEM_TYPES[name]
    target = getattr(args, "resolved_target", None)
    if target is not None:
        item = resolve_item(target.name, item_type, ResolvedEnvironment("service", workspace_id), client)
        return [{"id": item.item_id, "displayName": item.display_name}]
    items = client.list_items(workspace_id, item_type)
    if len(items) > ENUMERATION_LIMIT and not getattr(args, "all_items", False):
        raise ServiceExportError(
            f"{name}: {len(items)} {item_type} items in the workspace exceed the "
            f"{ENUMERATION_LIMIT}-item limit; pass --all to proceed",
            2,
        )
    return items


def _workspace_id(args: argparse.Namespace, client: Any, mode: ResolvedMode) -> str:
    from .playwright_validation.resolver import resolve_workspace_id

    current = getattr(args, "workspace_id", "") or ""
    if _GUID.match(current):
        return current
    return resolve_workspace_id(client, mode.workspace or current)


def _dry_run_paths(name: str, args: argparse.Namespace, mode: ResolvedMode) -> list[Path] | None:
    """A typed target can be listed without a token or an API call."""
    target = getattr(args, "resolved_target", None)
    if target is None:
        return None
    suffix = "rdl" if SERVICE_ITEM_TYPES[name] == "PaginatedReport" else SERVICE_ITEM_TYPES[name]
    return [Path(f"{_safe(mode.workspace or '')}") / f"{_safe(target.name)}.{suffix}"]


def export_for_analyzer(name: str, args: argparse.Namespace, output_dir: Path) -> list[Path]:
    """Return the exported artifact paths ``name`` should analyze.

    Raises `ServiceExportError` carrying the exit code. Each deployed item
    is exported once per run, however many analyzers read it.
    """
    mode: ResolvedMode = args.resolved_mode
    if getattr(args, "dry_run", False):
        planned = _dry_run_paths(name, args, mode)
        if planned is not None:
            return planned
    from .playwright_validation.fabric_service_client import FabricServiceClientError
    from .playwright_validation.resolver import ServiceResolutionError
    from .playwright_validation.service_client import FabricRestClient, FabricToken, ServiceClientError

    client = build_service_client(args)
    item_type = SERVICE_ITEM_TYPES[name]
    try:
        workspace_id = _workspace_id(args, client, mode)
        items = _select_items(name, args, client, workspace_id)
    except ServiceExportError:
        raise
    except ServiceResolutionError as exc:
        raise ServiceExportError(str(exc), 1) from exc
    except (ServiceClientError, FabricServiceClientError) as exc:
        raise _remediation(exc, f"the {item_type} list of workspace '{mode.workspace}'") from exc

    args.workspace_id = workspace_id
    if getattr(args, "dry_run", False):
        return [Path(_safe(mode.workspace or "")) / f"{_safe(i['displayName'])}.{item_type}" for i in items]

    rest = FabricRestClient(FabricToken(client.access_token))
    cache: dict[tuple[str, str], Path] = args.__dict__.setdefault("_export_cache", {})
    roots: list[Path] = args.__dict__.setdefault("_export_roots", [])
    artifacts: list[Path] = []
    for item in items:
        key = (workspace_id, item["id"])
        if key not in cache:
            label = f"{item['displayName']}.{item_type}"
            try:
                parts = rest.get_item_definition(
                    workspace_id, item["id"], definition_format=_DEFINITION_FORMATS.get(item_type, "")
                )
            except ServiceClientError as exc:
                raise _remediation(exc, label) from exc
            root = output_dir / name / _safe(mode.workspace or workspace_id) / _safe(item["displayName"])
            if output_dir.resolve() not in root.resolve().parents:
                raise ServiceExportError(f"refusing export path outside {output_dir}", 1)
            roots.append(root)
            cache[key] = _write_parts(parts, root / "export", item_type, item["displayName"])
        artifacts.append(cache[key])
    return sorted(artifacts)


def _redact_text(text: str) -> str:
    text = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}=<redacted>", redact_secrets(text))
    return _JSON_SECRET.sub(lambda m: f"{m.group(1)}<redacted>", text)


def finalize_exports(args: argparse.Namespace) -> None:
    """Delete this run's exports, or redact them in place under `--keep-export`."""
    roots: list[Path] = getattr(args, "_export_roots", [])
    for root in roots:
        if not getattr(args, "keep_export", False):
            shutil.rmtree(root, ignore_errors=True)
            for parent in (root.parent, root.parent.parent):
                with contextlib.suppress(OSError):
                    parent.rmdir()
            continue
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                original = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                continue  # binary content carries no connection-string text
            except OSError:
                path.unlink(missing_ok=True)  # fail closed: never keep what cannot be audited
                continue
            redacted = _redact_text(original)
            if redacted != original:
                path.write_bytes(redacted.encode("utf-8"))
    roots.clear()
