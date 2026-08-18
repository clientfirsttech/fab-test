#!/usr/bin/env python3
"""CI annotations and PR review comments for analyzer findings.

This module emits GitHub Actions workflow commands (`::error::`, `::warning::`)
and optional PR review comments from analyzer envelopes. It is designed to be a
no-op outside of a GitHub Actions pull-request context.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ._analyzer_envelope import _is_error_severity, _is_warning_severity


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _is_ci() -> bool:
    return bool(_env("GITHUB_ACTIONS"))


def _pr_context() -> dict[str, str] | None:
    """Return PR context if running in a GitHub Actions PR."""
    event_name = _env("GITHUB_EVENT_NAME")
    if event_name not in ("pull_request", "pull_request_target"):
        return None
    ref = _env("GITHUB_REF")
    if not ref or not ref.startswith("refs/pull/"):
        return None
    pr_number = ref.split("/")[2]
    repo = _env("GITHUB_REPOSITORY")
    token = _env("GITHUB_TOKEN")
    if not repo or not token:
        return None
    return {
        "pr_number": pr_number,
        "repo": repo,
        "token": token,
        "api_url": _env("GITHUB_API_URL", "https://api.github.com"),
    }


def _format_finding_message(finding: dict[str, Any], analyzer: str) -> str:
    rule = (
        finding.get("rule")
        or finding.get("RuleName")
        or finding.get("RuleID")
        or finding.get("ruleId")
        or "unknown"
    )
    obj = finding.get("object") or finding.get("ObjectName") or ""
    msg = (
        finding.get("message")
        or finding.get("Message")
        or finding.get("description")
        or ""
    )
    if obj:
        return f"[{analyzer}] {rule} — {obj}: {msg}".strip()
    return f"[{analyzer}] {rule}: {msg}".strip()


def emit_workflow_annotations(
    envelope: dict[str, Any],
    artifact_path: str = "",
) -> None:
    """Emit ::error:: and ::warning:: annotations for findings.

    In GitHub Actions each finding becomes a workflow annotation. Outside CI
    this function prints nothing.
    """
    if not _is_ci():
        return

    findings = envelope.get("findings", [])
    analyzer = envelope.get("analyzer", "analyzer")
    for finding in findings:
        sev = finding.get("severity") or finding.get("Severity")
        message = _format_finding_message(finding, analyzer)
        if _is_error_severity(sev):
            print(f"::error::{message}")
        elif _is_warning_severity(sev):
            print(f"::warning::{message}")


def _post_pr_review_comment(context: dict[str, str], body: str) -> bool:
    """Post a single PR review comment using the GitHub API."""
    url = (
        f"{context['api_url']}/repos/{context['repo']}/"
        f"issues/{context['pr_number']}/comments"
    )
    payload = json.dumps({"body": body}).encode("utf-8")
    request = Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {context['token']}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status == 201
    except Exception as exc:
        print(f"::warning::Could not post PR review comment: {exc}")
        return False


def emit_pr_review_comments(
    envelope: dict[str, Any],
    artifact_path: str = "",
) -> None:
    """Post warning-level findings as PR review comments.

    Errors are left as workflow annotations only to avoid noisy PR comments for
    failures that already fail the build.
    """
    context = _pr_context()
    if not context:
        return

    analyzer = envelope.get("analyzer", "analyzer")
    artifact = Path(artifact_path).stem if artifact_path else "artifact"
    warnings = [
        f for f in envelope.get("findings", [])
        if _is_warning_severity(f.get("severity") or f.get("Severity"))
    ]
    if not warnings:
        return

    lines = [
        f"### ⚠️ {analyzer} warnings for `{artifact}`",
        "",
    ]
    for finding in warnings:
        lines.append(f"- {_format_finding_message(finding, analyzer)}")
    lines.append("")
    lines.append(
        "See uploaded workflow artifacts for the full envelope and native output."
    )
    _post_pr_review_comment(context, "\n".join(lines))
