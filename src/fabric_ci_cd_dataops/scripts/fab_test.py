#!/usr/bin/env python3
"""fab-test: Run Fabric artifact analyzers against .fabric/artifacts locally.

fab-test runs analyzers against your actual .fabric artifacts.
It is NOT pytest. Use pytest to test the framework; use fab-test to test your artifacts.

Usage:
    python scripts/fab_test.py bpa [--tabular-editor-path PATH] [-v]
    python scripts/fab_test.py pbir [--inspector-path PATH] [-v]
    python scripts/fab_test.py pql_test [-v]
    python scripts/fab_test.py pql_lint [-v]
    python scripts/fab_test.py all [-v]

Global flags (all subcommands):
    --artifact STEM      Only analyze the artifact matching this stem
    --artifact-dir DIR   Root to discover artifacts under (default: the working directory)
    --output-dir DIR     Root for result envelopes (default: fab-test-results)
    --dry-run            List matching artifacts without running any analyzer
    --telemetry          Stream telemetry to Eventhouse when configured
    --no-telemetry       Suppress telemetry even when configured
    --format {text,json} Output format for aggregate summaries (default: text)
    -v, --verbose        Increase output verbosity (one -v = verbose, two -v = debug)
"""

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fabric_ci_cd_dataops import __version__ as _FAB_TEST_VERSION

from ._cli_utils import narrate
from ._config import (
    CONFIG_FILENAME,
    ConfigError,
    merged_file_config,
    resolve_setting,
    validate_config,
)
from ._credentials import probe_credentials
from ._desktop import bridge_cli_path, detect_desktop_instances
from ._fab_test_context import (
    _DEFAULT_SUBPROCESS_TIMEOUT,
    _PYPROJECT_CONFIG,
    ARTIFACT_ROOT,
    REPO_ROOT,
    RESULTS_ROOT,
)
from ._metadata import (
    ANALYZERS,
    BPA_RULES,
    PBIR_RULES,
    metadata_path,
    resolve_metadata,
)
from ._pbip_discovery import discover_pbip_projects as _discover_pbip_projects
from ._run_manifest import RunManifest
from ._scan import find_skipped_checkouts as _find_skipped_checkouts
from ._target import TargetError, select_target, workspace_conflict
from ._telemetry import eventhouse_rows

