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
    --artifact-dir DIR   Root for .fabric artifacts (default: .fabric/artifacts)
    --output-dir DIR     Root for result envelopes (default: analyzer-results)
    --dry-run            List matching artifacts without running any analyzer
    --telemetry          Stream telemetry to Eventhouse when configured
    --no-telemetry       Suppress telemetry even when configured
    --format {text,json} Output format for aggregate summaries (default: text)
    -v, --verbose        Increase output verbosity (one -v = verbose, two -v = debug)
"""

import argparse
import contextlib
import difflib
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fabric_ci_cd_dataops import __version__ as _FAB_TEST_VERSION

from ._analyzer_annotations import (
    emit_pr_review_comments,
    emit_workflow_annotations,
)
from ._analyzer_envelope import _severity_counts
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
from ._pbip_discovery import discover_pbip_projects as _discover_pbip_projects
from ._report_html import resolve_report
from ._run_manifest import RunManifest
from ._target import TargetError, select_target, target_from_args, workspace_conflict
from .eventhouse_logger import publish_analyzer_telemetry
from .fab_test_registry import (
    _DEFAULT_BPA_RULES,
    _DEFAULT_INSPECTOR_PATH,
    _DEFAULT_PBIR_RULES,
    _DEFAULT_TE_PATH,
)
from .fab_test_registry import (
    ANALYZER_REGISTRY as _ANALYZER_REGISTRY,
)
from .fab_test_registry import (
    ANALYZER_SCOPES as _ANALYZER_SCOPES,
)
from .fab_test_registry import (
    HIDDEN_ANALYZERS as _HIDDEN_ANALYZERS,
)
from .fab_test_registry import (
    applicable_analyzers as _applicable_analyzers,
)
from .fab_test_registry import (
    bound_desktop_instance as _bound_desktop_instance,
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
    discover_pbip_sources as _discover_pbip_sources,
)
from .fab_test_registry import (
    is_repository_scoped as _is_repository_scoped,
)
from .fab_test_registry import (
    load_fab_test_all_analyzers as _load_fab_test_all_analyzers,
)
from .fab_test_registry import (
    preflight_error as _preflight_error,
)
from .fab_test_registry import (
    unsupported_scope_error as _unsupported_scope_error,
)
from .fab_test_registry import (
    visible_analyzers as _visible_analyzers,
)
from .fab_test_summary import (
    _print_all_summary,
    _print_auth_status,
    _print_config_show,
    _print_doctor,
    _print_list,
    _print_local_doctor,
    _print_summary,
    _read_artifact_envelope,
)
from .playwright_validation.resolver import resolve_workspace_id

# Ensure UTF-8 output on Windows where the default pipe encoding is cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def _repo_root() -> Path:
    """Return the repository root.

    In CI the runner checks out the repo into ``GITHUB_WORKSPACE``. When the
    package is installed as a wheel, ``__file__`` points into ``site-packages``,
    so resolving paths from the script location is wrong. Use the current
    working directory as the default root so ``fab-test`` operates on the repo
    it is invoked from.
    """
    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    return Path.cwd().resolve()


REPO_ROOT = _repo_root()
SCRIPTS_DIR = REPO_ROOT / "scripts"
ARTIFACT_ROOT = REPO_ROOT / ".fabric" / "artifacts"
RESULTS_ROOT = REPO_ROOT / "analyzer-results"


_PYPROJECT_CONFIG, _FILE_CONFIG_WARNINGS = merged_file_config(REPO_ROOT, REPO_ROOT / "pyproject.toml")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _guid_type(value: str) -> str:
    """argparse type= validator for --workspace-id; empty (unset) is allowed."""
    if value and not _GUID_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a valid GUID "
            "(expected format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)"
        )
    return value


def _is_ci() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


_CI_PREFIXES = ("::error::", "::warning::", "::notice::")


def _clean_annotation(line: str) -> str:
    for prefix in _CI_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix):]
    return line


def _verbosity_env(args: argparse.Namespace) -> str:
    """Map fab-test -v/-vv flags to ANALYZER_VERBOSITY values."""
    count = getattr(args, "verbose", 0) or 0
    if count >= 2:
        return "debug"
    if count == 1:
        return "verbose"
    return ""


# Default per-artifact subprocess timeout (seconds), used when neither
# --timeout nor ANALYZER_TIMEOUT is set. Matches the longest wrapper timeout.
_DEFAULT_SUBPROCESS_TIMEOUT = 120


# Defined in _report_html so fab_test_summary can ask the same question
# without importing this module, which would be a cycle.
_resolve_report = resolve_report


def _resolve_timeout(
    args: argparse.Namespace, config: dict[str, Any] | None = None
) -> int:
    """Resolve the per-artifact subprocess timeout via the centralized resolver.

    Precedence: --timeout > ANALYZER_TIMEOUT > config file > default.
    """
    config = _PYPROJECT_CONFIG if config is None else config
    value, _origin = resolve_setting(
        "timeout",
        cli_value=getattr(args, "timeout", None),
        env_var="ANALYZER_TIMEOUT",
        file_config=config,
        packaged_default=_DEFAULT_SUBPROCESS_TIMEOUT,
        cast=int,
    )
    return value


def _apply_environment_default(
    args: argparse.Namespace, config: dict[str, Any]
) -> None:
    """Fill --env via the centralized resolver when not passed.

    No-op for subcommands without an --env flag. Precedence:
    --env > FABRIC_ENVIRONMENT > config file > "" (no default environment).
    """
    if not hasattr(args, "environment"):
        return
    value, _origin = resolve_setting(
        "environment",
        cli_value=args.environment or None,
        env_var="FABRIC_ENVIRONMENT",
        file_config=config,
        packaged_default="",
    )
    args.environment = value


def _telemetry_enabled(args: argparse.Namespace) -> bool:
    """Return True when telemetry should be streamed for this invocation."""
    if args.telemetry is False:
        return False
    if args.telemetry is True:
        return True
    return os.getenv("ENABLE_EVENTHOUSE_LOGGING", "").lower() == "true"


def _git_command_output(cmd: list[str]) -> str:
    """Run a local git command and return trimmed stdout, or "" on any failure."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def _git_context() -> dict[str, str]:
    """Return repository/branch/commit/actor context from GitHub Actions or git CLI.

    Falls back to local git for branch, commit, and actor (via
    ``git config user.email``) so telemetry still carries useful context on
    local runs and self-hosted runners where ``GITHUB_*`` vars are empty.
    """
    ctx = {
        "repository": os.getenv("GITHUB_REPOSITORY", ""),
        "branch": os.getenv("GITHUB_REF_NAME", ""),
        "commit": os.getenv("GITHUB_SHA", ""),
        "actor": os.getenv("GITHUB_ACTOR", ""),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", ""),
    }
    if not ctx["commit"]:
        ctx["commit"] = _git_command_output(["git", "rev-parse", "HEAD"])
    if not ctx["branch"]:
        ctx["branch"] = _git_command_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if not ctx["actor"]:
        ctx["actor"] = _git_command_output(["git", "config", "user.email"])
    return ctx


