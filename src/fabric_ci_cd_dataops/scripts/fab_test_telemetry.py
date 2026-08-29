"""fab-test's telemetry: readiness, payload building, and delivery.

Extracted from fab_test.py (Fab-Test Module Split epic). Pure move -- no
behavior change; `--telemetry --dry-run`'s preview output stays unchanged.
"""

import argparse
import contextlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fabric_ci_cd_dataops import __version__ as _FAB_TEST_VERSION

from ._analyzer_envelope import severity_counts
from ._cli_utils import narrate
from ._fab_test_context import REPO_ROOT
from ._git_context import git_command_output, git_context
from ._telemetry import TelemetryDecision, telemetry_decision
from .eventhouse_logger import EventhouseSink, publish_analyzer_telemetry


def _telemetry_table(analyzer: str) -> str:
    """Return the Eventhouse table an analyzer's records land in.

    Derived, never configured: a config key would only let the file and the
    derivation disagree about where a record went.
    """
    return "fabric_dynamic_analysis" if analyzer == "pql_test" else "fabric_static_analysis"


def _telemetry_destination(decision: TelemetryDecision, analyzer: str) -> str:
    """Describe where telemetry would go, for the --dry-run preview."""
    if not decision.eventhouse.configured:
        return "not configured (set `telemetry.eventhouse` in fab-test.yml)"
    return (
        f"{decision.eventhouse.uri} / {decision.eventhouse.database} "
        f"/ {_telemetry_table(analyzer)}"
    )


def _telemetry_readiness(args: argparse.Namespace) -> dict[str, Any]:
    """Return a `doctor` row for telemetry.

    ``ready`` is tri-state. False is a problem the caller can fix; None means
    "not applicable or not verifiable here" and never counts toward whether
    `doctor` passes -- telemetry is optional, and a run that never wanted it
    must not be reported as broken.

    A configured destination with resolvable credentials still returns None
    rather than True. Ingest permission is a grant on the KQL database, and
    a service principal without the Database Ingestor role authenticates
    perfectly and cannot ingest. `doctor` once reported four cloud analyzers
    ready with no credentials at all; claiming ready on the strength of a
    resolvable credential would be the same false green.
    """
    from ._credentials import (
        IncompleteServicePrincipalError,
        ambient_credential_available,
        resolve_service_principal,
    )
    from .eventhouse_logger import (
        TelemetryDependencyError,
        load_ingest_dependencies,
    )

    def _row(ready, reason, remediation=None, resolved_path=None):
        return {
            "analyzer": "telemetry",
            "ready": ready,
            "reason": reason,
            "remediation": remediation,
            "resolved_path": resolved_path,
            "version": None,
        }

    eventhouse = _telemetry_decision(args).eventhouse
    if not eventhouse.configured:
        return _row(None, "not configured (optional; set `telemetry.eventhouse` to enable)")

    destination = f"{eventhouse.uri} / {eventhouse.database}"

    try:
        load_ingest_dependencies()
    except TelemetryDependencyError as exc:
        return _row(False, "ingest client not installed", str(exc), destination)

    env_file = getattr(args, "playwright_env_file", None)
    try:
        principal = resolve_service_principal(env_file)
    except IncompleteServicePrincipalError as exc:
        return _row(False, "service principal is incomplete", str(exc), destination)

    if principal is None and not ambient_credential_available():
        return _row(
            False,
            "no credentials resolved",
            "Set FABRIC_TENANT_ID, FABRIC_SERVICE_PRINCIPAL_ID, and "
            "FABRIC_SERVICE_PRINCIPAL_SECRET, or sign in with `az login`",
            destination,
        )

    return _row(
        None,
        "configured; ingest permission unverified",
        "Tables are created on first use. If that fails, the credential needs rights "
        "to create tables as well as the Database Ingestor role on the KQL database "
        "(Fabric: the Eventhouse item -> Manage permissions); the failure message "
        "carries the KQL to run by hand instead",
        destination,
    )


def _open_telemetry(args: argparse.Namespace) -> Any:
    """Open this run's telemetry sink, or None when nothing asked for one.

    Keyed off `requested` rather than `enabled` so a run that asked but has
    nowhere to send still reaches `_close_telemetry`, which is what makes a
    silently-discarded record impossible.
    """
    decision = _telemetry_decision(args)
    if not decision.requested:
        return None
    return EventhouseSink(
        decision.eventhouse, env_file=getattr(args, "playwright_env_file", None)
    )


def _close_telemetry(sink: Any, args: argparse.Namespace) -> str | None:
    """Deliver the run's telemetry and report once. Returns the failure, if any.

    Once per run, not once per artifact: N identical warnings for one
    unreachable cluster is noise that hides the next problem.
    """
    if sink is None:
        return None
    output_format = getattr(args, "output_format", "text")
    decision = _telemetry_decision(args)
    if not decision.eventhouse.configured:
        message = (
            "telemetry was requested but no Eventhouse destination is configured; "
            "set `telemetry.eventhouse` in fab-test.yml or EVENTHOUSE_URI/EVENTHOUSE_DATABASE"
        )
        narrate(f"::warning::{message}", output_format=output_format)
        return message

    result = sink.flush()
    if result.ok:
        if result.sent:
            narrate(
                f"  ✓ fab-test: telemetry delivered ({result.sent} record(s))",
                output_format=output_format,
            )
        return None
    narrate(f"::warning::Telemetry not delivered: {result.error}", output_format=output_format)
    return result.error


