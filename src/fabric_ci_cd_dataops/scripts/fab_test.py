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
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
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
    build_command as _build_command,
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
    check_readiness as _check_readiness,
)
from .fab_test_registry import (
    preflight_error as _preflight_error,
)
from .fab_test_summary import (
    _print_all_summary,
    _print_doctor,
    _print_list,
    _print_summary,
    _read_artifact_envelope,
)

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


def _load_pyproject_config(path: Path) -> dict[str, Any]:
    """Load the ``[tool.fab-test]`` table from ``pyproject.toml``, if present."""
    if not path.exists():
        return {}
    try:
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    config = data.get("tool", {}).get("fab-test", {})
    return config if isinstance(config, dict) else {}


_PYPROJECT_CONFIG = _load_pyproject_config(REPO_ROOT / "pyproject.toml")


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


def _resolve_timeout(
    args: argparse.Namespace, config: dict[str, Any] | None = None
) -> int:
    """Resolve the per-artifact subprocess timeout.

    Precedence: --timeout > ANALYZER_TIMEOUT > [tool.fab-test].timeout > default.
    """
    cli_timeout = getattr(args, "timeout", None)
    if cli_timeout is not None:
        return cli_timeout
    env_timeout = os.environ.get("ANALYZER_TIMEOUT", "")
    if env_timeout:
        try:
            return int(env_timeout)
        except ValueError:
            pass
    config = _PYPROJECT_CONFIG if config is None else config
    if "timeout" in config:
        return config["timeout"]
    return _DEFAULT_SUBPROCESS_TIMEOUT


def _apply_environment_default(
    args: argparse.Namespace, config: dict[str, Any]
) -> None:
    """Fill --env from FABRIC_ENVIRONMENT or [tool.fab-test] when not passed.

    No-op for subcommands without an --env flag. CLI values are never
    overwritten; env var still takes precedence over the config file.
    """
    if not hasattr(args, "environment") or args.environment:
        return
    args.environment = os.environ.get("FABRIC_ENVIRONMENT") or config.get(
        "environment", ""
    )


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


def _run_one_artifact(
    name: str,
    artifact: Path,
    args: argparse.Namespace,
    output_dir: Path,
    in_ci: bool,
    sub_env: dict[str, str],
    timeout: int,
    index: int,
    total: int,
) -> tuple[str, int]:
    """Run one analyzer against one artifact. Returns (stem, exit_code)."""
    output_format = getattr(args, "output_format", "text")
    display_name = "." if _is_repository_scoped(name) else artifact.stem
    if total > 1:
        if in_ci:
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
            stderr=None if in_ci else subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=sub_env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        narrate(
            f"  ⏰ fab-test {name}: timed out after {timeout}s for {display_name}",
            output_format=output_format,
        )
        if capture_stdout:
            _reemit(exc.stdout)
        return (display_name, 1)

    if capture_stdout:
        _reemit(proc.stdout)

    if not in_ci and proc.stderr:
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

    _errors, warnings = _severity_counts(envelope.get("findings", []))
    if in_ci:
        emit_workflow_annotations(envelope)
    if warnings > 0:
        emit_pr_review_comments(envelope, str(artifact))
    _send_telemetry(name, artifact, envelope, args)

    return (artifact.stem, artifact_code)


