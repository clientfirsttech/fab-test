"""fab-test's admin/reporting subcommands: doctor, list, explain, config, auth.

Extracted from fab_test.py (Fab-Test Module Split epic). Pure move -- no
behavior change; `_ADMIN_COMMAND_HANDLERS` and `_dispatch_admin_command`
stay in fab_test.py as the thin dispatcher tying this module in.
"""

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ._command_builders import (
    build_command as _build_command,
)
from ._config import resolve_setting, verbosity_level
from ._credentials import SIGN_IN_REMEDIATION, probe_credentials
from ._desktop import bridge_cli_path, detect_desktop_instances
from ._fab_test_context import (
    _DEFAULT_SUBPROCESS_TIMEOUT,
    ARTIFACT_ROOT,
    REPO_ROOT,
    RESULTS_ROOT,
)
from ._feature_flags import is_enabled, not_enabled_message
from ._metadata import (
    ANALYZERS,
    BPA_RULES,
    PBIR_RULES,
    RDL_RULES,
    metadata_path,
    resolve_metadata,
)
from ._mode import ModeError, ResolvedMode, resolve_mode
from ._pql_identity import token_account, token_tenant
from ._readiness import (
    check_readiness as _check_readiness,
)
from ._rule_overlay import overlay_rows
from ._run_targets import (
    _manifest_target,
    _target_of,
)
from ._scan import find_skipped_checkouts as _find_skipped_checkouts
from ._service_export import service_item_type, service_readiness
from ._target import TargetError, select_target
from ._telemetry import eventhouse_rows, lakehouse_rows
from .fab_test_local import _LOCAL_ANALYZERS, _local_readiness
from .fab_test_parser import _aliases_for, _canonical_name
from .fab_test_registry import (
    _DEFAULT_BPA_RULES,
    _DEFAULT_PBIR_RULES,
    _DEFAULT_RDL_RULES,
)
from .fab_test_registry import (
    ANALYZER_REGISTRY as _ANALYZER_REGISTRY,
)
from .fab_test_registry import (
    ANALYZER_SCOPES as _ANALYZER_SCOPES,
)
from .fab_test_registry import (
    discover_artifacts as _discover,
)
from .fab_test_registry import (
    is_repository_scoped as _is_repository_scoped,
)
from .fab_test_registry import (
    load_fab_test_all_analyzers as _load_fab_test_all_analyzers,
)
from .fab_test_registry import (
    unsupported_scope_error as _unsupported_scope_error,
)
from .fab_test_registry import (
    unsupported_type_error as _unsupported_type_error,
)
from .fab_test_registry import (
    visible_analyzers as _visible_analyzers,
)
from .fab_test_summary import (
    _print_auth_status,
    _print_config_show,
    _print_doctor,
    _print_list,
    _print_local_doctor,
)
from .fab_test_telemetry import _telemetry_readiness_rows


def _print_help(parser: argparse.ArgumentParser, topic: str | None) -> int:
    """`fab-test help [ANALYZER]` -- the git spelling of `--help`."""
    if topic:
        # Prints the subcommand's own help and exits; an unknown topic
        # exits 2 with the same message `fab-test <typo>` gives.
        parser.parse_args([topic, "--help"])
    parser.print_help()
    return 0


def _all_analyzers() -> tuple[str, ...]:
    """Resolve which analyzers `fab-test all` should run."""
    return _load_fab_test_all_analyzers(metadata_path(ANALYZERS, REPO_ROOT))