def _detect_origin() -> str:
    """Return which CI system (if any) this run is executing under.

    Checked in a fixed order so a run with multiple CI env vars set (e.g. a
    CI system that shells out to another) resolves deterministically.
    """
    if os.environ.get("GITHUB_ACTIONS"):
        return "github-actions"
    if os.environ.get("GITLAB_CI"):
        return "gitlab-ci"
    if os.environ.get("CIRCLECI"):
        return "circleci"
    if os.environ.get("AZURE_DEVOPS"):
        return "azure-devops"
    return "local"


def _current_os_platform() -> str:
    return sys.platform


def _machine_context() -> dict[str, str]:
    """Return non-sensitive machine context: platform, python, fab-test version.

    A field is simply omitted (rather than failing the whole payload) if it
    cannot be determined.
    """
    context: dict[str, str] = {"fab_test_version": _FAB_TEST_VERSION}
    with contextlib.suppress(Exception):
        context["platform"] = _current_os_platform()
    with contextlib.suppress(Exception):
        context["python_version"] = platform.python_version()
    return context


def _redact_pii(value: str) -> str:
    """Redact a value that looks like PII (e.g. an email address).

    Hashes rather than drops the value so it stays usable for correlating
    runs by the same actor without exposing the raw email in telemetry.
    """
    if "@" in value:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        return f"sha256:{digest}"
    return value


def _build_telemetry_payload(
    analyzer: str,
    artifact: Path,
    envelope: dict[str, Any],
    environment: str,
) -> dict[str, Any]:
    """Build a telemetry payload for an analyzer/artifact run."""
    errors, warnings = _severity_counts(envelope.get("findings", []))
    ctx = _git_context()
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "artifact_name": artifact.stem,
        "artifact_type": artifact.suffix.lstrip("."),
        "commit_sha": ctx.get("commit", ""),
        "workflow_run_id": ctx.get("workflow_run_id", ""),
        "repository": ctx.get("repository", ""),
        "actor": _redact_pii(ctx.get("actor", "")),
        "branch": ctx.get("branch", ""),
        "origin": _detect_origin(),
        "environment": environment,
        "analyzer": analyzer,
        "status": envelope.get("status", "unknown"),
        "error_count": errors,
        "warning_count": warnings,
        "findings_count": len(envelope.get("findings", [])),
        "results": envelope,
        **_machine_context(),
    }


_REQUIRED_TELEMETRY_FIELDS = ("analyzer", "artifact_name", "status", "timestamp")


def _validate_telemetry_payload(
    payload: dict[str, Any], output_format: str = "text"
) -> dict[str, Any] | None:
    """Validate a telemetry payload before sending.

    Drops any optional field that isn't JSON-serializable and returns the
    cleaned payload. Returns None (and logs a warning) if a required field
    is missing, so the caller can skip the record without failing the run.
    """
    missing = [f for f in _REQUIRED_TELEMETRY_FIELDS if not payload.get(f)]
    if missing:
        narrate(
            f"::warning::Telemetry payload missing required field(s): "
            f"{', '.join(missing)}; skipping",
            output_format=output_format,
        )
        return None

    cleaned = {}
    for key, value in payload.items():
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            continue
        cleaned[key] = value
    return cleaned