# Re-exported: tests import these directly from `fab_test` rather than from
# `fab_test_execution`, since that is where they lived before this split.
from .fab_test_execution import (  # noqa: F401
    _apply_environment_default,
    _artifact_exit_code,
    _manifest_target,
    _resolve_timeout,
    _resolve_workspace_target,
    _run_analyzer,
    _target_of,
)
from .fab_test_parser import (
    _SUBCOMMAND_ALIASES,
    _aliases_for,
    _canonical_name,
    build_parser,
)
from .fab_test_registry import (
    _DEFAULT_BPA_RULES,
    _DEFAULT_PBIR_RULES,
)
from .fab_test_registry import (
    ANALYZER_REGISTRY as _ANALYZER_REGISTRY,
)
from .fab_test_registry import (
    ANALYZER_SCOPES as _ANALYZER_SCOPES,
)
from .fab_test_registry import (
    build_command as _build_command,
)
from .fab_test_registry import (
    check_readiness as _check_readiness,
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

# Re-exported: tests import this directly from `fab_test` rather than from
# `fab_test_summary`, since that is where it lived before this split.
from .fab_test_summary import (
    _print_all_summary,
    _print_auth_status,
    _print_config_show,
    _print_doctor,
    _print_list,
    _print_local_doctor,
    _print_summary,  # noqa: F401
)

# Re-exported under their fab_test.py names, unused in this module's own body:
# several tests import these directly from `fab_test` rather than from
# `fab_test_telemetry`, since that is where they lived before this split.
from .fab_test_telemetry import (  # noqa: F401
    _build_telemetry_payload,
    _close_telemetry,
    _detect_origin,
    _git_context,
    _machine_context,
    _open_telemetry,
    _relativize_paths,
    _send_telemetry,
    _telemetry_decision,
    _telemetry_destination,
    _telemetry_enabled,
    _telemetry_readiness,
    _validate_telemetry_payload,
)

# Ensure UTF-8 output on Windows where the default pipe encoding is cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)



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


def _clean_tools(repo_root: Path, dry_run: bool) -> int:
    """Remove (or preview removing) the .fab-test-tools cache directory."""
    cache_dir = repo_root / ".fab-test-tools"
    if not cache_dir.exists():
        print("  ✓ fab-test clean-tools: nothing to clean (.fab-test-tools does not exist)")
        return 0

    if dry_run:
        files = sorted(p for p in cache_dir.rglob("*") if p.is_file())
        print(f"fab-test clean-tools — dry run, would remove {cache_dir}:")
        for f in files:
            print(f"  • {f.relative_to(cache_dir)}")
        return 0

    shutil.rmtree(cache_dir)
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
    ("environment", "FABRIC_ENVIRONMENT", "", None),
    ("workspace", "FABRIC_WORKSPACE_ID", "", None),
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
    for key, relative in (("rules.bpa", BPA_RULES), ("rules.pbir", PBIR_RULES)):
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
    rows.extend(eventhouse_rows(file_config))
    return _print_config_show(rows, output_format)


_FAB_TEST_YML_TEMPLATE = """\
# fab-test.yml -- optional config-file front door for the fab-test CLI.
#
# Every key below is entirely optional and commented out: an absent key
# falls back to its environment variable (where one exists) and then its
# packaged default. Uncomment and edit only the settings you want to pin.
#
# Precedence for every setting: CLI flag > environment variable >
# this file > packaged default. Run `fab-test config --show` to see the
# effective value and origin of each setting right now.

# artifact_dir: .fabric/artifacts   # root to discover artifacts (repo root for `fab-test local`)
# output_dir: fab-test-results      # root for result envelopes and the run manifest
# jobs: 1                          # artifacts to run in parallel for the same analyzer
# format: text                     # text | json
# timeout: 200                     # per-artifact subprocess timeout in seconds [env: ANALYZER_TIMEOUT]
# environment: DEV                 # default environment label [env: FABRIC_ENVIRONMENT]
# workspace: Sales Dev             # default workspace name or GUID [env: FABRIC_WORKSPACE_ID]

# Rule overlays: deltas applied to a packaged ruleset instead of forking it.
# rules:
#   bpa:
#     disable: [RULE_ID]                  # remove a rule from the effective ruleset
#     severity: {RULE_ID: warning}        # info | warning | error
#     extend: path/to/extra-rules.json    # append rules from another file
#   pbir:
#     disable: [RULE_ID]
#     severity: {RULE_ID: warning}        # warning | error (PBIR Inspector has no "info" level)

# Ship analyzer telemetry to a Fabric Eventhouse. A configured destination is
# the enablement -- there is no separate on/off flag. Either key can instead
# be set via EVENTHOUSE_URI / EVENTHOUSE_DATABASE, which win over this file.
# telemetry:
#   eventhouse:
#     uri: https://<cluster>.kusto.fabric.microsoft.com       # [env: EVENTHOUSE_URI]
#     database: <database-name>                               # [env: EVENTHOUSE_DATABASE]
"""

_ENV_EXAMPLE_TEMPLATE = """\
# .env.example -- copy to .fab-test/.env and fill in the values you need.
# Search order: --env-file > PLAYWRIGHT_ENV_FILE > .fab-test/.env > ./.env.
# Never commit the real .env -- .fab-test/.gitignore keeps this directory's
# copy untracked even though .fab-test/metadata/ is meant to be checked in.

# Service principal for Fabric/Power BI REST API access.
# All three are optional for local use: leave them unset to fall back to
# DefaultAzureCredential (az login, a managed identity, VS Code sign-in,
# ...) for every command except `fab-test playwright`, which always needs
# a full service principal to generate an embed token.
FABRIC_TENANT_ID=
FABRIC_CLIENT_ID=
FABRIC_CLIENT_SECRET=

# Playwright visual/error validation target. Only needed when not using
# --artifact to resolve a report from a deployed workspace.
PLAYWRIGHT_WORKSPACE_ID=
PLAYWRIGHT_REPORT_ID=
PLAYWRIGHT_REPORT_NAME=
PLAYWRIGHT_DATASET_ID=
"""

_FAB_TEST_GITIGNORE_TEMPLATE = """\
# fab-test's own guard: .fab-test/metadata/ is meant to be checked in,
# but a .env in this directory holds credentials and never should be.
.env
"""


def _init(args: argparse.Namespace) -> int:
    """Scaffold a commented fab-test.yml, .fab-test/.gitignore, and
    .fab-test/.env.example.

    Never overwrites an existing file -- each is reported and left
    untouched instead. --dry-run reports what would be created without
    writing anything. `.fab-test/.env.example` replaces the root
    `.env.example` for new repositories: it lives beside the `.gitignore`
    that makes a real `.env` in the same directory safe to keep, rather
    than depending on a consumer's root `.gitignore` already covering it.
    """
    output_format = getattr(args, "output_format", "text")
    dry_run = getattr(args, "dry_run", False)
    fab_test_dir = REPO_ROOT / ".fab-test"
    templates = {
        REPO_ROOT / CONFIG_FILENAME: _FAB_TEST_YML_TEMPLATE,
        fab_test_dir / ".gitignore": _FAB_TEST_GITIGNORE_TEMPLATE,
        fab_test_dir / ".env.example": _ENV_EXAMPLE_TEMPLATE,
    }

    created = []
    would_create = []
    already_existed = []
    for path, template in templates.items():
        if path.exists():
            already_existed.append(str(path))
            narrate(
                f"  • fab-test init: already exists, left untouched: {path}",
                output_format=output_format,
            )
        elif dry_run:
            would_create.append(str(path))
            narrate(f"  fab-test init: would create {path}", output_format=output_format)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(template, encoding="utf-8")
            created.append(str(path))
            narrate(f"  ✓ fab-test init: created {path}", output_format=output_format)

    if output_format == "json":
        print(json.dumps(
            {"created": created, "would_create": would_create, "already_existed": already_existed},
            indent=2,
        ))
    return 0


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
    if not only:
        # Reported alongside the analyzers because it fails the same ways --
        # a missing tool, a missing credential -- but never counted toward
        # whether doctor passes: telemetry is optional, and a run that never
        # wanted it is not a broken installation.
        rows.append(_telemetry_readiness(args))
    return _print_doctor(rows, output_format)


_TOOL_DISPLAY_NAMES = {
    "bpa": "Tabular Editor",
    "pbir": "PBIR Inspector",
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

    try:
        args.resolved_target = _target_of(args)
    except TargetError as exc:
        print(f"  ✗ fab-test explain: {exc}", file=sys.stderr)
        return 2
    refusal = _unsupported_scope_error(name, args.resolved_target) or _unsupported_type_error(
        name, args.resolved_target
    )
    if refusal:
        print(f"  ✗ fab-test explain: {refusal}", file=sys.stderr)
        return 2

    if _is_repository_scoped(name):
        artifact = Path(".")
    else:
        matches = _discover(artifact_dir, glob, _target_of(args), output_dir=output_dir)
        # No real artifact to point at; show an illustrative command shape.
        artifact = matches[0] if matches else artifact_dir / f"<artifact>{glob.lstrip('*')}"

    command = _build_command(name, artifact, args, output_dir)
    readiness = _check_readiness(name, args)
    default_rules_path = {"bpa": _DEFAULT_BPA_RULES, "pbir": _DEFAULT_PBIR_RULES}.get(name)
    rules_path = (
        getattr(args, "bpa_rules_path", None)
        or getattr(args, "rules_path", None)
        or default_rules_path
    )
    payload = {
        "analyzer": name,
        "artifact": str(artifact),
        "target": _manifest_target(args),
        "command": command,
        "tool_path": readiness.get("resolved_path"),
        "rules_path": rules_path,
        "output_path": str(output_dir / name / artifact.stem / "envelope.json"),
    }

    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return 0

    print(f"fab-test explain {name}")
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


def _verify_ambient_credential() -> None:
    """Acquire a token from the ambient Azure credential, or raise.

    Split out so `auth status` has one seam to stub in tests and one place
    where a network call is deliberately allowed. `check_readiness` may
    never call this -- that asymmetry is the whole reason the §7 probe
    reports ambient credentials as unverified.
    """
    from .playwright_validation.fabric_service_client import _authenticate_ambient

    _authenticate_ambient()


def _check_workspace_reachable(workspace_id: str, args: argparse.Namespace) -> bool:
    """Whether the resolved identity can actually read ``workspace_id``.

    Moved here from the §7 probe, which must make no network call. Lists
    items rather than fetching the workspace so a permission that is
    scoped to reading contents still reports reachable.
    """
    from .playwright_validation.fabric_service_client import (
        FabricServiceClientError,
        build_fabric_service_client,
    )

    try:
        client = build_fabric_service_client(
            env_file=getattr(args, "playwright_env_file", None)
        )
        client.list_items(workspace_id, "SemanticModel")
    except (FabricServiceClientError, OSError):
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
    if not verified:
        try:
            _verify_ambient_credential()
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
                    "remediation": "Sign in with `az login`, or set a service principal",
                },
                output_format,
                exit_code=127,
            )
        verified, detail = True, f"{status.source} verified"

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
                "tenant_id": status.tenant_id,
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


