#!/usr/bin/env python3
"""Smoke test for the pql_test dynamic analyzer in GitHub Actions.

Bumps a harmless field in SampleModel-PQLAssert.SemanticModel/.platform, commits,
pushes to the current branch, watches the orchestrator workflow run, then verifies
the pql_test dynamic analyzer job executed inside the orchestrator run.
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

SMOKE_COMMIT_MESSAGE = "test(smoke): bump .platform to trigger pql_test smoke test"
REQUIRED_INFRASTRUCTURE_JOBS = {
    "Branch / Environment Guard",
    "Detect Changes / Detect Changed Artifacts",
    "Run CI/CD Pipeline / Prepare Artifact Matrix",
    "Constraint Enforcement Summary",
    "Pipeline Summary",
}
PLATFORM_PATH = Path(
    ".fabric/artifacts/SampleModel-PQLAssert.SemanticModel/.platform"
)


def platform_path() -> Path:
    """Return the .platform path to bump for the pql_test smoke test."""
    return PLATFORM_PATH


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


def bump_platform_file(*, dry_run: bool = False) -> Path:
    """Add a smoke-test timestamp to the SampleModel-PQLAssert .platform file."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = platform_path()
    if not path.exists():
        fail(f"Platform file not found: {path}")
    original = path.read_text(encoding="utf-8")
    updated = bump_platform_content(original, timestamp)
    if dry_run:
        print(f"[DRY RUN] would bump {path} with timestamp {timestamp}")
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
    return path


def commit_and_push(branch: str, *, dry_run: bool) -> str:
    """Stage, commit, and push the .platform change. Return the commit SHA."""
    if dry_run:
        print("[DRY RUN] would commit and push the .platform change")
        return current_sha()

    path = platform_path()
    run(["git", "add", str(path)])
    run(["git", "commit", "-m", SMOKE_COMMIT_MESSAGE])
    sha = current_sha()
    run(["git", "push", "origin", branch])
    print(f"[PUSHED] commit {sha[:8]} to origin/{branch}")
    return sha


def find_workflow_run(
    workflow: str, branch: str, sha: str, timeout_seconds: int = 120
) -> str:
    """Poll GitHub Actions until a run for the SHA appears."""
    print(f"[WAITING] for {workflow} run to start...")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = run(
            [
                "gh",
                "run",
                "list",
                f"--workflow={workflow}",
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
                print(f"[FOUND] {workflow} run: {run_id}")
                return run_id
        time.sleep(5)
    fail(f"Timed out waiting for {workflow} run to start.")


def watch_run(run_id: str) -> int:
    """Tail the workflow run and return gh's exit code."""
    print(f"[WATCHING] workflow run {run_id}...")
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


def classify_orchestrator_jobs(
    jobs: list[dict[str, object]],
) -> tuple[set[str], set[str]]:
    """Classify orchestrator jobs into required and acceptable failures."""
    conclusions = {job["name"]: job.get("conclusion", "unknown") for job in jobs}
    required_failures = set()
    acceptable_failures = set()

    for name, conclusion in conclusions.items():
        if conclusion == "success":
            continue
        if name in REQUIRED_INFRASTRUCTURE_JOBS:
            required_failures.add(name)
        else:
            acceptable_failures.add(name)

    for required in REQUIRED_INFRASTRUCTURE_JOBS:
        if required not in conclusions:
            required_failures.add(required)

    return required_failures, acceptable_failures





def find_pql_test_job(jobs: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the pql_test job for SampleModel-PQLAssert, if any."""
    for job in jobs:
        name = job.get("name", "")
        name_lower = name.lower()
        if (
            "pql_test" in name_lower or "pql-test" in name_lower
        ) and "SampleModel-PQLAssert" in name:
            return job
    return None


def revert_smoke_commit(branch: str) -> None:
    """Revert the most recent smoke test commit and push the revert."""
    head_message = run(["git", "log", "-1", "--pretty=%s"], capture=True).stdout.strip()
    if head_message != SMOKE_COMMIT_MESSAGE:
        fail(f"HEAD is not a smoke test commit ('{head_message}'). Refusing to revert.")
    run(["git", "revert", "HEAD", "--no-edit"])
    run(["git", "push", "origin", branch])
    print("[REVERTED] smoke test commit and pushed the revert.")


def main(argv: list[str] | None = None) -> int:
    """Entry point for the pql_test smoke test."""
    parser = argparse.ArgumentParser(
        description=(
            "Trigger the pql_test dynamic analyzer via the orchestrator workflow "
            "and verify the dynamic-validation job executes."
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

    bump_platform_file(dry_run=args.dry_run)

    if args.dry_run:
        print("\n[DRY RUN] complete. No commit was made.")
        return 0

    sha = commit_and_push(branch, dry_run=args.dry_run)

    orchestrator_run_id = find_workflow_run("orchestrator.yml", branch, sha)
    watch_run(orchestrator_run_id)
    orchestrator_jobs = fetch_job_details(orchestrator_run_id)
    required_failures, acceptable_failures = classify_orchestrator_jobs(
        orchestrator_jobs
    )

    if required_failures:
        safe_print("\n[FAIL] Required orchestrator jobs failed:")
        for name in sorted(required_failures):
            print(f"  - {name}")
        return 1

    pql_job = find_pql_test_job(orchestrator_jobs)

    print("\n" + "=" * 80)
    print("PQL Test Smoke Test Summary")
    print("=" * 80)
    repo = os.getenv("GITHUB_REPOSITORY", "<owner>/<repo>")
    print(f"Orchestrator run: https://github.com/{repo}/actions/runs/{orchestrator_run_id}")

    if pql_job is None:
        safe_print("\n[FAIL] pql_test job for SampleModel-PQLAssert was not found.")
        return 1

    status = pql_job.get("status", "unknown")
    conclusion = pql_job.get("conclusion", "unknown")
    safe_print("\n[PASS] pql_test job executed for SampleModel-PQLAssert.")
    print(f"   Status: {status}")
    print(f"   Conclusion: {conclusion}")
    print(
        "   Note: DAX assertion failures are reported by pql_test but do not fail "
        "this smoke test."
    )

    if acceptable_failures:
        print(
            "\n[WARNING] Acceptable orchestrator failures"
            " (tooling/workspace not configured):"
        )
        for name in sorted(acceptable_failures):
            print(f"  - {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