def _send_telemetry(
    analyzer: str,
    artifact: Path,
    envelope: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    """Send a telemetry record if enabled. Telemetry failure is non-blocking."""
    if not _telemetry_enabled(args):
        return

    output_format = getattr(args, "output_format", "text")
    table = (
        "fabric_dynamic_analysis"
        if analyzer == "pql_test"
        else "fabric_static_analysis"
    )
    payload = _build_telemetry_payload(
        analyzer,
        artifact,
        envelope,
        getattr(args, "environment", "") or os.getenv("FABRIC_ENVIRONMENT", ""),
    )
    validated = _validate_telemetry_payload(payload, output_format)
    if validated is None:
        return
    try:
        publish_analyzer_telemetry(table, validated, force=True)
    except Exception as exc:
        narrate(
            f"::warning::Telemetry failed for {artifact.stem}: {exc}",
            output_format=output_format,
        )


def _artifact_exit_code(
    proc_returncode: int,
    envelope: dict[str, Any] | None,
) -> int:
    """Return the fab-test exit code for a single artifact run.

    Warnings do not fail the build. Errors and tool crashes do.
    """
    if envelope is None:
        return 1 if proc_returncode != 0 else 0
    errors, warnings = _severity_counts(envelope.get("findings", []))
    if errors > 0:
        return 1
    if proc_returncode != 0 and warnings == 0:
        # Tool crashed or could not run; propagate the failure.
        return 1
    return 0


@dataclass
class _RunContext:
    """Per-run state shared across every artifact in one analyzer invocation."""

    in_ci: bool
    sub_env: dict[str, str]
    timeout: int
    manifest: RunManifest | None = None


def _run_one_artifact(
    name: str,
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
    ctx: _RunContext,
    index: int,
    total: int,
) -> tuple[str, int]:
    """Run one analyzer against one artifact. Returns (stem, exit_code)."""
    output_format = getattr(args, "output_format", "text")
    display_name = "." if _is_repository_scoped(name) else artifact.stem
    if total > 1:
        if ctx.in_ci:
            narrate(
                f"::notice::fab-test {name}: artifact {index} of {total} ({display_name})",
                output_format=output_format,
            )
        else:
            narrate(f"  artifact {index} of {total}", output_format=output_format)
    narrate(f"\n  ▶ fab-test {name}  →  {display_name}", output_format=output_format)
    cmd = _build_command(name, artifact, args, output_dir)
    # Under --format json, capture the child's stdout instead of inheriting it
    # (it would otherwise land in the middle of the JSON document) and
    # re-emit it as narration. --format text keeps today's direct inheritance
    # so there is no added buffering latency.
    capture_stdout = output_format == "json"

    def _reemit(text: str | None) -> None:
        if not text:
            return
        for line in text.splitlines():
            clean = _clean_annotation(line)
            if clean.strip():
                narrate(f"  {clean}", output_format=output_format)

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture_stdout else None,
            stderr=None if ctx.in_ci else subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ctx.sub_env,
            timeout=ctx.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        narrate(
            f"  ⏰ fab-test {name}: timed out after {ctx.timeout}s for {display_name}",
            output_format=output_format,
        )
        if capture_stdout:
            _reemit(exc.stdout)
        if ctx.manifest is not None:
            ctx.manifest.record_artifact(
                name, display_name, "timeout", None, 0, 0,
                detail=f"exceeded {ctx.timeout}s timeout",
            )
        return (display_name, 1)

    if capture_stdout:
        _reemit(proc.stdout)

    if not ctx.in_ci and proc.stderr:
        for line in proc.stderr.splitlines():
            clean = _clean_annotation(line)
            if clean.strip():
                narrate(f"  {clean}", output_format=output_format)

    # Read the envelope and apply the error/warning threshold ourselves so
    # warnings never fail the build.
    envelope = _read_artifact_envelope(output_dir, name, artifact.stem)
    if envelope is None and proc.returncode == 0:
        envelope = {
            "status": "passed",
            "findings": [],
            "artifact_path": str(artifact),
            "analyzer": name,
        }
    elif envelope is None:
        envelope = {
            "status": "failed",
            "findings": [],
            "artifact_path": str(artifact),
            "analyzer": name,
        }

    artifact_code = _artifact_exit_code(proc.returncode, envelope)

    errors, warnings = _severity_counts(envelope.get("findings", []))
    if ctx.in_ci:
        emit_workflow_annotations(envelope)
    if warnings > 0:
        emit_pr_review_comments(envelope, str(artifact))
    _send_telemetry(name, artifact, envelope, args)

    if ctx.manifest is not None:
        envelope_path = output_dir / name / artifact.stem / "envelope.json"
        ctx.manifest.record_artifact(
            name,
            artifact.stem,
            envelope.get("status", "unknown"),
            str(envelope_path) if envelope_path.exists() else None,
            errors,
            warnings,
        )

    return (artifact.stem, artifact_code)


def _manifest_target(args: argparse.Namespace) -> dict[str, Any] | None:
    """Return the resolved target as a plain dict for `run.json`, or None."""
    target = getattr(args, "resolved_target", None)
    if target is None:
        return None
    return target.as_dict(getattr(args, "workspace_id", "") or "")


def _resolve_workspace_target(args: argparse.Namespace) -> int | None:
    """Turn a workspace *name* into the ID the analyzers accept.

    Returns an exit code on failure, or None when there is nothing to do
    -- which is the overwhelmingly common case, so the Fabric client is
    imported and built only when a workspace was actually named. A GUID
    short-circuits inside `resolve_workspace_id` without a round trip.
    """
    target = _target_of(args)
    if target is not None and target.workspace:
        name = target.workspace
    elif not getattr(args, "workspace_id", ""):
        name = (getattr(args, "file_config", None) or {}).get("workspace", "")
    else:
        name = ""
    if not name:
        return None

    from .playwright_validation.fabric_service_client import build_fabric_service_client
    from .playwright_validation.resolver import (
        AmbiguousWorkspaceError,
        ServiceResolutionError,
        WorkspaceNotFoundError,
    )

    try:
        client = build_fabric_service_client(env_file=getattr(args, "playwright_env_file", None))
        args.workspace_id = resolve_workspace_id(client, name)
    except AmbiguousWorkspaceError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 2
    except WorkspaceNotFoundError as exc:
        print(f"  ✗ fab-test: {exc}", file=sys.stderr)
        return 1
    except ServiceResolutionError as exc:
        print(f"  ✗ fab-test: could not resolve workspace '{name}': {exc}", file=sys.stderr)
        return 1
    return None


# One definition, shared with fab_test_summary, so a second discovery pass
# cannot drift back to reading args.artifact directly -- which it did, and
# which crashed `fab-test all --artifact X`.
_target_of = target_from_args


def _discover_for(name: str, args: argparse.Namespace, glob: str) -> list[Path]:
    """Return the artifacts ``name`` will run against.

    Two analyzers do not discover at all: a repository-scoped one runs once
    against the repo metadata, and impact-manifest-driven Playwright
    validates a service-resolved set regardless of what exists locally.
    """
    if _is_repository_scoped(name):
        return [Path(".")]
    if name == "playwright" and getattr(args, "impact_manifest", None):
        return [Path(".")]
    return _discover(Path(args.artifact_dir), glob, _target_of(args))


def _report_no_artifacts(
    name: str, glob: str, args: argparse.Namespace, *, emit_own_json: bool
) -> int:
    """Narrate an empty discovery. Always exits 0 -- nothing matched is not a failure."""
    output_format = getattr(args, "output_format", "text")
    target = _target_of(args)
    if target is not None and target.path is not None:
        # A path target named a specific location, so reporting what the
        # scan of --artifact-dir turned up would answer a question the
        # caller did not ask.
        narrate(
            f"  ⚠ fab-test {name}: no {glob} artifact at {target.path}",
            output_format=output_format,
        )
    else:
        narrate(
            f"  ⚠ fab-test {name}: no {glob} artifacts or .pbip projects found under "
            f"{Path(args.artifact_dir)}",
            output_format=output_format,
        )
    if emit_own_json:
        print(json.dumps({"analyzer": name, "artifacts": []}, indent=2))
    return 0


def _report_dry_run(
    name: str,
    description: str,
    artifacts: list[Path],
    args: argparse.Namespace,
    *,
    emit_own_json: bool,
) -> int:
    """Narrate the plan without running anything. Always exits 0."""
    output_format = getattr(args, "output_format", "text")
    artifact_dir = Path(args.artifact_dir)
    narrate(
        f"\nfab-test {name} ({description}) — dry run, "
        f"{len(artifacts)} artifact(s):",
        output_format=output_format,
    )
    resolved = _manifest_target(args)
    if resolved:
        narrate(
            f"  target: {resolved['raw']} → scope {resolved['scope']}"
            + (f", workspace {resolved['workspace_id']}" if resolved["workspace_id"] else ""),
            output_format=output_format,
        )
    pbip_sources = _discover_pbip_sources(artifact_dir)
    for a in artifacts:
        analyzers = ", ".join(_applicable_analyzers(a)) or "none"
        source = pbip_sources.get(a)
        source_note = f"  [from {source.name}]" if source else ""
        narrate(
            f"  • {a.name}  (analyzers: {analyzers}){source_note}",
            output_format=output_format,
        )
    if _telemetry_enabled(args):
        environment = getattr(args, "environment", "") or os.getenv("FABRIC_ENVIRONMENT", "")
        for a in artifacts:
            preview = _build_telemetry_payload(
                name, a, {"status": "dry-run", "findings": []}, environment
            )
            narrate("\n  Telemetry preview (not sent):", output_format=output_format)
            narrate(json.dumps(preview, indent=2), output_format=output_format)
    if emit_own_json:
        print(
            json.dumps(
                {
                    "analyzer": name,
                    "dry_run": True,
                    "target": resolved,
                    "artifacts": [a.name for a in artifacts],
                },
                indent=2,
            )
        )
    return 0


def _preflight(
    name: str,
    args: argparse.Namespace,
    artifacts: list[Path],
    manifest: RunManifest | None,
) -> int | None:
    """Return an exit code when a prerequisite is missing, else None.

    Two checks, reported identically on purpose: a missing binary and a
    missing Desktop session are the same class of problem to the caller,
    and giving them different shapes would imply a difference that is not
    there.
    """
    output_format = getattr(args, "output_format", "text")

    def _fail(message: str, exit_code: int) -> int:
        narrate(
            f"\n  ✗ fab-test {name}: missing prerequisite\n  {message}\n",
            output_format=output_format,
        )
        if manifest is not None:
            manifest.record_artifact(name, "*", "preflight_failed", None, 0, 0, detail=message)
        return exit_code

    preflight_err = _preflight_error(name, args)
    if preflight_err:
        return _fail(*preflight_err)

    # A local/ target states the Desktop binding, so a missing instance is a
    # prerequisite failure rather than the silent fall-through to remote XMLA
    # that an unset --workspace-id gets.
    target = _target_of(args)
    if target is not None and target.scope == "desktop":
        unbound = [a for a in artifacts if _bound_desktop_instance(a) is None]
        if unbound:
            return _fail(
                f"no running Power BI Desktop instance has "
                f"{', '.join(a.name for a in unbound)} open.\n"
                "  Open the .pbip in Power BI Desktop, or drop the 'local/' "
                "prefix to run against a workspace.",
                127,
            )
    return None


def _analyzer_sub_env(args: argparse.Namespace, output_format: str) -> dict[str, str]:
    """Build the subprocess environment the analyzer wrappers read.

    These variables are how a setting reaches a wrapper without every
    command builder growing an argument for each one.
    """
    sub_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    verbosity = _verbosity_env(args)
    if verbosity:
        sub_env["ANALYZER_VERBOSITY"] = verbosity
    if output_format == "json":
        sub_env["ANALYZER_OUTPUT_MODE"] = "json"
    if _resolve_report(args):
        sub_env["ANALYZER_REPORT"] = "1"
    return sub_env


def _run_analyzer(
    name: str,
    args: argparse.Namespace,
    output_dir: Path,
    manifest: RunManifest | None = None,
) -> int:
    """Run one analyzer against all matching artifacts.

    Five phases in order: discover, report an empty result, report a dry
    run, preflight, execute. The first four each short-circuit with their
    own exit code, which is what keeps this readable as a sequence rather
    than a nest.
    """
    glob, description = _ANALYZER_REGISTRY[name]
    output_format = getattr(args, "output_format", "text")
    # `all` emits its own aggregate JSON via _print_all_summary; a standalone
    # analyzer must emit its own so stdout is never empty under --format json.
    emit_own_json = output_format == "json" and getattr(args, "analyzer", None) not in (
        "all",
        "local",
    )

    artifacts = _discover_for(name, args, glob)
    if not artifacts:
        return _report_no_artifacts(name, glob, args, emit_own_json=emit_own_json)
    if args.dry_run:
        return _report_dry_run(name, description, artifacts, args, emit_own_json=emit_own_json)

    preflight_exit_code = _preflight(name, args, artifacts, manifest)
    if preflight_exit_code is not None:
        return preflight_exit_code

    verbosity = _verbosity_env(args)
    ctx = _RunContext(
        in_ci=_is_ci(),
        sub_env=_analyzer_sub_env(args, output_format),
        timeout=_resolve_timeout(args),
        manifest=manifest,
    )
    total = len(artifacts)

    def _run(index_artifact: tuple[int, Path]) -> tuple[str, int]:
        index, artifact = index_artifact
        return _run_one_artifact(name, artifact, args, output_dir, ctx, index, total)

    indexed = list(enumerate(artifacts, start=1))
    jobs = max(1, getattr(args, "jobs", 1) or 1)
    if jobs > 1 and total > 1:
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            results = list(executor.map(_run, indexed))
    else:
        results = [_run(pair) for pair in indexed]

    return _print_summary(
        name,
        results,
        output_dir=output_dir,
        verbosity=verbosity,
        output_format=output_format,
    )


def _add_common_flags(
    parser: argparse.ArgumentParser, *, artifact_dir_default: Path = ARTIFACT_ROOT
) -> None:
    parser.add_argument(
        "--artifact-dir",
        default=str(_PYPROJECT_CONFIG.get("artifact_dir", artifact_dir_default)),
        metavar="DIR",
        help=f"Root for .fabric artifacts (default: {artifact_dir_default})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_PYPROJECT_CONFIG.get("output_dir", RESULTS_ROOT)),
        metavar="DIR",
        help=f"Root for result envelopes (default: {RESULTS_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and list matching artifacts without running any analyzer",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="TARGET",
        help=(
            "Artifact to analyze: a path (./src/Sales.SemanticModel), a name "
            "(Sales or Sales.SemanticModel), local/NAME for a running Power BI "
            "Desktop instance, or WORKSPACE.Workspace/NAME.Type for a deployed item"
        ),
    )
    parser.add_argument(
        "--artifact",
        default=None,
        metavar="STEM",
        help="Deprecated alias for the TARGET argument; only analyze this stem",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "Per-artifact subprocess timeout in seconds "
            f"[env: ANALYZER_TIMEOUT, default: {_DEFAULT_SUBPROCESS_TIMEOUT}]"
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=_PYPROJECT_CONFIG.get("jobs", 1),
        metavar="N",
        help="Run up to N artifacts in parallel for the same analyzer (default: 1)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "Increase output verbosity (one -v for per-finding detail, "
            "two -v for command + stdout/stderr; same as ANALYZER_VERBOSITY)"
        ),
    )
    report_group = parser.add_mutually_exclusive_group()
    report_group.add_argument(
        "--report",
        action="store_true",
        dest="report",
        default=None,
        help="Write a readable HTML report beside each result envelope",
    )
    report_group.add_argument(
        "--no-report",
        action="store_false",
        dest="report",
        help="Suppress HTML report generation (the default)",
    )
    telemetry_group = parser.add_mutually_exclusive_group()
    telemetry_group.add_argument(
        "--telemetry",
        action="store_true",
        dest="telemetry",
        default=None,
        help="Stream telemetry to Eventhouse when EVENTHOUSE_LOGGING is enabled",
    )
    telemetry_group.add_argument(
        "--no-telemetry",
        action="store_false",
        dest="telemetry",
        help="Suppress telemetry even when EVENTHOUSE_LOGGING is enabled",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for aggregate summaries (default: text)",
    )


_SUBCOMMAND_ALIASES = {
    "pql-test": "pql_test",
    "pql_test": "pql_test",
    "pql-lint": "pql_lint",
    "pql_lint": "pql_lint",
    "playwright_impact": "playwright-impact",
}

# Canonical (hyphenated, displayed) subcommand name -> internal registry key,
# for the handful where they diverge. Result directories (analyzer-results/
# <key>/...) stay on the registry key so historical results remain readable.
_CANONICAL_TO_REGISTRY_KEY = {
    "pql-test": "pql_test",
    "pql-lint": "pql_lint",
}
_REGISTRY_KEY_TO_CANONICAL = {v: k for k, v in _CANONICAL_TO_REGISTRY_KEY.items()}


def _canonical_name(registry_key: str) -> str:
    """Return the canonical (hyphenated) display name for a registry key."""
    return _REGISTRY_KEY_TO_CANONICAL.get(registry_key, registry_key)


def _aliases_for(registry_key: str, canonical: str) -> list[str]:
    """Return every other accepted spelling for ``registry_key``."""
    return sorted(
        {
            alias
            for alias, key in _SUBCOMMAND_ALIASES.items()
            if key == registry_key and alias != canonical
        }
    )


_COMMON_COMPLETION_FLAGS = (
    "--artifact-dir --output-dir --dry-run --artifact --timeout --jobs "
    "-v --verbose --telemetry --no-telemetry --format --help"
)


def _completion_subcommands() -> str:
    return " ".join(
        (
            *(_canonical_name(name) for name in _ANALYZER_REGISTRY),
            "all",
            "clean-tools",
            "help",
        )
    )


def _generate_completion_script(shell: str) -> str:
    """Return a shell completion script that also completes artifact stems.

    Artifact stems are looked up from ``.fabric/artifacts`` at *completion
    time* in the user's shell (not baked in here), so the list always
    reflects whatever directory they are tab-completing from.
    """
    subcommands = _completion_subcommands()
    if shell == "bash":
        return f"""\
_fab_test_completions() {{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    if [[ ${{COMP_CWORD}} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "{subcommands} --version --print-completion --help" -- "${{cur}}") )
        return 0
    fi

    if [[ "${{prev}}" == "--artifact" ]]; then
        local dir=".fabric/artifacts"
        if [[ -d "${{dir}}" ]]; then
            local stems
            stems=$(for f in "${{dir}}"/*; do basename "$f" | sed 's/\\.[^.]*$//'; done | sort -u)
            COMPREPLY=( $(compgen -W "${{stems}}" -- "${{cur}}") )
        fi
        return 0
    fi

    if [[ "${{cur}}" == -* ]]; then
        COMPREPLY=( $(compgen -W "{_COMMON_COMPLETION_FLAGS}" -- "${{cur}}") )
    fi
}}
complete -F _fab_test_completions fab-test
"""
    return f"""\
#compdef fab-test

_fab_test() {{
    local -a subcommands
    subcommands=({subcommands})

    if (( CURRENT == 2 )); then
        compadd -a subcommands
        compadd -- --version --print-completion --help
        return
    fi

    if [[ "${{words[CURRENT-1]}}" == "--artifact" ]]; then
        local dir=".fabric/artifacts"
        if [[ -d "${{dir}}" ]]; then
            local -a stems
            stems=($(for f in "${{dir}}"/*(N); do basename "$f" | sed 's/\\.[^.]*$//'; done | sort -u))
            compadd -a stems
        fi
        return
    fi

    compadd -- {_COMMON_COMPLETION_FLAGS}
}}

_fab_test
"""


class _PrintCompletionAction(argparse.Action):
    """argparse action that prints a completion script and exits, like --version."""

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ARG002 - argparse Action API
        print(_generate_completion_script(values))
        parser.exit()


class _FabTestParser(argparse.ArgumentParser):
    """Parser whose unknown-analyzer error names only the advertised commands.

    argparse renders `invalid choice` straight from the subparser table,
    which holds every alias spelling *and* the hidden analyzers — exactly
    the names the help listing works to keep off the surface (see
    HIDDEN_ANALYZERS). A wrong first word would otherwise be the one place
    that leaks them. The rewrite lists canonical spellings only, and points
    a near miss at what the caller probably meant.
    """

    #: Canonical, visible subcommand names, in the order they were declared.
    advertised_subcommands: tuple[str, ...] = ()
    #: Every accepted spelling, aliases and hidden names included, used only
    #: to match a typo — answering a direct question is not advertising.
    accepted_subcommands: tuple[str, ...] = ()

    def error(self, message: str):
        match = re.match(r"argument ANALYZER: invalid choice: '([^']*)'", message)
        if match and self.advertised_subcommands:
            message = self._unknown_analyzer_message(match.group(1))
        super().error(message)

    def _unknown_analyzer_message(self, name: str) -> str:
        close = difflib.get_close_matches(name, self.accepted_subcommands, n=1, cutoff=0.6)
        suggestion = ""
        if close:
            canonical = _canonical_name(_SUBCOMMAND_ALIASES.get(close[0], close[0]))
            suggestion = f"did you mean '{self.prog} {canonical}'? "
        return (
            f"unknown analyzer '{name}' -- {suggestion}"
            f"choose from {', '.join(self.advertised_subcommands)}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = _FabTestParser(
        prog="fab-test",
        description=(
            "Run Fabric artifact analyzers locally.\n\n"
            "fab-test tests your .fabric artifacts — it is NOT pytest.\n"
            "  pytest -m bpa      tests the BPA wrapper (always green)\n"
            "  fab-test bpa       runs BPA against your actual .fabric artifacts"
        ),
        epilog=(
            "Exit codes:\n"
            "  0    All artifacts passed (warnings do not fail the build)\n"
            "  1    An analyzer found error-level findings, or the analyzer process crashed\n"
            "  2    Invalid CLI arguments (no analyzer was invoked)\n"
            "  126  Analyzer unsupported on this platform (see message for the supported OS)\n"
            "  127  Required external tool could not be resolved (see message for the fix)\n\n"
            f"Version: {_FAB_TEST_VERSION} | "
            "Docs: https://github.com/kerski/fabric-ci-cd-dataops/blob/main/docs/QUICK-VALIDATION.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {_FAB_TEST_VERSION}",
        help="Show fab-test version and exit",
    )
    parser.add_argument(
        "--print-completion",
        choices=["bash", "zsh"],
        action=_PrintCompletionAction,
        help="Print a shell completion script for bash or zsh and exit",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=f"Path to a config file (default: discover {CONFIG_FILENAME} at the repository root)",
    )

    subs = parser.add_subparsers(dest="analyzer", metavar="ANALYZER")
    subs.required = True

    # --- bpa ---
    bpa_p = subs.add_parser(
        "bpa",
        help="Tabular Editor Best Practice Analyzer (SemanticModel artifacts)",
    )
    _add_common_flags(bpa_p)
    bpa_p.add_argument(
        "--tabular-editor-path",
        default=None,
        dest="tabular_editor_path",
        metavar="PATH",
        help=(
            "Path to TabularEditor.exe "
            f"[env: TABULAR_EDITOR_PATH, default: {_DEFAULT_TE_PATH}]"
        ),
    )
    bpa_p.add_argument(
        "--bpa-rules-path",
        default=_DEFAULT_BPA_RULES,
        dest="bpa_rules_path",
        metavar="PATH",
        help=f"BPA rules JSON file [default: {_DEFAULT_BPA_RULES}]",
    )

    # --- pbir ---
    pbir_p = subs.add_parser(
        "pbir",
        help="PBIR Inspector — static report analysis (Report artifacts)",
    )
    _add_common_flags(pbir_p)
    pbir_p.add_argument(
        "--inspector-path",
        default=None,
        dest="inspector_path",
        metavar="PATH",
        help=(
            "Path to PBIR Inspector binary "
            f"[env: PBIR_INSPECTOR_PATH, default: {_DEFAULT_INSPECTOR_PATH}]"
        ),
    )
    pbir_p.add_argument(
        "--rules-path",
        default=_DEFAULT_PBIR_RULES,
        dest="rules_path",
        metavar="PATH",
        help=f"PBIR Inspector rules JSON [default: {_DEFAULT_PBIR_RULES}]",
    )

    # --- pql-test ---
    pql_test_p = subs.add_parser(
        "pql-test",
        aliases=["pql_test"],
        help="pql-test DAX/PQL test runner (SemanticModel artifacts)",
    )
    _add_common_flags(pql_test_p)
    pql_test_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        type=_guid_type,
        help="Fabric workspace ID [env: FABRIC_WORKSPACE_ID]",
    )
    pql_test_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
        help="Environment label (e.g. DEV, PROD, ANY) [env: FABRIC_ENVIRONMENT]",
    )

    # --- pql-lint ---
    pql_lint_p = subs.add_parser(
        "pql-lint",
        aliases=["pql_lint"],
        # Omitting `help` (rather than passing argparse.SUPPRESS, which
        # renders a literal "==SUPPRESS==" line) keeps this out of the
        # subcommand listing while leaving it fully invocable. See
        # HIDDEN_ANALYZERS. Its own --help still works via `description`.
        description="pqlint Power Query linter (SemanticModel artifacts)",
    )
    _add_common_flags(pql_lint_p)

    # --- playwright ---
    playwright_p = subs.add_parser(
        "playwright",
        help="Playwright visual/error validation (Report artifacts)",
    )
    _add_common_flags(playwright_p)
    playwright_p.add_argument(
        "--env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to .env file with report and credential settings",
    )
    playwright_p.add_argument(
        "--impact-manifest",
        default=None,
        dest="impact_manifest",
        metavar="PATH",
        help="Path to impacted-report manifest JSON",
    )
    playwright_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        type=_guid_type,
        help="Fabric workspace ID [env: FABRIC_WORKSPACE_ID]",
    )
    playwright_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
        help="Environment label (e.g. DEV, PROD, ANY) [env: FABRIC_ENVIRONMENT]",
    )
    playwright_p.add_argument(
        "--dataset-id",
        default="",
        dest="dataset_id",
        metavar="ID",
        help="Semantic model / dataset ID override",
    )

    # --- playwright-impact ---
    impact_p = subs.add_parser(
        "playwright-impact",
        aliases=["playwright_impact"],
        help="Build impacted-report manifest for Playwright validation",
    )
    _add_common_flags(impact_p)
    impact_p.add_argument(
        "--changed-artifacts",
        default="changed-artifacts.json",
        dest="changed_artifacts",
        metavar="PATH",
        help="Path to changed-artifacts.json (default: changed-artifacts.json)",
    )
    impact_p.add_argument(
        "--output",
        default=None,
        dest="output_path",
        metavar="PATH",
        help="Path for the JSON impact manifest",
    )
    impact_p.add_argument(
        "--env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to .env file with service principal credentials",
    )
    impact_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        type=_guid_type,
        help="Fabric workspace ID [env: FABRIC_WORKSPACE_ID]",
    )
    impact_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
        help="Environment label (e.g. DEV, PROD, ANY) [env: FABRIC_ENVIRONMENT]",
    )

    # --- dependencies ---
    deps_p = subs.add_parser(
        "dependencies",
        help="Discover reports that depend on a deployed semantic model",
    )
    _add_common_flags(deps_p)
    deps_p.add_argument(
        "--semantic-model",
        required=True,
        dest="semantic_model",
        metavar="NAME",
        help="Name of the deployed semantic model",
    )
    deps_p.add_argument(
        "--env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to .env file with service principal credentials",
    )
    deps_p.add_argument(
        "--output",
        default=None,
        dest="output_path",
        metavar="PATH",
        help="Path to write JSON dependency manifest",
    )
    deps_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        type=_guid_type,
        help="Fabric workspace ID [env: FABRIC_WORKSPACE_ID]",
    )
    deps_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
        help="Environment label (e.g. DEV, PROD, ANY) [env: FABRIC_ENVIRONMENT]",
    )

    # --- all ---
    all_p = subs.add_parser("all", help="Run all analyzers in sequence")
    _add_common_flags(all_p)
    all_p.add_argument(
        "--tabular-editor-path",
        default=None,
        dest="tabular_editor_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--bpa-rules-path",
        default=_DEFAULT_BPA_RULES,
        dest="bpa_rules_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--inspector-path",
        default=None,
        dest="inspector_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--rules-path",
        default=_DEFAULT_PBIR_RULES,
        dest="rules_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        type=_guid_type,
    )
    all_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
    )
    all_p.add_argument(
        "--playwright-env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to .env file for Playwright validation",
    )

    # --- auth ---
    auth_p = subs.add_parser(
        "auth",
        help="Report or acquire Fabric credentials (fab-test stores none of its own)",
    )
    auth_subs = auth_p.add_subparsers(dest="auth_command", metavar="COMMAND")
    auth_subs.required = True
    auth_status_p = auth_subs.add_parser(
        "status",
        help="Show which identity fab-test would use, verifying it for real",
    )
    auth_status_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        help="Check whether this workspace is reachable [env: FABRIC_WORKSPACE_ID]",
    )
    auth_status_p.add_argument(
        "--env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to a .env file holding credentials",
    )
    auth_status_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format (default: text)",
    )
    auth_login_p = auth_subs.add_parser(
        "login",
        help="Delegate sign-in to the tool that owns the credential",
    )
    auth_login_p.add_argument(
        # Deliberately NOT --environment: in fab-test, --env is the test
        # environment label (DEV/PROD). pql-test spells the Azure cloud
        # --environment, and merging the two names would be a trap.
        "--cloud",
        default="public",
        choices=["public", "USGov", "USGovHigh", "USGovDoD", "Germany", "China"],
        help="Azure cloud to sign in to (default: public)",
    )
    auth_login_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format (default: text)",
    )

    # --- local ---
    local_p = subs.add_parser(
        "local",
        help=(
            # Deliberately not enumerated: the bundle includes the hidden
            # pql-lint, and naming only the visible members would be
            # incomplete rather than merely brief. `local --dry-run` lists
            # exactly what would run.
            "Run the local analyzer bundle "
            "against every discovered .pbip project -- no cloud required"
        ),
    )
    _add_common_flags(local_p, artifact_dir_default=REPO_ROOT)
    local_p.add_argument(
        "--tabular-editor-path", default=None, dest="tabular_editor_path", metavar="PATH",
    )
    local_p.add_argument(
        "--bpa-rules-path", default=_DEFAULT_BPA_RULES, dest="bpa_rules_path", metavar="PATH",
    )
    local_p.add_argument(
        "--inspector-path", default=None, dest="inspector_path", metavar="PATH",
    )
    local_p.add_argument(
        "--rules-path", default=_DEFAULT_PBIR_RULES, dest="rules_path", metavar="PATH",
    )

    # --- clean-tools ---
    clean_tools_p = subs.add_parser(
        "clean-tools",
        help="Remove or inspect the .fab-test-tools downloaded-binary cache",
    )
    clean_tools_p.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be removed without deleting anything",
    )

    # --- doctor ---
    doctor_p = subs.add_parser(
        "doctor",
        help="Check whether each analyzer's prerequisites are ready to run",
    )
    doctor_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the readiness report (default: text)",
    )
    doctor_p.add_argument(
        "--analyzer",
        dest="analyzer_filter",
        default=None,
        metavar="NAME",
        help="Only check this analyzer",
    )
    doctor_p.add_argument(
        "--local",
        action="store_true",
        help="Check prerequisites for the local Desktop workflow (fab-test local)",
    )

    # --- config ---
    config_p = subs.add_parser(
        "config",
        help="Show effective configuration and where each setting came from",
    )
    config_p.add_argument(
        "--show",
        action="store_true",
        help="Print every effective setting with its value and origin",
    )
    config_p.add_argument(
        "--validate",
        action="store_true",
        help="Confirm the config file's keys and types are valid, and exit",
    )
    config_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the settings report (default: text)",
    )

    # --- init ---
    init_p = subs.add_parser(
        "init",
        help="Scaffold a commented fab-test.yml and .env.example",
    )
    init_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the scaffold report (default: text)",
    )
    init_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing anything",
    )

    # --- list ---
    list_p = subs.add_parser(
        "list",
        help="List available analyzers with their artifact glob, matched count, and required tool",
    )
    list_p.add_argument(
        "--artifact-dir",
        default=str(_PYPROJECT_CONFIG.get("artifact_dir", ARTIFACT_ROOT)),
        metavar="DIR",
        help=f"Root for .fabric artifacts (default: {ARTIFACT_ROOT})",
    )
    list_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the capability report (default: text)",
    )

    # --- explain ---
    explain_p = subs.add_parser(
        "explain",
        help="Show the resolved command for one analyzer without running it",
    )
    explain_p.add_argument(
        "analyzer_name",
        metavar="ANALYZER",
        help="Analyzer to explain (e.g. bpa, pbir, pql_test)",
    )
    explain_p.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="TARGET",
        help="Optional target to resolve and explain (e.g. local/Sales)",
    )
    explain_p.add_argument(
        "--artifact-dir",
        default=str(_PYPROJECT_CONFIG.get("artifact_dir", ARTIFACT_ROOT)),
        metavar="DIR",
        help=f"Root for .fabric artifacts (default: {ARTIFACT_ROOT})",
    )
    explain_p.add_argument(
        "--output-dir",
        default=str(_PYPROJECT_CONFIG.get("output_dir", RESULTS_ROOT)),
        metavar="DIR",
        help=f"Root for result envelopes (default: {RESULTS_ROOT})",
    )
    explain_p.add_argument(
        "--artifact",
        default=None,
        metavar="STEM",
        help="Explain the command for the artifact whose stem matches STEM",
    )
    explain_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the explanation (default: text)",
    )

    # --- help ---
    help_p = subs.add_parser(
        "help",
        help="Show this help, or one analyzer's help (fab-test help bpa)",
    )
    help_p.add_argument(
        "help_topic",
        nargs="?",
        default=None,
        metavar="ANALYZER",
        help="Analyzer or command to show help for (e.g. bpa, doctor)",
    )

    # Read back from the subparser table rather than maintained by hand, so
    # a new subcommand cannot be added without the error message learning
    # about it.
    accepted = tuple(subs.choices)
    parser.accepted_subcommands = accepted
    parser.advertised_subcommands = tuple(
        dict.fromkeys(
            _canonical_name(_SUBCOMMAND_ALIASES.get(name, name))
            for name in accepted
            if _SUBCOMMAND_ALIASES.get(name, name) not in _HIDDEN_ANALYZERS
        )
    )

    return parser


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
    metadata_path = REPO_ROOT / ".github" / "metadata" / "analyzers.json"
    return _load_fab_test_all_analyzers(metadata_path)


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
# output_dir: analyzer-results      # root for result envelopes and the run manifest
# jobs: 1                          # artifacts to run in parallel for the same analyzer
# format: text                     # text | json
# timeout: 120                     # per-artifact subprocess timeout in seconds [env: ANALYZER_TIMEOUT]
# environment: DEV                 # default environment label [env: FABRIC_ENVIRONMENT]