def _cache_entry_labels(cache_dir: Path) -> list[str]:
    """Return an `analyzer/platform[/version]` label for each cached tool.

    Derived from where a resolved-executable marker or an ``extracted/``
    directory actually lives, so it works for both the version-keyed cache
    layout and the older unversioned one -- no assumption about how many
    path segments sit above it. Reporting these by name is what turns
    `clean-tools`'s confirmation into something a maintainer can match
    against `analyzers.json`, instead of one generic "removed .fab-test-
    tools" line that doesn't say what was actually in it.
    """
    labels = set()
    for marker in cache_dir.rglob("resolved-executable.txt"):
        labels.add(marker.parent.relative_to(cache_dir).as_posix())
    for extracted in cache_dir.rglob("extracted"):
        if extracted.is_dir():
            labels.add(extracted.parent.relative_to(cache_dir).as_posix())
    return sorted(labels)


def _clean_tools(repo_root: Path, dry_run: bool) -> int:
    """Remove (or preview removing) the .fab-test-tools cache directory.

    Always a full wipe -- clean-tools is the "start over" command, not a
    selective prune. A version bump in analyzers.json already makes an old
    cached version unreachable on its own (see `_analyzer_tool_bootstrap.
    _cache_dir`); this just clears the cache directory entirely and names
    what was in it.
    """
    cache_dir = repo_root / ".fab-test-tools"
    if not cache_dir.exists():
        print("  ✓ fab-test clean-tools: nothing to clean (.fab-test-tools does not exist)")
        return 0

    entries = _cache_entry_labels(cache_dir)

    if dry_run:
        print(f"fab-test clean-tools — dry run, would remove {cache_dir}:")
        if entries:
            for label in entries:
                print(f"  • {label}")
        else:
            for f in sorted(p for p in cache_dir.rglob("*") if p.is_file()):
                print(f"  • {f.relative_to(cache_dir)}")
        return 0

    shutil.rmtree(cache_dir)
    for label in entries:
        print(f"  ✓ fab-test clean-tools: removed {label}")
    print(f"  ✓ fab-test clean-tools: removed {cache_dir}")
    return 0


# (key, env_var, packaged_default, cast) for every setting resolve_setting
# can currently resolve. Keep in sync with _config._VALID_KEYS.
_SETTING_SPECS: list[tuple[str, str | None, Any, type | None]] = [
    ("artifact_dir", None, str(ARTIFACT_ROOT), None),
    ("output_dir", None, str(RESULTS_ROOT), None),
    ("jobs", None, 1, None),
    ("format", None, "text", None),
    ("timeout", "ANALYZER_TIMEOUT", _DEFAULT_SUBPROCESS_TIMEOUT, int),
    ("verbosity", "ANALYZER_VERBOSITY", "default", verbosity_level),
    ("environment", "FABRIC_ENVIRONMENT", "", None),
    ("workspace", "FABRIC_WORKSPACE_ID", "", None),
    ("playwright_user_name", "PLAYWRIGHT_USER_NAME", "", None),
    ("playwright_config", "PLAYWRIGHT_CONFIG_PATH", "", None),
]

_SECRET_KEY_MARKERS = ("secret", "password", "token", "api_key")


def _is_secret_key(key: str) -> bool:
    """Whether a config key name looks like it holds a credential."""
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _config_validate(args: argparse.Namespace) -> int:
    """Report that the config file is valid.

    main() already runs merged_file_config()/validate_config() for every
    invocation before any subcommand dispatches -- reaching this handler
    at all means the config already passed. This just reports it.
    """
    output_format = getattr(args, "output_format", "text")
    if output_format == "json":
        print(json.dumps({"valid": True}, indent=2))
    else:
        print("✅ Configuration is valid.")
    return 0


def _ruleset_rows() -> list[dict[str, Any]]:
    """Return `config --show` rows naming where each ruleset resolved from.

    The path alone does not say whether it is a `.fab-test/metadata`
    override, this repository's legacy `.github/metadata` copy, or the copy
    packaged in the wheel -- and a consumer debugging an unexpected finding
    needs to know which ruleset produced it.
    """
    rows = []
    for key, relative in (("rules.bpa", BPA_RULES), ("rules.pbir", PBIR_RULES), ("rules.rdl", RDL_RULES)):
        resolved, origin = resolve_metadata(relative, REPO_ROOT)
        rows.append({"key": key, "value": str(resolved), "origin": origin})
    return rows


