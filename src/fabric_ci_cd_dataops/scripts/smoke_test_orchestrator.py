#!/usr/bin/env python3
"""Smoke test for the orchestrator pipeline.

Bumps a harmless field in one or more .platform files (SemanticModel and/or
Report), commits, pushes to the current branch, and watches the triggered
orchestrator workflow run to completion.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from difflib import unified_diff
from pathlib import Path
from typing import NoReturn

SMOKE_COMMIT_MESSAGE = "test(smoke): bump .platform to trigger orchestrator"
REQUIRED_INFRASTRUCTURE_JOBS = {
    "Branch / Environment Guard",
    "Detect Changes / Detect Changed Artifacts",
    "Run CI/CD Pipeline / Prepare Artifact Matrix",
    "Constraint Enforcement Summary",
    "Pipeline Summary",
}
ACCEPTABLE_FAILURE_JOBS = {
    "Run CI/CD Pipeline / Tabular Editor BPA - SampleModel-PQLAssert.SemanticModel",
    "Run CI/CD Pipeline / PBIR Inspector - SampleModel-PQLAssert.Report",
    # Dynamic analyzers need the artifact deployed in the target workspace first.
    # A missing model or report in the workspace is an environment/artifact state
    # issue, not a pipeline wiring defect, and must not be treated as a failure
    # of the smoke test itself.
    "Run CI/CD Pipeline / Dynamic Analyzer - pql_test - SampleModel-PQLAssert.SemanticModel",
    "Run CI/CD Pipeline / Dynamic Analyzer - playwright - SampleModel-PQLAssert.Report",
    # Matrix jobs are skipped when no matching artifact changed; the literal
    # placeholder names appear in that case. Accept either skipped or failed
    # placeholder matrix jobs because they represent no artifact to process.
    "Run CI/CD Pipeline / PBIR Inspector - ${{ matrix.artifact }}",
    "Run CI/CD Pipeline / Tabular Editor BPA - ${{ matrix.artifact }}",
    "Run CI/CD Pipeline / Deploy - ${{ matrix.name }}",
    "Run CI/CD Pipeline / Telemetry - ${{ matrix.name }}",
    "Run CI/CD Pipeline / Deploy - SampleModel-PQLAssert.SemanticModel",
    "Run CI/CD Pipeline / Deploy - SampleModel-PQLAssert.Report",
    "Run CI/CD Pipeline / Telemetry - SampleModel-PQLAssert.SemanticModel",
    "Run CI/CD Pipeline / Telemetry - SampleModel-PQLAssert.Report",
}
PLATFORM_PATHS = {
    "semantic-model": Path(
        ".fabric/artifacts/SampleModel-PQLAssert.SemanticModel/.platform"
    ),
    "report": Path(".fabric/artifacts/SampleModel-PQLAssert.Report/.platform"),
}


def platform_paths_for(artifact_type: str) -> list[Path]:
    """Return the .platform paths to bump for the requested artifact type."""
    if artifact_type == "both":
        return list(PLATFORM_PATHS.values())
    return [PLATFORM_PATHS[artifact_type]]


def _safe_print(message: str) -> str:
    """Return a UTF-8-safe string by replacing unsupported characters."""
    return message.encode("utf-8", errors="replace").decode("utf-8")


def fail(message: str) -> NoReturn:
    """Print an error message and exit with code 1."""
    print(_safe_print(f"[FAIL] {message}"), file=sys.stderr)
    sys.exit(1)


def safe_print(message: str) -> None:
    """Print a UTF-8-safe message to stdout."""
    print(_safe_print(message))


def run(
    command: list[str], *, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a shell command, optionally capturing output."""
    if capture:
        return subprocess.run(
            command,
            check=check,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
    return subprocess.run(
        command, check=check, text=True, encoding="utf-8", errors="replace"
    )


def bump_platform_content(content: str, timestamp: str) -> str:
    """Return .platform content with an updated _smokeTestTimestamp in config."""
    data = json.loads(content)
    data.setdefault("config", {})
    data["config"]["_smokeTestTimestamp"] = timestamp
    output = json.dumps(data, indent=2)
    if content.endswith("\n"):
        output += "\n"
    return output


def require_gh() -> None:
    """Ensure the GitHub CLI is installed and authenticated."""
    if not shutil.which("gh"):
        fail("gh CLI is not on PATH. Install it and run 'gh auth login'.")
    result = run(["gh", "auth", "status"], check=False, capture=True)
    if result.returncode != 0:
        fail("gh CLI is not authenticated. Run 'gh auth login'.")


def current_branch() -> str:
    """Return the current Git branch name."""
    result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return result.stdout.strip()


def current_sha() -> str:
    """Return the current Git commit SHA."""
    result = run(["git", "rev-parse", "HEAD"], capture=True)
    return result.stdout.strip()


def validate_branch(branch: str) -> None:
    """Refuse to run on protected branches."""
    if branch == "main":
        fail("Smoke tests cannot run on main. Switch to develop or a feature branch.")
    if branch != "develop" and not branch.startswith("feature/"):
        fail(
            "Smoke tests are only supported on develop or feature/* branches, "
            f"not '{branch}'."
        )


def working_tree_is_clean() -> bool:
    """Return True if the working tree has no staged or unstaged changes."""
    result = run(["git", "status", "--porcelain"], capture=True)
    return result.stdout.strip() == ""


def bump_platform_files(paths: list[Path], *, dry_run: bool = False) -> list[Path]:
    """Add a smoke-test timestamp to each requested .platform file."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for path in paths:
        if not path.exists():
            fail(f"Platform file not found: {path}")
        original = path.read_text(encoding="utf-8")
        updated = bump_platform_content(original, timestamp)
        if dry_run:
            safe_print(f"[DRY RUN] would bump {path} with timestamp {timestamp}")
            print("\n--- Diff preview ---")
            for line in unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            ):
                print(line)
        else:
            path.write_text(updated, encoding="utf-8")
            safe_print(f"[BUMPED] {path} with timestamp {timestamp}")
    return paths


def commit_and_push(branch: str, paths: list[Path], dry_run: bool) -> str:
    """Stage, commit, and push the .platform changes. Return the commit SHA."""
    if dry_run:
        safe_print("[DRY RUN] would commit and push the .platform change(s)")
        return current_sha()

    run(["git", "add", *[str(p) for p in paths]])
    run(["git", "commit", "-m", SMOKE_COMMIT_MESSAGE])
    sha = current_sha()
    run(["git", "push", "origin", branch])
    safe_print(f"[PUSHED] commit {sha[:8]} to origin/{branch}")
    return sha


def find_orchestrator_run(branch: str, sha: str, timeout_seconds: int = 120) -> str:
    """Poll GitHub Actions until the orchestrator run for the SHA appears."""
    print("⏳ Waiting for orchestrator workflow run to start...")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = run(
            [
                "gh",
                "run",
                "list",
                "--workflow=orchestrator.yml",
                f"--branch={branch}",
                "--json=databaseId,headSha,status,conclusion,displayTitle",
                "--limit=10",
            ],
            capture=True,
            check=False,
        )
        if result.returncode != 0:
            time.sleep(5)
            continue
        try:
            runs = json.loads(result.stdout)
        except json.JSONDecodeError:
            time.sleep(5)
            continue
        for run_entry in runs:
            if run_entry.get("headSha") == sha:
                run_id = str(run_entry["databaseId"])
                print(f"🔍 Found orchestrator run: {run_id}")
                return run_id
        time.sleep(5)
    fail("Timed out waiting for orchestrator run to start.")


def watch_run(run_id: str) -> int:
    """Tail the workflow run and return gh's exit code."""
    print(f"👀 Watching workflow run {run_id}...")
    result = run(["gh", "run", "watch", run_id, "--exit-status"], check=False)
    return result.returncode


def fetch_job_details(run_id: str) -> list[dict[str, object]]:
    """Return the raw job list for a workflow run."""
    result = run(
        ["gh", "run", "view", run_id, "--json=jobs"],
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return data.get("jobs", [])


def fetch_job_log(run_id: str, job_id: int) -> str:
    """Fetch the plain-text log for a specific job."""
    result = run(
        ["gh", "run", "view", run_id, f"--job={job_id}", "--log"],
        capture=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def missing_fab_test(run_id: str, jobs: list[dict[str, object]]) -> set[str]:
    """Return job names whose logs show 'fab-test: command not found'."""
    missing: set[str] = set()
    for job in jobs:
        if job.get("conclusion") != "failure":
            continue
        job_id = job.get("databaseId")
        name = job.get("name", "")
        if not job_id or not name:
            continue
        log = fetch_job_log(run_id, int(job_id))
        if log and "fab-test: command not found" in log:
            missing.add(name)
    return missing


def _is_placeholder_matrix_job(name: str) -> bool:
    """Return True for placeholder matrix job names before substitution."""
    return "${{" in name and "}}" in name


def classify_results(
    run_id: str,
    jobs: list[dict[str, object]],
) -> tuple[set[str], set[str], set[str]]:
    """Classify jobs by whether their failure is acceptable or required."""
    conclusions = {
        job["name"]: job.get("conclusion", "unknown") for job in jobs
    }
    fab_test_missing = missing_fab_test(run_id, jobs)
    required_failures = set()
    acceptable_failures = set()
    unexpected_failures = set()

    for name, conclusion in conclusions.items():
        if conclusion == "success":
            continue
        if name in fab_test_missing or name in REQUIRED_INFRASTRUCTURE_JOBS:
            required_failures.add(name)
        elif name in ACCEPTABLE_FAILURE_JOBS:
            acceptable_failures.add(name)
        elif conclusion == "skipped" and _is_placeholder_matrix_job(name):
            # Placeholder matrix job skipped because no artifact matched.
            acceptable_failures.add(name)
        else:
            unexpected_failures.add(name)

    # Any required job that never ran is also a failure.
    ran_names = set(conclusions.keys())
    for required in REQUIRED_INFRASTRUCTURE_JOBS:
        if required not in ran_names:
            required_failures.add(required)

    return required_failures, acceptable_failures, unexpected_failures


def print_summary(
    run_id: str,
    required_failures: set[str],
    acceptable_failures: set[str],
    unexpected_failures: set[str],
) -> int:
    """Print the smoke test summary and return the exit code."""
    print("\n" + "=" * 80)
    print("Smoke Test Summary")
    print("=" * 80)
    print(f"Run ID: {run_id}")
    repo = os.getenv("GITHUB_REPOSITORY", "<owner>/<repo>")
    print(f"Workflow URL: https://github.com/{repo}/actions/runs/{run_id}")

    if acceptable_failures:
        safe_print(
            "\n[WARNING] Acceptable failures (tooling/workspace not configured):"
        )
        for name in sorted(acceptable_failures):
            print(f"  - {name}")

    if unexpected_failures:
        safe_print("\n[FAIL] Unexpected failures:")
        for name in sorted(unexpected_failures):
            print(f"  - {name}")

    if required_failures:
        safe_print("\n[FAIL] Required infrastructure failures:")
        for name in sorted(required_failures):
            print(f"  - {name}")

    if not required_failures and not unexpected_failures:
        safe_print(
            "\n[PASS] Orchestrator infrastructure is healthy. Smoke test passed."
        )
        return 0

    return 1


def revert_smoke_commit(branch: str) -> None:
    """Revert the most recent smoke test commit and push the revert."""
    head_message = run(["git", "log", "-1", "--pretty=%s"], capture=True).stdout.strip()
    if head_message != SMOKE_COMMIT_MESSAGE:
        fail(f"HEAD is not a smoke test commit ('{head_message}'). Refusing to revert.")
    run(["git", "revert", "HEAD", "--no-edit"])
    run(["git", "push", "origin", branch])
    safe_print("[REVERTED] smoke test commit and pushed the revert.")


def main(argv: list[str] | None = None) -> int:
    """Entry point for the orchestrator smoke test."""
    parser = argparse.ArgumentParser(
        description=(
            "Trigger the orchestrator workflow with a .platform change "
            "and watch it run."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the .platform change without committing or pushing.",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Revert the most recent smoke test commit instead of running a new test.",
    )
    parser.add_argument(
        "--artifact-type",
        choices=["semantic-model", "report", "both"],
        default="both",
        help=(
            "Which artifact type to bump. "
            "'semantic-model' exercises BPA, 'report' exercises PBIR Inspector, "
            "'both' exercises both analyzers (default)."
        ),
    )
    args = parser.parse_args(argv)

    require_gh()
    branch = current_branch()
    validate_branch(branch)

    if args.revert:
        revert_smoke_commit(branch)
        return 0

    if not args.dry_run and not working_tree_is_clean():
        fail(
            "Working tree is not clean. "
            "Commit or stash changes before running the smoke test."
        )

    paths = platform_paths_for(args.artifact_type)
    bump_platform_files(paths, dry_run=args.dry_run)

    if args.dry_run:
        safe_print("\n[DRY RUN] complete. No commit was made.")
        return 0

    sha = commit_and_push(branch, paths, args.dry_run)
    run_id = find_orchestrator_run(branch, sha)
    watch_run(run_id)
    jobs = fetch_job_details(run_id)
    required, acceptable, unexpected = classify_results(run_id, jobs)
    return print_summary(run_id, required, acceptable, unexpected)


if __name__ == "__main__":
    sys.exit(main())