_ADMIN_COMMAND_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "auth": _auth,
    "clean-tools": lambda args: _clean_tools(REPO_ROOT, args.dry_run),
    "doctor": _doctor,
    "list": _list_analyzers,
    "explain": _explain_analyzer,
    "config": _config_show,
    "init": _init,
}


def _dispatch_admin_command(args: argparse.Namespace) -> int | None:
    """Run the admin/reporting subcommand named by ``args.analyzer``.

    Returns ``None`` when ``args.analyzer`` isn't one of these, so the
    caller knows to fall through to the analyzer-running path instead.
    """
    handler = _ADMIN_COMMAND_HANDLERS.get(args.analyzer)
    return handler(args) if handler else None


# pql_lint is excluded while it is hidden from the advertised surface
# (see HIDDEN_ANALYZERS): a bundle should not run what the CLI does not
# offer. It remains fully invocable on its own.
_LOCAL_ANALYZERS = ("bpa", "pbir", "pql_test")


def _pql_lint_path() -> str | None:
    """Resolved location of the ``pqlint`` package if usable, else ``None``.

    Unlike pql-test, pqlint is not a pinned fab-test dependency, so a
    fresh install genuinely may not have it -- the case this check exists
    to catch (mirrors invoke_pqlint.py's own resolution fallback).
    """
    on_path = shutil.which("pqlint")
    if on_path:
        return on_path
    spec = importlib.util.find_spec("pqlint")
    return spec.origin if spec else None