# Rule overlays: deltas applied to a packaged ruleset instead of forking it.
# rules:
#   bpa:
#     disable: [RULE_ID]                  # remove a rule from the effective ruleset
#     severity: {RULE_ID: warning}        # info | warning | error
#     extend: path/to/extra-rules.json    # append rules from another file
#   pbir:
#     disable: [RULE_ID]
#     severity: {RULE_ID: warning}        # warning | error (PBIR Inspector has no "info" level)
"""

_ENV_EXAMPLE_TEMPLATE = """\
# .env.example -- copy to .env and fill in the values you need.
# .env is auto-discovered at the repository root; --env-file overrides it.
# Never commit the real .env -- it holds credentials.

# Service principal for Fabric/Power BI REST API access.
# Leave all three unset to fall back to DefaultAzureCredential (az login,
# a managed identity, VS Code sign-in, ...).
FABRIC_TENANT_ID=
FABRIC_CLIENT_ID=
FABRIC_CLIENT_SECRET=

# Playwright visual/error validation target.
PLAYWRIGHT_WORKSPACE_ID=
PLAYWRIGHT_REPORT_ID=
PLAYWRIGHT_REPORT_NAME=
PLAYWRIGHT_DATASET_ID=
"""


def _init(args: argparse.Namespace) -> int:
    """Scaffold a commented fab-test.yml and .env.example.

    Never overwrites an existing file -- each is reported and left
    untouched instead. --dry-run reports what would be created without
    writing anything.
    """
    output_format = getattr(args, "output_format", "text")
    dry_run = getattr(args, "dry_run", False)
    templates = {
        REPO_ROOT / CONFIG_FILENAME: _FAB_TEST_YML_TEMPLATE,
        REPO_ROOT / ".env.example": _ENV_EXAMPLE_TEMPLATE,
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
    return _print_doctor(rows, output_format)


_TOOL_DISPLAY_NAMES = {
    "bpa": "Tabular Editor",
    "pbir": "PBIR Inspector",
}


def _list_analyzers(args: argparse.Namespace) -> int:
    """List every subcommand with its artifact glob, matched count, and tool."""
    artifact_dir = Path(args.artifact_dir)
    output_format = getattr(args, "output_format", "text")

    rows = []
    for name in _visible_analyzers():
        glob, description = _ANALYZER_REGISTRY[name]
        count = 1 if _is_repository_scoped(name) else len(_discover(artifact_dir, glob, None))
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
    return _print_list(rows, output_format)


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
    refusal = _unsupported_scope_error(name, args.resolved_target)
    if refusal:
        print(f"  ✗ fab-test explain: {refusal}", file=sys.stderr)
        return 2

    if _is_repository_scoped(name):
        artifact = Path(".")
    else:
        matches = _discover(artifact_dir, glob, _target_of(args))
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
        except Exception as exc:  # any auth failure is reported, never re-raised
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


_LOCAL_ANALYZERS = ("pql_lint", "bpa", "pbir", "pql_test")


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
        code = _run_analyzer(name, args, output_dir, manifest)
        results.append({"analyzer": name, "status": "ran", "exit_code": code})

    exit_code = 1 if any(r.get("exit_code", 0) != 0 for r in results) else 0
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
        refusal = _unsupported_scope_error(args.analyzer, args.resolved_target)
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

    target = args.resolved_target

    if args.analyzer == "all":
        analyzers = _all_analyzers()
        # An analyzer that cannot honor the target is skipped rather than
        # failing the batch: `all local/Sales` should still run everything
        # that reads files, and saying which were skipped is more useful
        # than refusing the whole invocation.
        runnable = []
        for name in analyzers:
            refusal = _unsupported_scope_error(name, target)
            if refusal:
                narrate(
                    f"  ⚠ fab-test all: skipping {name} — {refusal}",
                    output_format=args.output_format,
                )
            else:
                runnable.append(name)
        if runnable:
            codes = [_run_analyzer(name, args, output_dir, manifest) for name in runnable]
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
        exit_code = _run_analyzer(args.analyzer, args, output_dir, manifest)

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