def _telemetry_decision(args: argparse.Namespace) -> TelemetryDecision:
    """Resolve this run's telemetry decision from the flags and the config file."""
    return telemetry_decision(
        cli_telemetry=getattr(args, "telemetry", None),
        file_config=getattr(args, "file_config", None) or {},
    )


def _telemetry_enabled(args: argparse.Namespace) -> bool:
    """Return True when telemetry should be streamed for this invocation.

    The rule itself lives in `_telemetry`, which `eventhouse_logger` also
    reads; this stays because two call sites and their tests name it.
    """
    return _telemetry_decision(args).enabled


# Re-exported under their historic private names: telemetry code and its
# tests call `_git_context()`/`_git_command_output()` and monkeypatch them
# as module attributes here. The implementation lives in `_git_context.py`
# so `_report_html.py` (the run index) can share it without importing this
# module, which would be a cycle.
_git_command_output = git_command_output
_git_context = git_context


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


def _relativize_paths(value: Any, repo_root: Path) -> Any:
    """Rewrite absolute paths under ``repo_root`` to repository-relative ones.

    Applied to the telemetry payload only, never to the envelope on disk: a
    human clicking a result wants the absolute path, and an Eventhouse row
    does not.

    The leak this closes is not obvious from the payload's own fields. Every
    analyzer envelope carries `artifact_path` and `rules_file`, and the whole
    envelope is embedded as `results`, so `C:\\Users\\<name>\\...` shipped the
    operating-system username in plaintext on every local run -- while
    `actor`, the field meant to identify the run, was hashed into something
    nobody could resolve.

    A path *outside* the repository is dropped to its final component rather
    than rewritten as `../../..`, which would leak the depth of the home
    directory and mean nothing to a reader of the table.
    """
    if isinstance(value, dict):
        return {key: _relativize_paths(item, repo_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_relativize_paths(item, repo_root) for item in value]
    if not isinstance(value, str) or not value:
        return value
    return _relative_to_root(value, repo_root)


def _relative_to_root(value: str, repo_root: Path) -> str:
    """Return one string with any absolute path in it made repository-relative."""
    root = f"{repo_root}"
    if root and root in value:
        # Both separators: an envelope written on Windows carries backslashes
        # while the JSON that quotes it may not.
        return value.replace(f"{root}\\", "").replace(f"{root}/", "").replace(root, ".")
    if _looks_absolute(value):
        return Path(value).name
    return value


def _looks_absolute(value: str) -> str | bool:
    """Whether a string looks like an absolute filesystem path.

    Deliberately narrow: a false positive would rewrite an ordinary message
    into its last path-like component, which is worse than leaving a path
    that names nothing sensitive.
    """
    return value.startswith(("/", "\\")) or (len(value) > 2 and value[1:3] in (":\\", ":/"))


def _build_telemetry_payload(
    analyzer: str,
    artifact: Path,
    envelope: dict[str, Any],
    environment: str,
) -> dict[str, Any]:
    """Build a telemetry payload for an analyzer/artifact run."""
    errors, warnings = severity_counts(envelope.get("findings", []))
    ctx = _git_context()
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "artifact_name": artifact.stem,
        "artifact_type": artifact.suffix.lstrip("."),
        "commit_sha": ctx.get("commit", ""),
        "workflow_run_id": ctx.get("workflow_run_id", ""),
        "repository": ctx.get("repository", ""),
        # Recorded as given. Hashing this answered "was this the same person
        # as last time" and nothing else, while the username leaked anyway
        # through the paths below -- so it bought no privacy and cost the
        # attribution the field exists for. The repository already stores
        # this address in plaintext on every commit.
        "actor": ctx.get("actor", ""),
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
    # Last, over the whole payload including the embedded envelope: the
    # username leaked through `results.artifact_path`, not through any field
    # named above, so relativizing only the fields we thought about is how
    # this was missed the first time.
    return _relativize_paths(payload, REPO_ROOT)


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
    sink: Any = None,
) -> None:
    """Queue a telemetry record if enabled. Telemetry failure is non-blocking.

    Queued rather than sent: one run's records go out in as few ingests as
    the tables allow, because this is called once per artifact and a client
    per artifact would pay connection setup N times. `sink` is None only for
    a caller that has not opened one, which then falls back to the immediate
    single-record path.
    """
    if not _telemetry_enabled(args):
        return

    output_format = getattr(args, "output_format", "text")
    table = _telemetry_table(analyzer)
    payload = _build_telemetry_payload(
        analyzer,
        artifact,
        envelope,
        getattr(args, "environment", "") or os.getenv("FABRIC_ENVIRONMENT", ""),
    )
    validated = _validate_telemetry_payload(payload, output_format)
    if validated is None:
        return
    if sink is not None:
        sink.add(table, validated)
        return
    try:
        publish_analyzer_telemetry(table, validated, force=True)
    except Exception as exc:  # noqa: BLE001 - boundary: telemetry never fails a run
        narrate(
            f"::warning::Telemetry failed for {artifact.stem}: {exc}",
            output_format=output_format,
        )