def _local_readiness(name: str, args: argparse.Namespace) -> dict[str, Any]:
    """Return a readiness dict for one of the `_LOCAL_ANALYZERS`.

    Always has the same four keys as `check_readiness` (ready, reason,
    resolved_path, remediation) so a JSON consumer never has to branch on
    which analyzer it's reading. pql_test is always ready (a pinned
    fab-test dependency); pql_lint needs its own presence check since
    pqlint is not bundled; bpa/pbir reuse the existing bootstrapped-tool
    readiness probe.
    """
    if name == "pql_lint":
        path = _pql_lint_path()
        if path:
            return {"ready": True, "reason": "pqlint available", "resolved_path": path, "remediation": None}
        return {
            "ready": False,
            "reason": "pqlint not found on PATH or importable",
            "resolved_path": None,
            "remediation": "pip install pqlint",
        }
    if name == "pql_test":
        return {
            "ready": True,
            "reason": "pql-test is a fab-test dependency",
            "resolved_path": None,
            "remediation": None,
        }
    return _check_readiness(name, args)


def _project_matches_glob(project: Any, glob: str) -> bool:
    """Whether a discovered PbipProject has the folder `glob` matches."""
    suffix = glob.lstrip("*")
    if suffix == ".SemanticModel":
        return project.semantic_model_path is not None
    if suffix == ".Report":
        return project.report_path is not None
    return False