def _run_analyzer(name: str, args: argparse.Namespace, output_dir: Path) -> int:
    """Run one analyzer against all matching artifacts. Returns 0 or 1."""
    glob, description = _ANALYZER_REGISTRY[name]
    artifact_dir = Path(args.artifact_dir)
    output_format = getattr(args, "output_format", "text")
    # `all` emits its own aggregate JSON via _print_all_summary; a standalone
    # analyzer must emit its own so stdout is never empty under --format json.
    emit_own_json = output_format == "json" and getattr(args, "analyzer", None) != "all"

    if _is_repository_scoped(name):
        # Repository-scoped analyzers run once against the repo metadata.
        artifacts = [Path(".")]
    elif name == "playwright" and getattr(args, "impact_manifest", None):
        # Impact-manifest driven Playwright validates a service-resolved set
        # of reports once, regardless of how many Report artifacts exist
        # locally.
        artifacts = [Path(".")]
    else:
        artifacts = _discover(artifact_dir, glob, getattr(args, "artifact", None))

    if not artifacts:
        narrate(
            f"  ⚠ fab-test {name}: no {glob} artifacts found in {artifact_dir}",
            output_format=output_format,
        )
        if emit_own_json:
            print(json.dumps({"analyzer": name, "artifacts": []}, indent=2))
        return 0

    if args.dry_run:
        narrate(
            f"\nfab-test {name} ({description}) — dry run, "
            f"{len(artifacts)} artifact(s):",
            output_format=output_format,
        )
        for a in artifacts:
            narrate(f"  • {a.name}", output_format=output_format)
        if _telemetry_enabled(args):
            environment = getattr(args, "environment", "") or os.getenv(
                "FABRIC_ENVIRONMENT", ""
            )
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
                        "artifacts": [a.name for a in artifacts],
                    },
                    indent=2,
                )
            )
        return 0

    # Pre-flight: check required tools exist before invoking subprocesses.
    preflight_err = _preflight_error(name, args)
    if preflight_err:
        message, exit_code = preflight_err
        narrate(
            f"\n  ✗ fab-test {name}: missing prerequisite\n  {message}\n",
            output_format=output_format,
        )
        return exit_code

    in_ci = _is_ci()
    _sub_env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    verbosity = _verbosity_env(args)
    if verbosity:
        _sub_env["ANALYZER_VERBOSITY"] = verbosity
    if output_format == "json":
        _sub_env["ANALYZER_OUTPUT_MODE"] = "json"
    timeout = _resolve_timeout(args)
    jobs = max(1, getattr(args, "jobs", 1) or 1)

    total = len(artifacts)

    def _run(index_artifact: tuple[int, Path]) -> tuple[str, int]:
        index, artifact = index_artifact
        return _run_one_artifact(
            name, artifact, args, output_dir, in_ci, _sub_env, timeout, index, total
        )

    indexed_artifacts = list(enumerate(artifacts, start=1))
    if jobs > 1 and len(artifacts) > 1:
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            results = list(executor.map(_run, indexed_artifacts))
    else:
        results = [_run(pair) for pair in indexed_artifacts]

    return _print_summary(
        name,
        results,
        output_dir=output_dir,
        verbosity=verbosity,
        output_format=output_format,
    )


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-dir",
        default=str(_PYPROJECT_CONFIG.get("artifact_dir", ARTIFACT_ROOT)),
        metavar="DIR",
        help=f"Root for .fabric artifacts (default: {ARTIFACT_ROOT})",
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
        "--artifact",
        default=None,
        metavar="STEM",
        help="Only analyze the artifact whose stem matches STEM",
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
    "pql-lint": "pql_lint",
    "playwright_impact": "playwright-impact",
}


_COMMON_COMPLETION_FLAGS = (
    "--artifact-dir --output-dir --dry-run --artifact --timeout --jobs "
    "-v --verbose --telemetry --no-telemetry --format --help"
)


def _completion_subcommands() -> str:
    return " ".join((*_ANALYZER_REGISTRY.keys(), "all", "clean-tools"))


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
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

    # --- pql_test ---
    pql_test_p = subs.add_parser(
        "pql_test",
        aliases=["pql-test"],
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

    # --- pql_lint ---
    pql_lint_p = subs.add_parser(
        "pql_lint",
        aliases=["pql-lint"],
        help="pqlint Power Query linter (SemanticModel artifacts)",
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

    return parser


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


def _doctor(args: argparse.Namespace) -> int:
    """Check whether each analyzer's prerequisites are ready to run."""
    output_format = getattr(args, "output_format", "text")
    only = getattr(args, "analyzer_filter", None)
    if only and only not in _ANALYZER_REGISTRY:
        print(
            f"  ✗ fab-test doctor: unknown analyzer '{only}'. "
            f"Valid names: {', '.join(_ANALYZER_REGISTRY)}",
            file=sys.stderr,
        )
        return 2

    names = [only] if only else list(_ANALYZER_REGISTRY.keys())
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
    for name, (glob, description) in _ANALYZER_REGISTRY.items():
        if _is_repository_scoped(name):
            count = 1
        else:
            count = len(_discover(artifact_dir, glob, None))
        rows.append(
            {
                "analyzer": name,
                "description": description,
                "glob": glob or None,
                "matched_artifacts": count,
                "required_tool": _TOOL_DISPLAY_NAMES.get(name),
            }
        )
    return _print_list(rows, output_format)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.analyzer = _SUBCOMMAND_ALIASES.get(args.analyzer, args.analyzer)

    if args.analyzer == "clean-tools":
        return _clean_tools(REPO_ROOT, args.dry_run)

    if args.analyzer == "doctor":
        return _doctor(args)

    if args.analyzer == "list":
        return _list_analyzers(args)

    _apply_environment_default(args, _PYPROJECT_CONFIG)
    output_dir = Path(args.output_dir)

    artifact_dir = Path(args.artifact_dir)
    if not artifact_dir.exists():
        narrate(
            f"  ✗ fab-test: --artifact-dir does not exist: {artifact_dir}",
            output_format=args.output_format,
        )
        return 2

    if args.analyzer == "all":
        analyzers = _all_analyzers()
        if not analyzers:
            narrate(
                "  ⚠ fab-test all: no analyzers configured in analyzers.json",
                output_format=args.output_format,
            )
            return 0
        codes = [_run_analyzer(name, args, output_dir) for name in analyzers]
        return _print_all_summary(output_dir, analyzers, codes, args)

    return _run_analyzer(args.analyzer, args, output_dir)


if __name__ == "__main__":
    sys.exit(main())