def _config_show(args: argparse.Namespace) -> int:
    """Print every effective setting fab-test would use, and where it came from.

    Never reflects an explicit CLI flag from *this* invocation -- `config`
    doesn't take `--jobs`/`--timeout`/etc. itself; it reports what a bare
    invocation of another subcommand would resolve to right now.
    """
    if getattr(args, "validate", False):
        return _config_validate(args)

    output_format = getattr(args, "output_format", "text")
    file_config = getattr(args, "file_config", {})
    rows = []
    for key, env_var, packaged_default, cast in _SETTING_SPECS:
        value, origin = resolve_setting(
            key,
            cli_value=None,
            env_var=env_var,
            file_config=file_config,
            packaged_default=packaged_default,
            cast=cast,
        )
        display_value = "<redacted>" if _is_secret_key(key) else value
        rows.append({"key": key, "value": display_value, "origin": origin})
    rows.extend(_ruleset_rows())
    rows.extend(overlay_rows(file_config.get("rules", {})))
    rows.extend(eventhouse_rows(file_config))
    rows.extend(lakehouse_rows(file_config))
    return _print_config_show(rows, output_format)


def _doctor_local(args: argparse.Namespace) -> int:
    """Check prerequisites for the local Desktop workflow (`fab-test local`).

    Python version and the Desktop-instance count are read directly, never
    downloaded; the Bridge CLI check is presence-only (see `bridge_cli_path`
    for why). Each `_LOCAL_ANALYZERS` entry reuses `_local_readiness`, the
    same check `fab-test local` itself runs before starting.
    """
    output_format = getattr(args, "output_format", "text")
    rows: list[dict[str, Any]] = []

    py_ok = sys.version_info >= (3, 12)
    rows.append({
        "check": "python",
        "ready": py_ok,
        "reason": platform.python_version(),
        "resolved_path": sys.executable,
        "remediation": None if py_ok else "Install Python 3.12 or later",
    })

    instances = detect_desktop_instances()
    rows.append({
        "check": "desktop",
        "ready": bool(instances),
        "reason": (
            f"{len(instances)} instance(s) running" if instances else "no running instance detected"
        ),
        "resolved_path": None,
        "remediation": None if instances else "Open a .pbip file in Power BI Desktop",
    })

    bridge_path = bridge_cli_path()
    rows.append({
        "check": "desktop-bridge",
        "ready": bridge_path is not None,
        "reason": "found on PATH" if bridge_path else "not found on PATH",
        "resolved_path": bridge_path,
        "remediation": (
            None if bridge_path
            else "npm install -g @microsoft/powerbi-desktop-bridge-cli (preview; report-render checks only)"
        ),
    })

    would_run = []
    for name in _LOCAL_ANALYZERS:
        readiness = _local_readiness(name, args)
        rows.append({"check": name, **readiness})
        if readiness["ready"]:
            would_run.append(name)

    return _print_local_doctor(rows, would_run, output_format)


def _doctor(args: argparse.Namespace) -> int:
    """Check whether each analyzer's prerequisites are ready to run."""
    if getattr(args, "local", False):
        return _doctor_local(args)

    output_format = getattr(args, "output_format", "text")
    only = getattr(args, "analyzer_filter", None)
    if only and not is_enabled(only):
        print(f"  ✗ fab-test doctor: {not_enabled_message(only)}", file=sys.stderr)
        return 2
    if only and only not in _ANALYZER_REGISTRY:
        print(
            f"  ✗ fab-test doctor: unknown analyzer '{only}'. "
            f"Valid names: {', '.join(_ANALYZER_REGISTRY)}",
            file=sys.stderr,
        )
        return 2

    # Naming one explicitly reports it even when hidden — hiding a name from
    # the menu should not refuse to answer a direct question about it.
    names = [only] if only else list(_visible_analyzers())
    rows = [{"analyzer": name, **_check_readiness(name, args)} for name in names]
    for row in rows:
        if service_item_type(row["analyzer"]) and row["analyzer"] != "pql_test":
            row["service"] = service_readiness(args)
    if not only:
        # Reported alongside the analyzers because it fails the same ways --
        # a missing tool, a missing credential -- but never counted toward
        # whether doctor passes: telemetry is optional, and a run that never
        # wanted it is not a broken installation.
        rows.extend(_telemetry_readiness_rows(args))
    return _print_doctor(rows, output_format, strict=getattr(args, "strict", False))