def _build_local_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Build the `fab-test local --dry-run` plan.

    Never spawns a subprocess or touches Desktop detection: it only
    discovers projects on disk and checks each analyzer's readiness, the
    same primitives `doctor`/`list` already use.
    """
    artifact_dir = Path(args.artifact_dir)
    projects = _discover_pbip_projects(artifact_dir)

    plan_analyzers = []
    for name in _LOCAL_ANALYZERS:
        readiness = _local_readiness(name, args)
        if not readiness["ready"]:
            plan_analyzers.append({
                "analyzer": name,
                "status": "skipped",
                "reason": readiness["reason"],
                "remediation": readiness["remediation"],
            })
            continue
        glob, _description = _ANALYZER_REGISTRY[name]
        matching = [p.name for p in projects if _project_matches_glob(p, glob)]
        plan_analyzers.append({"analyzer": name, "status": "would_run", "projects": matching})

    return {
        "analyzer": "local",
        "dry_run": True,
        "projects": [p.name for p in projects],
        "analyzers": plan_analyzers,
    }


def _narrate_local_plan(plan: dict[str, Any], output_format: str) -> None:
    """Print the fab-test local --dry-run plan as human-readable narration."""
    projects = plan["projects"]
    narrate(
        f"\nfab-test local — dry run, {len(projects)} project(s): "
        f"{', '.join(projects) if projects else '(none)'}",
        output_format=output_format,
    )
    for entry in plan["analyzers"]:
        if entry["status"] == "skipped":
            hint = f" ({entry['remediation']})" if entry["remediation"] else ""
            narrate(
                f"  ⏭ {entry['analyzer']}: skipped -- {entry['reason']}{hint}",
                output_format=output_format,
            )
        else:
            names = ", ".join(entry["projects"]) if entry["projects"] else "(no matching project)"
            narrate(f"  ▶ {entry['analyzer']}: would run against {names}", output_format=output_format)


def _run_local(args: argparse.Namespace) -> int:
    """Run every analyzer in `_LOCAL_ANALYZERS` against every discovered project.

    An analyzer whose prerequisite is absent is skipped with a remediation
    hint rather than failing the run (vision §2.7: platform gaps degrade to
    skips). Never requires a workspace ID, service-principal credential, or
    Fabric network call -- the `local` subparser doesn't even expose those
    flags.
    """
    output_format = getattr(args, "output_format", "text")
    output_dir = Path(args.output_dir)

    if getattr(args, "dry_run", False):
        plan = _build_local_plan(args)
        _narrate_local_plan(plan, output_format)
        if output_format == "json":
            print(json.dumps(plan, indent=2))
        return 0

    manifest = RunManifest(
        _FAB_TEST_VERSION, sys.argv, origin=_detect_origin(), target=_manifest_target(args)
    )
    telemetry = _open_telemetry(args)

    results: list[dict[str, Any]] = []
    for name in _LOCAL_ANALYZERS:
        readiness = _local_readiness(name, args)
        if not readiness["ready"]:
            hint = f" ({readiness['remediation']})" if readiness["remediation"] else ""
            narrate(
                f"  ⏭ fab-test local: {name} skipped -- {readiness['reason']}{hint}",
                output_format=output_format,
            )
            results.append({"analyzer": name, "status": "skipped", "reason": readiness["reason"]})
            continue
        code = _run_analyzer(name, args, output_dir, manifest, telemetry)
        results.append({"analyzer": name, "status": "ran", "exit_code": code})

    exit_code = 1 if any(r.get("exit_code", 0) != 0 for r in results) else 0
    # Flushed before the manifest is written so run.json can record whether
    # this run's telemetry landed.
    manifest.telemetry_error = _close_telemetry(telemetry, args)
    manifest.write(output_dir, exit_code)
    if output_format == "json":
        print(json.dumps({"analyzer": "local", "results": results, "exit_code": exit_code}, indent=2))
    return exit_code


def _prepare_config(args: argparse.Namespace) -> int | None:
    """Load and validate the file config onto ``args``, or return an exit code.

    Consumed downstream by every ``resolve_setting()`` call
    (`_resolve_timeout`, `_apply_environment_default`, `fab-test config
    --show`), which is why it runs before anything reads a setting.
    """
    try:
        args.file_config, warnings = merged_file_config(
            REPO_ROOT, REPO_ROOT / "pyproject.toml", args.config
        )
        validate_config(args.file_config)
    except ConfigError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 2
    for warning in warnings:
        narrate(f"  ⚠ fab-test: {warning}", output_format=getattr(args, "output_format", "text"))

    # An explicit --telemetry with no destination is a configuration problem,
    # reported here so it costs one message per run rather than one per
    # artifact -- and before any analyzer starts, so nothing runs only to
    # discover its telemetry had nowhere to go.
    refusal = _telemetry_decision(args).refusal
    if refusal:
        print(f"  ✗ fab-test: {refusal}", file=sys.stderr)
        return 2
    return None


def _prepare_target(args: argparse.Namespace) -> int | None:
    """Resolve and validate the target onto ``args``, or return an exit code.

    Four checks that have to happen in this order. The target is resolved
    once so discovery, the command builders, and the run manifest all read
    the same value instead of re-deriving it. The scope refusal comes
    before workspace resolution deliberately: asking Fabric to resolve a
    workspace for an analyzer that could never read a deployed item wastes
    a round trip and reports the wrong failure.
    """
    try:
        args.resolved_target = select_target(
            getattr(args, "target", None), getattr(args, "artifact", None)
        )
    except TargetError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 2

    conflict = workspace_conflict(args.resolved_target, getattr(args, "workspace_id", ""))
    if conflict:
        print(f"  ✗ fab-test: {conflict}", file=sys.stderr)
        return 2

    if args.analyzer not in ("all", "local"):
        refusal = _unsupported_scope_error(
            args.analyzer, args.resolved_target
        ) or _unsupported_type_error(args.analyzer, args.resolved_target)
        if refusal:
            print(f"  ✗ fab-test: {refusal}", file=sys.stderr)
            return 2

    return _resolve_workspace_target(args)


def _prepare_paths(args: argparse.Namespace) -> int | None:
    """Apply the environment default and confirm the artifact root exists."""
    _apply_environment_default(args, _PYPROJECT_CONFIG)
    artifact_dir = Path(args.artifact_dir)
    if not artifact_dir.exists():
        narrate(
            f"  ✗ fab-test: --artifact-dir does not exist: {artifact_dir}",
            output_format=args.output_format,
        )
        return 2
    return None


# Ordered: each returns an exit code to stop on, or None to continue. The
# order is load-bearing -- config before anything reads a setting, the admin
# commands before a target is resolved they do not need, and paths last
# because the environment default feeds them.
_PREPARE_STEPS: tuple[Callable[[argparse.Namespace], int | None], ...] = (
    _prepare_config,
    _dispatch_admin_command,
    _prepare_target,
    _prepare_paths,
)


def _dispatch_run(args: argparse.Namespace) -> int:
    """Run the requested analyzer (or the `all` / `local` bundle)."""
    output_dir = Path(args.output_dir)

    if args.analyzer == "local":
        return _run_local(args)

    manifest = RunManifest(
        _FAB_TEST_VERSION, sys.argv, origin=_detect_origin(), target=_manifest_target(args)
    )
    telemetry = _open_telemetry(args)

    target = args.resolved_target

    if args.analyzer == "all":
        analyzers = _all_analyzers()
        # An analyzer that cannot honor the target is skipped rather than
        # failing the batch: `all local/Sales` should still run everything
        # that reads files, and saying which were skipped is more useful
        # than refusing the whole invocation.
        runnable = []
        for name in analyzers:
            refusal = _unsupported_scope_error(name, target) or _unsupported_type_error(
                name, target
            )
            if refusal:
                narrate(
                    f"  ⚠ fab-test all: skipping {name} — {refusal}",
                    output_format=args.output_format,
                )
            else:
                runnable.append(name)
        if runnable:
            codes = [
                _run_analyzer(name, args, output_dir, manifest, telemetry) for name in runnable
            ]
            exit_code = _print_all_summary(output_dir, runnable, codes, args)
        elif analyzers:
            narrate(
                "  ✗ fab-test all: no configured analyzer can run against that target",
                output_format=args.output_format,
            )
            exit_code = 2
        else:
            narrate(
                "  ⚠ fab-test all: no analyzers configured in analyzers.json",
                output_format=args.output_format,
            )
            exit_code = 0
    else:
        # The scope refusal for a single analyzer already ran above, before
        # any network call.
        exit_code = _run_analyzer(args.analyzer, args, output_dir, manifest, telemetry)

    # One flush for the whole run, `all` included: a sink per analyzer would
    # reopen the ingest client for each of them.
    manifest.telemetry_error = _close_telemetry(telemetry, args)
    manifest.write(output_dir, exit_code)
    return exit_code


def main() -> int:
    """Parse arguments, run the preparation chain, then dispatch.

    Reads as resolve, validate, dispatch. Each step in `_PREPARE_STEPS`
    returns an exit code to stop on or None to continue, which is what
    keeps the guards out of here -- they used to be ten early returns
    inline, one per failure mode added over time.
    """
    parser = build_parser()
    args = parser.parse_args()
    if args.analyzer == "help":
        # Answered before the config is read: help is what you reach for
        # when something is already wrong, including the config itself.
        return _print_help(parser, args.help_topic)
    args.analyzer = _SUBCOMMAND_ALIASES.get(args.analyzer, args.analyzer)

    for step in _PREPARE_STEPS:
        exit_code = step(args)
        if exit_code is not None:
            return exit_code

    return _dispatch_run(args)


if __name__ == "__main__":
    sys.exit(main())
