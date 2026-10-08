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
import errno
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any

from ._cli_utils import narrate
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
}

# A report is exported in its stored format: Fabric will not convert a
# PBIR-Legacy report to PBIR, so asking for PBIR fails the whole operation.
_DEFINITION_FORMATS = {"SemanticModel": "TMDL"}
_LEGACY_REASON = "stored as PBIR-Legacy, which the analyzers cannot read; convert to PBIR to test"
ENUMERATION_LIMIT = 50
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_UNSAFE = re.compile(r"[^\w.\- ]")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|pwd|accountkey|sharedaccesskey|client_?secret)\s*=\s*[^;\"'\r\n]+"
)
_JSON_SECRET = re.compile(r'(?i)("(?:password|pwd|accountkey|sharedaccesskey|client_?secret)"\s*:\s*")[^"]*')
_CI_VARIABLES = ("CI", "GITHUB_ACTIONS", "TF_BUILD")
_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
_WINDOWS_PATH_TOO_LONG = 206  # ERROR_FILENAME_EXCED_RANGE


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
    if getattr(args, "mode", "repo") != "service" or name not in SERVICE_ITEM_TYPES:
        return False
    return (
        name != "pql_test"
        or getattr(args, "analyzer", None) == "all"
        or bool(getattr(args, "service_workspace", ""))
    )


def service_target_refusal(name: str, args: argparse.Namespace) -> str | None:
    """Refuse a path TARGET combined with a service-mode export."""
    target = getattr(args, "resolved_target", None)
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
    status = probe_credentials(getattr(args, "playwright_env_file", None))
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

    env_file = getattr(args, "playwright_env_file", None)
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
        text = f"cannot export {label}: Fabric getDefinition failed ({_fabric_error(exc) or status or exc})"
    return ServiceExportError(text, 1)


def _fabric_error(exc: Exception) -> str:
    """Fabric's own ``errorCode: message`` from an error body, or ``""``.

    A failed long-running operation arrives as HTTP 200 with the error
    nested under ``error``; a direct failure carries it at the top level.
    """
    try:
        data = json.loads(getattr(exc, "body", "") or "")
    except ValueError:
        return ""
    error = data.get("error", data) if isinstance(data, dict) else None
    if not isinstance(error, dict) or not error.get("errorCode"):
        return ""
    return f"{error['errorCode']}: {error.get('message', '')}".rstrip(": ")


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
    from .playwright_validation.resolver import ResolvedEnvironment, list_inventory, resolve_item

    item_type = SERVICE_ITEM_TYPES[name]
    target = getattr(args, "resolved_target", None)
    if target is not None:
        item = resolve_item(target.name, item_type, ResolvedEnvironment("service", workspace_id), client)
        return [{"id": item.item_id, "displayName": item.display_name}]
    items = list_inventory(client, workspace_id, item_type)
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
    if name == "pql_test":
        return [Path(f"{mode.workspace or ''}.Workspace") / f"{target.name}.{suffix}"]
    return [Path(f"{_safe(mode.workspace or '')}") / f"{_safe(target.name)}.{suffix}"]


def _progress(args: argparse.Namespace, message: str, end: str = "\n") -> None:
    """Narrate export progress on stderr; silent under -q and --format json, like the banner."""
    if getattr(args, "quiet", False) or getattr(args, "output_format", "text") == "json":
        return
    print(message, end=end, file=sys.stderr, flush=True)


def _fetch_definition(
    rest: Any, args: argparse.Namespace, workspace_id: str, item: dict[str, Any], item_type: str
) -> list[dict[str, str]]:
    """Return one item's definition parts, announcing the export as it runs."""
    from .playwright_validation.service_client import ServiceClientError

    label = f"{item['displayName']}.{item_type}"
    _progress(args, f"exporting {label}...", end="")
    started = time.monotonic()
    try:
        parts = rest.get_item_definition(
            workspace_id, item["id"], definition_format=_DEFINITION_FORMATS.get(item_type, "")
        )
    except ServiceClientError as exc:
        _progress(args, " failed")
        raise _remediation(exc, label) from exc
    _progress(args, f" done ({time.monotonic() - started:.1f}s)")
    return parts


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
    from .playwright_validation.service_client import FabricRestClient, FabricToken

    client = build_service_client(args)
    item_type = SERVICE_ITEM_TYPES[name]
    workspace_id, items = _list_items(name, args, client, mode)
    args.workspace_id = workspace_id
    if name == "pql_test":
        return _deployed_models(args, client, workspace_id, mode, items)
    if getattr(args, "dry_run", False):
        return [Path(_safe(mode.workspace or "")) / f"{_safe(i['displayName'])}.{item_type}" for i in items]

    _announce_credential(args, client)
    rest = FabricRestClient(FabricToken(client.access_token))
    # None marks a PBIR-Legacy report: exported once, never analyzed.
    cache: dict[tuple[str, str], Path | None] = args.__dict__.setdefault("_export_cache", {})
    artifacts: list[Path] = []
    skipped: list[str] = args.__dict__.setdefault("_export_skipped", {}).setdefault(name, [])
    for item in items:
        key = (workspace_id, item["id"])
        if key not in cache:
            cache[key] = _export_item(rest, item, name, args, output_dir, workspace_id)
        if cache[key] is None:
            skipped.append(f"{item['displayName']}.{item_type}")
        else:
            artifacts.append(cache[key])
    if skipped and not artifacts:
        raise ServiceExportError(f"nothing to test: {', '.join(skipped)} -- {_LEGACY_REASON}", 1)
    output_format = getattr(args, "output_format", "text")
    for label in skipped:
        narrate(f"  ⏭ {label} skipped -- {_LEGACY_REASON}", output_format=output_format)
    return sorted(artifacts)


