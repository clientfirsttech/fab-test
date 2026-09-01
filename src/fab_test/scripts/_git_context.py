"""Repository identity: branch, commit, and actor for the run (HTML Report §2).

Shared by telemetry (`fab_test.py`) and the run-level HTML index
(`_report_html.py`), which both want to say who ran this and from where
without either reimplementing the CI-env-var-vs-local-git fallback. Kept
in its own module because `_report_html.py` must not import `fab_test.py`
-- that direction already runs the other way -- and duplicating the
fallback logic is how it would drift between the two consumers.
"""

import os
import subprocess


def git_command_output(cmd: list[str]) -> str:
    """Run a local git command and return trimmed stdout, or "" on any failure."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:  # noqa: BLE001 - boundary: git is optional context
        # Swallowed silently on purpose. This only enriches telemetry/reports
        # with the repository, branch, and actor, and every caller already
        # reads "" as "unknown". Warning here would fire on every run outside
        # a git checkout -- a normal way to use fab-test -- so the noise
        # would train people to ignore it.
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_context() -> dict[str, str]:
    """Return repository/branch/commit/actor context from GitHub Actions or git CLI.

    Falls back to local git for branch, commit, and actor (via
    ``git config user.email``) so context is still useful on local runs
    and self-hosted runners where ``GITHUB_*`` vars are empty, and reads
    as empty strings -- never raises -- outside a git checkout entirely.
    """
    ctx = {
        "repository": os.getenv("GITHUB_REPOSITORY", ""),
        "branch": os.getenv("GITHUB_REF_NAME", ""),
        "commit": os.getenv("GITHUB_SHA", ""),
        "actor": os.getenv("GITHUB_ACTOR", ""),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID", ""),
    }
    if not ctx["repository"]:
        remote = git_command_output(["git", "remote", "get-url", "origin"])
        ctx["repository"] = _repository_from_remote(remote)
    if not ctx["commit"]:
        ctx["commit"] = git_command_output(["git", "rev-parse", "HEAD"])
    if not ctx["branch"]:
        ctx["branch"] = git_command_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if not ctx["actor"]:
        ctx["actor"] = git_command_output(["git", "config", "user.email"])
    return ctx


def _repository_from_remote(remote_url: str) -> str:
    """Return ``owner/repo`` parsed from a git remote URL, or "" if it doesn't parse.

    Handles both the HTTPS (``https://github.com/owner/repo.git``) and SSH
    (``git@github.com:owner/repo.git``) forms a local ``origin`` remote may
    take, by normalizing the SSH colon to a slash and reading the last two
    path segments -- so the host and protocol in front of them don't matter.
    """
    trimmed = remote_url.strip().removesuffix(".git").rstrip("/")
    if not trimmed:
        return ""
    segments = trimmed.replace(":", "/").rsplit("/", 2)[-2:]
    if len(segments) != 2 or not all(segments):
        return ""
    return "/".join(segments)
