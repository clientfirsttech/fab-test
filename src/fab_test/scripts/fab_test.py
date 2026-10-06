#!/usr/bin/env python3
"""fab-test: Run Fabric artifact analyzers against fabric-artifacts locally.

fab-test runs analyzers against your actual Fabric artifacts.
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
import os
import sys
from collections.abc import Callable
from pathlib import Path

from fab_test import __version__ as _FAB_TEST_VERSION

from ._cli_utils import narrate
from ._config import (
    ConfigError,
    apply_verbosity_default,
    merged_file_config,
    validate_config,
)
from ._fab_test_context import (
    _PYPROJECT_CONFIG,
    REPO_ROOT,
    RESULTS_ROOT,  # noqa: F401 -- re-exported: tests import this directly from `fab_test`
)
from ._mode import ModeError, resolve_mode
from ._report_html import open_report_conflict
from ._run_manifest import RunManifest
from ._service_export import (
    finalize_exports,
    interactive_refusal,
    is_service_run,
    service_item_type,
    service_target_refusal,
)
from ._target import TargetError, select_target, workspace_conflict

# Re-exported: `_dispatch_admin_command`'s handler table and `_prepare_target`
# both still call these directly from fab_test.py's own code.
from .fab_test_admin import (
    _all_analyzers,
    _auth,
    _clean_tools,
    _config_show,
    _doctor,
    _explain_analyzer,
    _init,
    _list_analyzers,
    _print_help,
)

# Re-exported: tests import these directly from `fab_test` rather than from
# `fab_test_execution`, since that is where they lived before this split.
from .fab_test_execution import (  # noqa: F401
    _apply_environment_default,
    _artifact_exit_code,
    _manifest_target,
    _resolve_timeout,
    _resolve_workspace_target,
    _run_analyzer,
)
from .fab_test_local import _LOCAL_ANALYZERS, _run_local  # noqa: F401
from .fab_test_parser import (
    _SUBCOMMAND_ALIASES,
    build_parser,
)
from .fab_test_registry import (
    load_fab_test_all_analyzers as _load_fab_test_all_analyzers,  # noqa: F401
)
from .fab_test_registry import (
    unsupported_scope_error as _unsupported_scope_error,
)
from .fab_test_registry import (
    unsupported_type_error as _unsupported_type_error,
)
from .fab_test_skill import _skill

# Re-exported: tests import this directly from `fab_test` rather than from
# `fab_test_summary`, since that is where it lived before this split.
from .fab_test_summary import (
    _print_all_summary,
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
from .playwright_validation.execution_config import prepare_execution

# Ensure UTF-8 output on Windows where the default pipe encoding is cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)



_ADMIN_COMMAND_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "auth": _auth,
    "clean-tools": lambda args: _clean_tools(REPO_ROOT, args.dry_run),
    "doctor": _doctor,
    "list": _list_analyzers,
    "explain": _explain_analyzer,
    "config": _config_show,
    "init": _init,
    "skill": _skill,
}


def _dispatch_admin_command(args: argparse.Namespace) -> int | None:
    """Run the admin/reporting subcommand named by ``args.analyzer``.

    Returns ``None`` when ``args.analyzer`` isn't one of these, so the
    caller knows to fall through to the analyzer-running path instead.
    """
    handler = _ADMIN_COMMAND_HANDLERS.get(args.analyzer)
    return handler(args) if handler else None



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


def _prepare_verbosity(args: argparse.Namespace) -> int | None:
    """Turn ANALYZER_VERBOSITY or `verbosity:` into the -q/-v flag it stands for."""
    apply_verbosity_default(args, args.file_config)
    return None


def _prepare_report_flags(args: argparse.Namespace) -> int | None:
    """Refuse an explicit `--no-report --open-report` before anything runs."""
    conflict = open_report_conflict(args)
    if conflict:
        print(f"  ✗ fab-test: {conflict}", file=sys.stderr)
        return 2
    return None


def _pql_workspace_conflict(args: argparse.Namespace) -> str | None:
    """pql-test's --workspace (mode) and --workspace-id (XMLA) must agree."""
    if args.analyzer != "pql_test":
        return None
    service_ws = (getattr(args, "service_workspace", "") or "").strip()
    xmla_ws = (getattr(args, "workspace_id", "") or "").strip()
    if service_ws and xmla_ws and service_ws != xmla_ws:
        return (
            f"--workspace '{service_ws}' and --workspace-id '{xmla_ws}' "
            "name different workspaces; pass one or the other"
        )
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
            getattr(args, "target", None),
            getattr(args, "artifact", None),
            default_type=service_item_type(args.analyzer),
        )
    except TargetError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 2

    conflict = workspace_conflict(args.resolved_target, getattr(args, "workspace_id", ""))
    conflict = conflict or _pql_workspace_conflict(args)
    if conflict:
        print(f"  ✗ fab-test: {conflict}", file=sys.stderr)
        return 2

    try:
        # pql-test's --workspace-id is an XMLA connection setting, not a mode;
        # its mode flag is --workspace (service_workspace), like the others'.
        workspace_flag = (
            getattr(args, "service_workspace", "")
            if args.analyzer == "pql_test"
            else getattr(args, "workspace_id", "")
        )
        args.resolved_mode = resolve_mode(
            args.resolved_target,
            workspace_flag=workspace_flag,
            artifact_dir_explicit=getattr(args, "artifact_dir_explicit", False),
        )
    except ModeError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 2
    args.mode = args.resolved_mode.mode

    refusal = None
    if args.analyzer not in ("all", "local"):
        refusal = (
            _unsupported_scope_error(args.analyzer, args.resolved_target)
            or _unsupported_type_error(args.analyzer, args.resolved_target)
            or service_target_refusal(args.analyzer, args)
        )
    refusal = refusal or (args.mode == "service" and interactive_refusal(args)) or None
    if refusal:
        print(f"  ✗ fab-test: {refusal}", file=sys.stderr)
        return 2

    # Under --format json or -q stderr stays silent; the mode is in the envelope.
    if getattr(args, "output_format", "text") != "json" and not getattr(args, "quiet", False):
        print(args.resolved_mode.banner(), file=sys.stderr)
    if getattr(args, "dry_run", False) and is_service_run(args.analyzer, args) and args.resolved_target:
        # A typed target is listed from its name alone: no token, no API call.
        return None
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
    lambda args: prepare_execution(args, REPO_ROOT),
    _prepare_verbosity,
    _prepare_report_flags,
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

    try:
        return _dispatch_run(args)
    finally:
        # Exports are test inputs, not results: gone on every exit path.
        finalize_exports(args)


if __name__ == "__main__":
    sys.exit(main())
