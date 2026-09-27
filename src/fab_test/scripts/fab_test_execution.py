"""fab-test's per-artifact execution core: discovery, subprocess, envelope, summary.

Extracted from fab_test.py (Fab-Test Module Split epic). Pure move -- no
behavior change; `--jobs` parallelism, timeout resolution, and per-artifact
progress narration all stay exactly as they were.
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._analyzer_annotations import (
    emit_pr_review_comments,
    emit_workflow_annotations,
)
from ._analyzer_envelope import severity_counts
from ._cli_utils import CHECKOUT_REMEDIATION, narrate, skipped_checkout_lines
from ._config import resolve_setting
from ._credentials import configured_workspace, redact_secrets
from ._fab_test_context import (
    _DEFAULT_SUBPROCESS_TIMEOUT,
    _PYPROJECT_CONFIG,
    RESULTS_ROOT,
)
from ._playwright_dataset_target import (
    DatasetTargetExit,
    dataset_target_requested,
    refuse_dataset_workspace_without_dataset_id,
    resolve_dataset_targets,
)
from ._playwright_timeout_scaling import (
    Narration as PlaywrightNarration,
)
from ._playwright_timeout_scaling import run_playwright_with_scaled_timeout
from ._report_html import resolve_report
from ._run_manifest import RunManifest
from ._scan import find_rdl_files as _find_rdl_files
from ._scan import find_skipped_checkouts as _find_skipped_checkouts
from ._target import target_from_args
from .fab_test_registry import (
    ANALYZER_REGISTRY as _ANALYZER_REGISTRY,
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
    discover_artifacts as _discover,
)
from .fab_test_registry import (
    discover_pbip_sources as _discover_pbip_sources,
)
from .fab_test_registry import (
    is_repository_scoped as _is_repository_scoped,
)
from .fab_test_registry import (
    playwright_test_cases_dir as _playwright_test_cases_dir,
)
from .fab_test_registry import (
    preflight_error as _preflight_error,
)
from .fab_test_summary import _print_summary, _read_artifact_envelope
from .fab_test_telemetry import (
    _build_telemetry_payload,
    _send_telemetry,
    _telemetry_decision,
    _telemetry_destination,
)
from .playwright_validation.resolver import resolve_workspace_id

# Referenced by _run_analyzer via _is_ci(); a module-level function rather
# than inline os.environ reads so tests can monkeypatch it as one seam.
_CI_PREFIXES = ("::error::", "::warning::", "::notice::")


def _is_ci() -> bool:
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def _clean_annotation(line: str) -> str:
    for prefix in _CI_PREFIXES:
        if line.startswith(prefix):
            return line[len(prefix) :]
    return line


# Long enough for the full remediation sentences the analyzers actually emit,
# which name every flag and environment variable that would resolve the
# failure, and short enough that a stack trace cannot turn run.json into a
# log file.
_DETAIL_MAX_CHARS = 500


def _stderr_detail(stderr: str | None) -> str | None:
    """Return the analyzer's failure message for `run.json`, or None.

    Called only when the analyzer exited non-zero *without* writing an
    envelope, so its stderr is the only account of what went wrong. An
    `::error::` line is the message the analyzer chose to surface, so it wins
    over whatever noise trails it; failing that, the last non-empty line does.

    Redacted on the way in: the secrets constraint puts the run manifest on
    the same footing as stdout and telemetry, and a child that interpolates a
    client secret into its own error text would otherwise write it to a file
    a pipeline uploads.
    """
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    if not lines:
        return None
    annotated = [line for line in lines if line.startswith("::error::")]
    chosen = _clean_annotation(annotated[-1] if annotated else lines[-1])
    return redact_secrets(chosen)[:_DETAIL_MAX_CHARS]


def _verbosity_env(args: argparse.Namespace) -> str:
    """Map fab-test -v/-vv flags to ANALYZER_VERBOSITY values."""
    count = getattr(args, "verbose", 0) or 0
    if count >= 2:
        return "debug"
    if count == 1:
        return "verbose"
    return ""


# Defined in _report_html so fab_test_summary can ask the same question
# without importing this module, which would be a cycle.
_resolve_report = resolve_report


def _resolve_timeout(args: argparse.Namespace, config: dict[str, Any] | None = None) -> tuple[int, bool]:
    """Resolve the per-artifact subprocess timeout via the centralized resolver.

    Precedence: --timeout > ANALYZER_TIMEOUT > config file > default.

    Returns ``(value, is_default)``. ``is_default`` is True only when
    nothing explicit was set anywhere -- the signal that lets playwright's
    case-count-scaled timeout (Playwright Case Scaling epic) apply without
    silently overriding a caller's own explicit choice, which stays an
    override in every other analyzer's byte-identical existing behavior.
    """
    config = _PYPROJECT_CONFIG if config is None else config
    value, origin = resolve_setting(
        "timeout",
        cli_value=getattr(args, "timeout", None),
        env_var="ANALYZER_TIMEOUT",
        file_config=config,
        packaged_default=_DEFAULT_SUBPROCESS_TIMEOUT,
        cast=int,
    )
    return value, origin == "default"


def _apply_environment_default(args: argparse.Namespace, config: dict[str, Any]) -> None:
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


def _artifact_exit_code(
    proc_returncode: int,
    envelope: dict[str, Any] | None,
) -> int:
    """Return the fab-test exit code for a single artifact run.

    Warnings do not fail the build. Errors and tool crashes do. A wrapper that
    refused to start (126/127) keeps that code, so setup is not mistaken for a finding.
    """
    failure = proc_returncode if proc_returncode in (126, 127) else 1
    if envelope is None:
        return failure if proc_returncode != 0 else 0
    errors, warnings = severity_counts(envelope.get("findings", []))
    if errors > 0:
        return 1
    if proc_returncode != 0 and warnings == 0:
        return failure
    return 0


@dataclass
class _RunContext:
    """Per-run state shared across every artifact in one analyzer invocation."""

    in_ci: bool
    sub_env: dict[str, str]
    timeout: int
    # True when `timeout` came from the packaged default rather than an
    # explicit --timeout/ANALYZER_TIMEOUT/config value -- see
    # `_resolve_timeout`. Only in this state does playwright's case-count
    # scaling apply.
    timeout_is_default: bool = False
    manifest: RunManifest | None = None
    # One sink per run, drained once at the end. Ingesting inline would open
    # a queued-ingest client per artifact for one logical run.
    telemetry: Any = None


def _announce_artifact_run(
    name: str, display_name: str, index: int, total: int, ctx: "_RunContext", output_format: str
) -> None:
    """Narrate which artifact is about to run, in the "N of total" banner."""
    if total > 1:
        if ctx.in_ci:
            narrate(
                f"::notice::fab-test {name}: artifact {index} of {total} ({display_name})",
                output_format=output_format,
            )
        else:
            narrate(f"  artifact {index} of {total}", output_format=output_format)
    narrate(f"\n  ▶ fab-test {name}  →  {display_name}", output_format=output_format)


def _reemit_lines(text: str | None, output_format: str) -> None:
    """Re-narrate a captured stream, one cleaned annotation line at a time."""
    if not text:
        return
    for line in text.splitlines():
        clean = _clean_annotation(line)
        if clean.strip():
            narrate(f"  {clean}", output_format=output_format)


def _run_artifact_process(
    cmd: list[str],
    ctx: "_RunContext",
    capture_stdout: bool,
    output_format: str,
    name: str,
    display_name: str,
    test_cases_path: Path | None = None,
) -> "subprocess.CompletedProcess | tuple[str, int]":
    """Run the analyzer subprocess. Returns the completed process, or a
    ``(display_name, exit_code)`` result already handled on timeout."""
    if name == "playwright" and ctx.timeout_is_default and test_cases_path is not None:
        return run_playwright_with_scaled_timeout(
            cmd,
            ctx,
            capture_stdout,
            output_format,
            name,
            display_name,
            test_cases_path,
            PlaywrightNarration(reemit_lines=_reemit_lines, narrate=narrate),
        )
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture_stdout else None,
            # Piped in every mode, CI included. Inheriting it there sent the
            # analyzer's remediation to the log and nowhere else, leaving
            # run.json -- often the only artifact a pipeline uploads -- saying
            # the run failed and not why. Re-emitted below either way.
            stderr=subprocess.PIPE,
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
            _reemit_lines(exc.stdout, output_format)
        if ctx.manifest is not None:
            ctx.manifest.record_artifact(
                name,
                display_name,
                "timeout",
                None,
                0,
                0,
                detail=f"exceeded {ctx.timeout}s timeout",
            )
        return (display_name, 1)


def _emit_process_output(
    proc: subprocess.CompletedProcess, capture_stdout: bool, ctx: "_RunContext", output_format: str
) -> None:
    """Re-narrate stdout (if captured) and stderr from a finished analyzer run."""
    if capture_stdout:
        _reemit_lines(proc.stdout, output_format)

    if proc.stderr:
        if ctx.in_ci:
            # Verbatim: GitHub renders `::error::` against the file, and a
            # stripped prefix is a lost annotation.
            print(proc.stderr, end="", file=sys.stderr)
        else:
            _reemit_lines(proc.stderr, output_format)


def _load_artifact_envelope(
    output_dir: Path, name: str, artifact: Path, returncode: int
) -> tuple[dict[str, Any], bool]:
    """Read the analyzer's envelope, or synthesize one when it wrote none.

    Returns ``(envelope, aborted)``. ``aborted`` is set only when the
    analyzer produced no envelope and no clean exit -- its stderr is then
    the only record of why.
    """
    envelope = _read_artifact_envelope(output_dir, name, artifact.stem)
    if envelope is not None:
        return envelope, False
    if returncode == 0:
        return {
            "status": "passed",
            "findings": [],
            "artifact_path": str(artifact),
            "analyzer": name,
        }, False
    return {
        "status": "failed",
        "findings": [],
        "artifact_path": str(artifact),
        "analyzer": name,
    }, True


def _finalize_artifact_run(
    name: str,
    artifact: Path,
    args: argparse.Namespace,
    ctx: "_RunContext",
    proc: subprocess.CompletedProcess,
    envelope: dict[str, Any],
    aborted: bool,
    output_dir: Path,
) -> int:
    """Apply the error/warning threshold, send telemetry, and record the manifest."""
    artifact_code = _artifact_exit_code(proc.returncode, envelope)

    errors, warnings = severity_counts(envelope.get("findings", []))
    if ctx.in_ci:
        emit_workflow_annotations(envelope)
    if warnings > 0:
        emit_pr_review_comments(envelope, str(artifact))
    _send_telemetry(name, artifact, envelope, args, ctx.telemetry)

    if ctx.manifest is not None:
        envelope_path = output_dir / name / artifact.stem / "envelope.json"
        ctx.manifest.record_artifact(
            name,
            artifact.stem,
            envelope.get("status", "unknown"),
            str(envelope_path) if envelope_path.exists() else None,
            errors,
            warnings,
            detail=_stderr_detail(proc.stderr) if aborted else None,
        )

    return artifact_code


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
    _announce_artifact_run(name, display_name, index, total, ctx, output_format)

    cmd = _build_command(name, artifact, args, output_dir)
    # Under --format json, capture the child's stdout instead of inheriting it
    # (it would otherwise land in the middle of the JSON document) and
    # re-emit it as narration. --format text keeps today's direct inheritance
    # so there is no added buffering latency.
    capture_stdout = output_format == "json"

    test_cases_path = None
    if name == "playwright" and not getattr(args, "impact_manifest", None):
        # --impact-manifest runs across multiple reports in one invocation --
        # no single per-artifact cases file to poll for, so that mode keeps
        # the flat outer timeout unchanged.
        test_cases_path = _playwright_test_cases_dir(output_dir, artifact) / "test-cases.json"

    result = _run_artifact_process(cmd, ctx, capture_stdout, output_format, name, display_name, test_cases_path)
    if isinstance(result, tuple):
        return result
    proc = result

    _emit_process_output(proc, capture_stdout, ctx, output_format)

    # Read the envelope and apply the error/warning threshold ourselves so
    # warnings never fail the build.
    envelope, aborted = _load_artifact_envelope(output_dir, name, artifact, proc.returncode)
    artifact_code = _finalize_artifact_run(name, artifact, args, ctx, proc, envelope, aborted, output_dir)
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


def _playwright_remote_target(args: argparse.Namespace) -> Path | None:
    """A playwright target named explicitly, with an environment to resolve it
    against, but no matching local folder.

    Playwright never reads report content from disk for either report type --
    the local folder under ``--artifact-dir`` is purely a naming anchor for
    the "discover everything" batch case. A caller who named a specific
    report (``--artifact NAME`` or ``WORKSPACE.Workspace/NAME.Type``) and an
    environment has stated an intent to resolve it live via ``resolve_report``,
    which a paginated (RDL) report especially needs: this repo's
    ``.fabric/artifacts/`` tree only ever holds PBIR-format interactive
    reports, so an RDL report can never have a local folder to be found by at
    all. A real filesystem path (``./src/Sales.Report``) is left alone --
    naming a specific location and finding nothing there is a real miss, not
    a signal to resolve remotely.
    """
    target = _target_of(args)
    if target is None or target.scope not in ("path", "workspace"):
        return None
    if target.scope == "path" and target.path is not None:
        return None
    environment = getattr(args, "environment", "") or os.getenv("FABRIC_ENVIRONMENT", "")
    workspace = configured_workspace(args, playwright=False)
    if not environment and not workspace:
        return None
    return Path(target.name)


def _discover_rdl_files(args: argparse.Namespace, output_dir: Path) -> list[Path]:
    """Return local ``.rdl`` files matching the current target, if any.

    A paginated report is a flat ``NAME.rdl`` file, not a folder with a
    Fabric type suffix -- ``discover_artifacts``/`scan` cannot find it, since
    they only ever match directory names. Narrowed the same way
    `discover_artifacts` narrows a directory match: a target naming a
    different type finds nothing, and a target naming a name filters to it.
    """
    target = _target_of(args)
    if target is not None and target.type is not None and target.type != "PaginatedReport":
        return []
    files = _find_rdl_files(Path(args.artifact_dir), excluded_paths=[output_dir])
    if target is None or target.name is None:
        return files
    return [f for f in files if f.stem == target.name]


def _discover_for(name: str, args: argparse.Namespace, glob: str) -> list[Path]:
    """Return the artifacts ``name`` will run against.

    Two analyzers do not discover at all: a repository-scoped one runs once
    against the repo metadata, and impact-manifest- or dataset-driven
    Playwright validates a service-resolved set whatever exists locally.
    """
    if _is_repository_scoped(name):
        return [Path(".")]
    if name == "playwright":
        refuse_dataset_workspace_without_dataset_id(args)
    if name == "playwright" and getattr(args, "impact_manifest", None):
        return [Path(".")]
    if name == "playwright" and dataset_target_requested(args):
        return resolve_dataset_targets(args)
    output_dir = Path(getattr(args, "output_dir", RESULTS_ROOT))
    discovered = _discover(Path(args.artifact_dir), glob, _target_of(args), output_dir=output_dir)
    if name == "playwright":
        # playwright's own registered glob only ever covers *.Report, so a
        # paginated report -- a flat .rdl file, never discovered by the
        # directory-suffix scan above -- needs its own lookup or a batch run
        # (no --artifact) would never find one at all.
        discovered = discovered + _discover_rdl_files(args, output_dir)
        if not discovered:
            remote = _playwright_remote_target(args)
            if remote is not None:
                return [remote]
    return discovered


def _report_no_artifacts(name: str, glob: str, args: argparse.Namespace, *, emit_own_json: bool) -> int:
    """Narrate an empty discovery. Always exits 0 -- nothing matched is not a failure.

    An empty result has two very different causes that used to read
    identically: the root holds no artifacts, or every candidate below it
    was pruned as a nested checkout. The second is what a developer sees
    running `fab-test` from a folder of sibling repositories, and it is
    the one with a fix worth naming.
    """
    output_format = getattr(args, "output_format", "text")
    target = _target_of(args)
    checkouts: list[Path] = []
    if target is not None and target.path is not None:
        # A path target named a specific location, so reporting what the
        # scan of --artifact-dir turned up would answer a question the
        # caller did not ask.
        narrate(
            f"  ⚠ fab-test {name}: no {glob} artifact at {target.path}",
            output_format=output_format,
        )
    else:
        artifact_dir = Path(args.artifact_dir)
        checkouts = _find_skipped_checkouts(artifact_dir)
        # No `.pbip` clause: pairing enriches a result, and has not decided
        # whether an artifact exists since discovery went suffix-based.
        narrate(
            f"  ⚠ fab-test {name}: no {glob} artifacts found under {artifact_dir}",
            output_format=output_format,
        )
        for line in skipped_checkout_lines(checkouts):
            narrate(line, output_format=output_format)
    if emit_own_json:
        payload: dict[str, Any] = {
            "analyzer": name,
            "artifacts": [],
            "skipped_checkouts": [str(path) for path in checkouts],
        }
        if checkouts:
            payload["remediation"] = CHECKOUT_REMEDIATION
        print(json.dumps(payload, indent=2))
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
        f"\nfab-test {name} ({description}) — dry run, {len(artifacts)} artifact(s):",
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
    # Keyed off "the caller asked", not "we could send". A preview whose job
    # is to show what would happen has to survive an unset destination and
    # say that the destination is what is unset.
    decision = _telemetry_decision(args)
    if decision.requested:
        narrate(
            f"\n  Telemetry destination: {_telemetry_destination(decision, name)}",
            output_format=output_format,
        )
        environment = getattr(args, "environment", "") or os.getenv("FABRIC_ENVIRONMENT", "")
        for a in artifacts:
            preview = _build_telemetry_payload(name, a, {"status": "dry-run", "findings": []}, environment)
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
    telemetry: Any = None,
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

    try:
        artifacts = _discover_for(name, args, glob)
    except DatasetTargetExit as exc:
        return exc.code
    if not artifacts:
        return _report_no_artifacts(name, glob, args, emit_own_json=emit_own_json)
    if args.dry_run:
        return _report_dry_run(name, description, artifacts, args, emit_own_json=emit_own_json)

    preflight_exit_code = _preflight(name, args, artifacts, manifest)
    if preflight_exit_code is not None:
        return preflight_exit_code

    verbosity = _verbosity_env(args)
    timeout, timeout_is_default = _resolve_timeout(args)
    ctx = _RunContext(
        in_ci=_is_ci(),
        sub_env=_analyzer_sub_env(args, output_format),
        timeout=timeout,
        timeout_is_default=timeout_is_default,
        manifest=manifest,
        telemetry=telemetry,
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
        # `all` lists every report beneath its aggregate table; naming them
        # here as well printed each one twice. Same condition as
        # emit_own_json above, and for the same reason.
        show_reports=getattr(args, "analyzer", None) != "all",
        args=args,
    )