_TOOL_DISPLAY_NAMES = {
    "bpa": "Tabular Editor",
    "pbir": "PBIR Inspector",
    "a11y": "pbir-a11y",
}


def _list_analyzers(args: argparse.Namespace) -> int:
    """List every subcommand with its artifact glob, matched count, and tool."""
    artifact_dir = Path(args.artifact_dir)
    output_dir = Path(getattr(args, "output_dir", str(RESULTS_ROOT)))
    output_format = getattr(args, "output_format", "text")

    rows = []
    for name in _visible_analyzers():
        glob, description = _ANALYZER_REGISTRY[name]
        count = (
            1
            if _is_repository_scoped(name)
            else len(_discover(artifact_dir, glob, None, output_dir=output_dir))
        )
        canonical = _canonical_name(name)
        rows.append(
            {
                "analyzer": canonical,
                "aliases": _aliases_for(name, canonical),
                "description": description,
                "glob": glob or None,
                "matched_artifacts": count,
                "required_tool": _TOOL_DISPLAY_NAMES.get(name),
                "scopes": sorted(_ANALYZER_SCOPES.get(name, frozenset())),
            }
        )
    # A repository-scoped analyzer always reports 1 and never discovers, so
    # "everything matched nothing" is a question about the discovering rows
    # alone. Only then is the scan worth explaining -- a partial result is
    # not a problem, and the walk is not free.
    discovered = [row["matched_artifacts"] for row in rows if row["glob"]]
    checkouts = (
        _find_skipped_checkouts(artifact_dir) if discovered and not any(discovered) else []
    )
    return _print_list(rows, output_format, skipped_checkouts=checkouts)


def _explain_mode(args: argparse.Namespace, name: str) -> ResolvedMode | int:
    """Resolve the target and mode for `explain`, or return the exit code to stop on."""
    try:
        args.resolved_target = select_target(
            getattr(args, "target", None),
            getattr(args, "artifact", None),
            default_type=service_item_type(name),
        )
    except TargetError as exc:
        print(f"  ✗ fab-test explain: {exc}", file=sys.stderr)
        return 2
    refusal = _unsupported_scope_error(name, args.resolved_target) or _unsupported_type_error(
        name, args.resolved_target
    )
    if refusal:
        print(f"  ✗ fab-test explain: {refusal}", file=sys.stderr)
        return 2
    try:
        resolved_mode = resolve_mode(
            args.resolved_target,
            workspace_flag=getattr(args, "workspace_id", ""),
            artifact_dir=str(getattr(args, "artifact_dir", ".")),
        )
    except ModeError as exc:
        print(f"  ✗ fab-test explain: {exc}", file=sys.stderr)
        return 2
    args.mode = resolved_mode.mode
    args.resolved_mode = resolved_mode
    return resolved_mode