def _list_items(
    name: str, args: argparse.Namespace, client: Any, mode: ResolvedMode
) -> tuple[str, list[dict[str, Any]]]:
    """Resolve the workspace and the items ``name`` reads, each failure a `ServiceExportError`."""
    from .playwright_validation.fabric_service_client import FabricServiceClientError
    from .playwright_validation.resolver import ServiceResolutionError
    from .playwright_validation.service_client import ServiceClientError

    try:
        workspace_id = _workspace_id(args, client, mode)
        return workspace_id, _select_items(name, args, client, workspace_id)
    except ServiceExportError:
        raise
    except ServiceResolutionError as exc:
        raise ServiceExportError(str(exc), 1) from exc
    except (ServiceClientError, FabricServiceClientError) as exc:
        label = f"the {SERVICE_ITEM_TYPES[name]} list of workspace '{mode.workspace}'"
        raise _remediation(exc, label) from exc


def _deployed_models(
    args: argparse.Namespace, client: Any, workspace_id: str, mode: ResolvedMode, items: list[dict[str, Any]]
) -> list[Path]:
    """Name each deployed model the way pql-test addresses it, exporting nothing.

    pql-test connects to the model over XMLA and discovers its tests there
    (``PQL.Assert.RetrieveTestsV2``), so the definition files would be a
    download nobody reads. ``WORKSPACE.Workspace/NAME.SemanticModel`` takes
    display names, so a workspace given by GUID is looked up once.
    """
    from ._pql_identity import pql_identity_mismatch
    from .playwright_validation.service_client import FabricRestClient, FabricToken

    workspace = mode.workspace or ""
    if not getattr(args, "dry_run", False):
        _announce_credential(args, client)
        mismatch = pql_identity_mismatch(client.access_token)
        if mismatch:
            raise ServiceExportError(mismatch, 2)
        if not workspace or _GUID.match(workspace):
            workspace = FabricRestClient(FabricToken(client.access_token)).get_workspace_name(workspace_id)
    return sorted(Path(f"{workspace}.Workspace") / f"{item['displayName']}.SemanticModel" for item in items)


def _export_item(
    rest: Any, item: dict[str, Any], name: str, args: argparse.Namespace, output_dir: Path, workspace_id: str
) -> Path | None:
    """Export one item and return its artifact path, or None for a PBIR-Legacy report."""
    item_type = SERVICE_ITEM_TYPES[name]
    parts = _fetch_definition(rest, args, workspace_id, item, item_type)
    if any(part["path"] == "report.json" for part in parts):
        return None
    root = output_dir / name / _safe(args.resolved_mode.workspace or workspace_id) / _safe(item["displayName"])
    if output_dir.resolve() not in root.resolve().parents:
        raise ServiceExportError(f"refusing export path outside {output_dir}", 1)
    args.__dict__.setdefault("_export_roots", []).append(root)
    try:
        return _write_parts(parts, root / "export", item_type, item["displayName"])
    except OSError as exc:
        raise _write_failure(exc, f"{item['displayName']}.{item_type}") from exc


def _write_failure(exc: OSError, label: str) -> ServiceExportError:
    """Name an export that could not be written, never a traceback.

    PBIR's nested ``definition/pages/<id>/visuals/<id>/visual.json`` is what
    crosses Windows' 260-character limit (WinError 206) under a deep output dir.
    """
    text = f"cannot write the export of {label} to {exc.filename}: {exc.strerror}"
    if exc.errno == errno.ENAMETOOLONG or getattr(exc, "winerror", None) == _WINDOWS_PATH_TOO_LONG:
        text += "; the path is too long -- pass a shorter --output-dir or enable Windows long-path support"
    return ServiceExportError(text, 1)


def service_skip_exit(name: str, args: argparse.Namespace) -> int:
    """1 when this run skipped a report ``name`` should have tested, else 0.

    A skipped report was never tested, so the run cannot claim every
    artifact passed.
    """
    return 1 if getattr(args, "_export_skipped", {}).get(name) else 0


def _announce_credential(args: argparse.Namespace, client: Any) -> None:
    """Name the credential the run resolved, once, beside the mode banner.

    The label and the env-file path only -- never a secret. Silent under
    ``--format json`` and ``-q``, like the banner.
    """
    if getattr(args, "_auth_announced", False):
        return
    args._auth_announced = True
    source = getattr(client, "credential_source", "unknown")
    if source == "service-principal":
        source += f" ({probe_credentials(getattr(args, 'playwright_env_file', None)).source})"
    _progress(args, f"auth={source}")


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
