"""Service-only Data Agent discovery and command construction."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from azure.core.exceptions import AzureError

from ._credentials import IncompleteServicePrincipalError
from ._data_agent_resolution import data_agent_base_url, list_data_agents, resolve_data_agent_url
from ._data_agent_suite import SuiteError, item_identity, load_suite, pair_suite, suite_index
from ._mode import ModeError, ResolvedMode
from ._results_stem import register_stems, results_stem
from ._scan import find_artifact_dirs
from ._service_export import ServiceExportError, build_service_client
from ._tests_dir import search_roots
from .fab_test_registry import discover_artifacts
from .invoke_data_agent import credential_secret
from .playwright_validation.fabric_service_client import FabricServiceClientError
from .playwright_validation.resolver import ServiceResolutionError, resolve_workspace_id

ENUMERATION_LIMIT = 5


def resolve_data_agent_mode(args: argparse.Namespace) -> ResolvedMode:
    """A Data Agent always runs in service mode; local folders only supply its suites."""
    target = getattr(args, "resolved_target", None)
    flag = getattr(args, "workspace_id", "") or ""
    inherited_mode = getattr(args, "resolved_mode", None)
    if (getattr(args, "analyzer", None) == "all" and inherited_mode and inherited_mode.source != "flag"
            and not getattr(args, "workspace_flag_given", False)):
        flag = ""  # all may have resolved a config workspace to a GUID; that did not make it an explicit flag
    if target is not None and target.scope == "desktop":
        raise ModeError("data-agent cannot run local/NAME; it tests deployed agents. Pass --workspace NAME_OR_ID.")
    if target is not None and target.workspace:
        return ResolvedMode("service", target.workspace, "target")
    sources = [
        (flag, "flag"), (os.getenv("FABRIC_WORKSPACE_ID", ""), "env"),
        ((getattr(args, "file_config", None) or {}).get("workspace", ""), "config"),
    ]
    for workspace, source in sources:
        if workspace:
            return ResolvedMode("service", workspace, source)
    raise ModeError("data-agent needs --workspace NAME_OR_ID, FABRIC_WORKSPACE_ID, or workspace: in fab-test.yml.")


def _has_urls(suite: Path) -> bool:
    providers = load_suite(suite).get("providers") or []
    if isinstance(providers, dict):
        providers = [providers]
    return bool(providers) and all(
        isinstance(p, dict) and isinstance(p.get("config"), dict)
        and bool(p["config"].get("base_url") or p["config"].get("fabric_urls"))
        for p in providers
    )


def _client(args: argparse.Namespace):
    credential_secret(getattr(args, "playwright_env_file", None))
    client = build_service_client(args)
    args.data_agent_workspace_id = resolve_workspace_id(client, args.data_agent_mode.workspace)
    return client


def _synthetic_agent(root: Path, name: str, item_id: str = "") -> Path:
    safe = re.sub(r"[^\w.\- ]", "_", name).strip(". ") or item_id or "DataAgent"
    return root / f"{safe}.DataAgent"


def _enumerate_agents(client, args: argparse.Namespace, root: Path,
                      names: dict[Path, str], suites: dict[Path, Path | None]) -> tuple[list[Path], dict[Path, str]]:
    agents = list_data_agents(client, args.data_agent_workspace_id)
    if len(agents) > ENUMERATION_LIMIT and not getattr(args, "all_items", False):
        raise SuiteError(
            f"Workspace contains {len(agents)} Data Agents; live tests consume capacity. Pass --all to run them."
        )
    selected, urls = [], {}
    for agent in agents:
        matches = [path for path, name in names.items() if name.lower() == agent["displayName"].lower()]
        if len(matches) > 1:
            raise SuiteError(f"Multiple local Data Agent items match {agent['displayName']}: {matches}. Narrow "
                             "--artifact-dir.")
        path = matches[0] if matches else _synthetic_agent(root, agent["displayName"], agent["id"])
        if path in selected:
            path = root / f"{agent['id']}.DataAgent"
        selected.append(path)
        names[path] = agent["displayName"]
        explicit = Path(args.tests) if getattr(args, "tests", None) else None
        suites[path] = suites.get(matches[0]) if matches else explicit
        urls[path] = data_agent_base_url(args.data_agent_workspace_id, agent["id"])
    return selected, urls


def discover_data_agents(args: argparse.Namespace) -> list[Path]:
    """Pair every denominator before resolving URLs; dry runs never acquire tokens."""
    try:
        return _discover_data_agents(args)
    except IncompleteServicePrincipalError as exc:
        raise ServiceExportError(str(exc), 127) from exc
    except SuiteError as exc:
        raise ServiceExportError(str(exc), 2) from exc
    except (ServiceResolutionError, FabricServiceClientError) as exc:
        raise ServiceExportError(str(exc), 1) from exc
    except AzureError as exc:
        raise ServiceExportError(f"Data Agent authentication failed: {exc}. Run `fab-test auth status`.", 127) from exc
    except ModeError as exc:
        raise ServiceExportError(str(exc), 2) from exc


def paired_suites(args: argparse.Namespace) -> dict[str, Path]:
    """Suites under --artifact-dir and fab-tests/, by the logicalId each claims."""
    return suite_index(search_roots(args), [Path(args.output_dir)])


def _discover_data_agents(args: argparse.Namespace) -> list[Path]:
    root, output = Path(args.artifact_dir), Path(args.output_dir)
    mode = (args.resolved_mode if getattr(args, "analyzer", None) == "data_agent"
            else resolve_data_agent_mode(args))
    args.data_agent_mode = mode
    target = getattr(args, "resolved_target", None)
    explicit = Path(args.tests) if getattr(args, "tests", None) else None
    if explicit:
        load_suite(explicit)
    paired = {} if explicit else paired_suites(args)
    local = find_artifact_dirs(root, (".DataAgent",), excluded_paths=[output])
    selected = discover_artifacts(root, "*.DataAgent", target, output_dir=output)
    names = {path: item_identity(path)[1] for path in local}
    suites = {path: pair_suite(path, paired, explicit) for path in local}
    if not selected and target is not None and target.path is None:
        selected = [path for path, name in names.items() if name.lower() == target.name.lower()]
    urls: dict[Path, str] = {}
    client = None
    if not selected and target is not None:
        if target.path is not None:
            raise SuiteError(f"No .DataAgent item at {target.path}. Check the path or pass a deployed item name.")
        if explicit is None:
            raise SuiteError("No local Data Agent item pairs with this target. Pass --tests FILE for a service target.")
        selected = [_synthetic_agent(root, target.name)]
        names[selected[0]], suites[selected[0]] = target.name, explicit
    enumerating = target is None and mode.source == "flag"
    if enumerating and not args.dry_run:
        client = _client(args)
        selected, urls = _enumerate_agents(client, args, root, names, suites)
    for path in selected:
        if path not in names:
            names[path] = item_identity(path)[1]
            suites[path] = pair_suite(path, paired, explicit)
        if args.dry_run or not suites[path] or _has_urls(suites[path]) or path in urls:
            continue
        client = client or _client(args)
        wanted = target.name if target is not None and target.scope == "workspace" else names[path]
        urls[path] = resolve_data_agent_url(client, args.data_agent_workspace_id, wanted)
    register_stems([*local, *(path for path in selected if path not in local)], root)
    args.data_agent_suites, args.data_agent_names, args.data_agent_urls = suites, names, urls
    args.data_agent_artifacts = selected
    return selected


def build_data_agent_command(artifact: Path, args: argparse.Namespace, output_dir: Path) -> list[str]:
    """Build the wrapper command using the already-paired suite and resolved URL."""
    command = [
        sys.executable, "-m", "fab_test.scripts.invoke_data_agent",
        "--artifact-path", str(artifact),
        "--output-path", str(output_dir / "data_agent" / results_stem(artifact) / "envelope.json"),
    ]
    tool = getattr(args, "_resolved_tool_path", "") or os.getenv("PROMPTFOO_PATH", "")
    if tool:  # else the wrapper reads PROMPTFOO_PATH itself; never an empty flag value
        command += ["--promptfoo-path", str(tool)]
    suite = getattr(args, "data_agent_suites", {}).get(artifact)
    if suite:
        command += ["--tests", str(suite.resolve())]
    url = getattr(args, "data_agent_urls", {}).get(artifact)
    if url:
        command += ["--base-url", url]
    env_file = getattr(args, "playwright_env_file", None)
    if env_file:
        command += ["--env-file", str(env_file)]
    timeout = getattr(args, "data_agent_timeout", None) or getattr(args, "timeout", None)
    if timeout:
        command += ["--timeout", str(timeout)]
    return command