def _explain_analyzer(args: argparse.Namespace) -> int:
    """Show the resolved command for one analyzer without running it."""
    name = args.analyzer_name
    if name not in _ANALYZER_REGISTRY:
        print(
            f"  ✗ fab-test explain: unknown analyzer '{name}'. "
            f"Valid names: {', '.join(_ANALYZER_REGISTRY)}",
            file=sys.stderr,
        )
        return 2

    output_format = getattr(args, "output_format", "text")
    output_dir = Path(getattr(args, "output_dir", str(RESULTS_ROOT)))
    artifact_dir = Path(getattr(args, "artifact_dir", str(ARTIFACT_ROOT)))
    glob, _description = _ANALYZER_REGISTRY[name]

    resolved_mode = _explain_mode(args, name)
    if isinstance(resolved_mode, int):
        return resolved_mode
    item_type = service_item_type(name)

    if _is_repository_scoped(name):
        artifact = Path(".")
    elif resolved_mode.mode == "service" and item_type:
        # Nothing is exported to explain a run: show the item that would be.
        target = args.resolved_target
        item = f"{target.name}.{item_type}" if target else f"<every {item_type}>"
        artifact = Path(resolved_mode.workspace or "") / item
    else:
        matches = _discover(artifact_dir, glob, _target_of(args), output_dir=output_dir)
        # No real artifact to point at; show an illustrative command shape.
        artifact = matches[0] if matches else artifact_dir / f"<artifact>{glob.lstrip('*')}"

    readiness = _check_readiness(name, args)
    if readiness.get("resolved_path"):
        # A real run resolves the tool before building its command; without
        # this the command named the legacy default while Tool named the
        # bootstrapped install.
        args._resolved_tool_path = str(readiness["resolved_path"])
    command = _build_command(name, artifact, args, output_dir)
    default_rules_path = {
        "bpa": _DEFAULT_BPA_RULES,
        "pbir": _DEFAULT_PBIR_RULES,
        "rdl": _DEFAULT_RDL_RULES,
    }.get(name)
    rules_path = (
        getattr(args, "bpa_rules_path", None)
        or getattr(args, "rdl_rules_path", None)
        or getattr(args, "rules_path", None)
        or default_rules_path
    )
    payload = {
        "analyzer": name,
        "artifact": str(artifact),
        "target": _manifest_target(args),
        "mode": resolved_mode.mode,
        "source": resolved_mode.source,
        "command": command,
        "tool_path": readiness.get("resolved_path"),
        "rules_path": rules_path,
        "output_path": str(output_dir / name / artifact.stem / "envelope.json"),
    }

    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"fab-test explain {name}")
    print(f"  Mode:     {resolved_mode.banner()}")
    target = payload["target"]
    if target:
        located = target["workspace_id"] or target["workspace"] or target["path"] or "-"
        print(f"  Target:   {target['raw']}")
        print(f"  Scope:    {target['scope']}  (name: {target['name']}, "
              f"type: {target['type'] or 'any'}, at: {located})")
    print(f"  Artifact: {payload['artifact']}")
    if payload["tool_path"]:
        print(f"  Tool:     {payload['tool_path']}")
    if payload["rules_path"]:
        print(f"  Rules:    {payload['rules_path']}")
    print(f"  Output:   {payload['output_path']}")
    print(f"  Command:  {' '.join(command)}")
    return 0


def _verify_ambient_credential() -> str:
    """Acquire a token from the ambient Azure credential and return it, or raise.

    Split out so `auth status` has one seam to stub in tests and one place
    where a network call is deliberately allowed. `check_readiness` may
    never call this -- that asymmetry is the whole reason the §7 probe
    reports ambient credentials as unverified.
    """
    from .playwright_validation.fabric_service_client import _authenticate_ambient

    return _authenticate_ambient()


def _check_workspace_reachable(workspace_id: str, args: argparse.Namespace) -> bool:
    """Whether the resolved identity can actually read ``workspace_id``.

    Moved here from the §7 probe, which must make no network call. Lists
    items rather than fetching the workspace so a permission that is
    scoped to reading contents still reports reachable. A name is resolved
    first, as every analyzer's --workspace takes one.
    """
    from .playwright_validation.fabric_service_client import FabricServiceClientError, build_fabric_service_client
    from .playwright_validation.resolver import ServiceResolutionError, resolve_workspace_id

    try:
        client = build_fabric_service_client(
            env_file=getattr(args, "playwright_env_file", None)
        )
        client.list_items(resolve_workspace_id(client, workspace_id), "SemanticModel")
    except (FabricServiceClientError, ServiceResolutionError, OSError):
        return False
    return True


def _auth_status(args: argparse.Namespace) -> int:
    """Report the identity fab-test would use, verifying it for real."""
    output_format = getattr(args, "output_format", "text")
    status = probe_credentials(env_file=getattr(args, "playwright_env_file", None))

    if not status.resolved:
        return _print_auth_status(
            {
                "identity": {"source": None, "tenant_id": None, "verified": False},
                "workspace": None,
                "detail": status.detail,
                "remediation": status.remediation,
            },
            output_format,
            exit_code=127,
        )

    verified, detail = status.verified, status.detail
    account, tenant_id = None, status.tenant_id
    if not verified:
        try:
            token = _verify_ambient_credential() or ""
        except Exception as exc:  # noqa: BLE001 - boundary: any credential
            # failure becomes a reported status, never a traceback
            return _print_auth_status(
                {
                    "identity": {
                        "source": status.source,
                        "tenant_id": status.tenant_id,
                        "verified": False,
                    },
                    "workspace": None,
                    "detail": str(exc),
                    "remediation": SIGN_IN_REMEDIATION,
                },
                output_format,
                exit_code=127,
            )
        verified, detail = True, f"{status.source} verified"
        # An ambient sign-in is whoever last ran `az login` (or VS Code, or
        # ...): name that account, or a run against the wrong tenant's
        # same-named workspace looks like a fab-test bug.
        account = token_account(token) or None
        tenant_id = token_tenant(token) or tenant_id
        if account:
            detail = f"{status.source} verified as {account}"

    workspace_id = getattr(args, "workspace_id", "") or (
        getattr(args, "file_config", None) or {}
    ).get("workspace", "")
    workspace = None
    exit_code = 0
    if workspace_id:
        reachable = _check_workspace_reachable(workspace_id, args)
        workspace = {"id": workspace_id, "reachable": reachable}
        if not reachable:
            exit_code = 1

    return _print_auth_status(
        {
            "identity": {
                "source": status.source,
                "account": account,
                "tenant_id": tenant_id,
                "verified": verified,
            },
            "workspace": workspace,
            "detail": detail,
            "remediation": None,
        },
        output_format,
        exit_code=exit_code,
    )


_AUTH_LOGIN_FALLBACK = (
    "No delegable login tool found on PATH.\n"
    "  Sign in with `az login`, or set FABRIC_TENANT_ID, "
    "FABRIC_SERVICE_PRINCIPAL_ID, and FABRIC_SERVICE_PRINCIPAL_SECRET."
)


def _auth_login(args: argparse.Namespace) -> int:
    """Delegate the login to the tool that owns the credential.

    Mints and stores nothing. `fab-test` is a facade: `pql-test` already
    maintains a login with browser, certificate, federated-token, and
    managed-identity support, and a fourth token cache on a machine that
    already has three would be a security surface with no new capability
    behind it. When there is nothing to delegate to, name the command that
    works instead of failing quietly.
    """
    tool = shutil.which("pql-test")
    if tool is None:
        print(f"  ✗ fab-test auth login: {_AUTH_LOGIN_FALLBACK}")
        return 127

    command = [tool, "auth", "login"]
    cloud = getattr(args, "cloud", "") or ""
    if cloud and cloud != "public":
        command += ["--environment", cloud]

    # Printed before running so the caller can reproduce it without fab-test.
    print(f"  → delegating to: {' '.join(command)}")
    return subprocess.run(command, check=False).returncode


def _auth(args: argparse.Namespace) -> int:
    """Dispatch `fab-test auth <status|login>`."""
    if getattr(args, "auth_command", None) == "login":
        return _auth_login(args)
    return _auth_status(args)
