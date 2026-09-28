"""Contract tests for `fab-test playwright --plan-only`.

`--plan-only` answers "what would this run test?" without minting an embed
token or opening a browser. It is what the parity check and the fixture
recorder drive, and the cheapest way for a human or an agent to see the
matrix before spending minutes rendering it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from fab_test.scripts import invoke_playwright
from fab_test.scripts.fab_test_registry import build_playwright_command
from fab_test.scripts.playwright_validation.config import PlaywrightValidationConfig
from fab_test.scripts.playwright_validation.test_cases import (
    DiscoveredBookmark,
    DiscoveredPage,
)

pytestmark = pytest.mark.playwright


@pytest.fixture
def config() -> PlaywrightValidationConfig:
    """Return a resolved config for one interactive report."""
    return PlaywrightValidationConfig(
        workspace_id="ws-1",
        report_id="rpt-1",
        report_name="SalesReport",
        dataset_id="ds-1",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=60,
        headless=True,
        report_type="report",
    )


def _args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    """Build the namespace `_run_single_report` reads."""
    defaults = {
        "pages": "auto",
        "roles": "auto",
        "plan_only": True,
        "test_cases_dir": str(tmp_path / "test-cases"),
        "output_path": str(tmp_path / "envelope.json"),
        "verbose": 0,
        "workers": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _discovered() -> tuple[list[DiscoveredPage], list[str]]:
    return (
        [
            DiscoveredPage(
                page_id="p1",
                page_name="Page 1",
                bookmarks=[DiscoveredBookmark("b1", "Bookmark 1")],
            )
        ],
        [],
    )


def test_plan_only_writes_the_matrix_without_minting_a_token(
    config: PlaywrightValidationConfig, tmp_path: Path
) -> None:
    """Given --plan-only, should discover and write the test cases but never
    acquire an embed token or launch a browser."""
    args = _args(tmp_path)

    with (
        patch.object(invoke_playwright, "resolve_discovery", return_value=_discovered()),
        patch.object(invoke_playwright, "acquire_embed_configs") as acquire,
        patch.object(invoke_playwright, "subprocess") as sub,
    ):
        exit_code = invoke_playwright._run_single_report(config, args)

    assert exit_code == 0
    acquire.assert_not_called()
    sub.run.assert_not_called()

    csv_path = tmp_path / "test-cases" / "test-cases.csv"
    assert csv_path.exists()
    assert "Bookmark 1" in csv_path.read_text(encoding="utf-8")


def test_plan_only_writes_an_envelope_a_caller_already_parses(
    config: PlaywrightValidationConfig, tmp_path: Path
) -> None:
    """Given --plan-only, should write the same envelope shape a real run
    writes, marked skipped -- a plan is not a passing test run."""
    args = _args(tmp_path)

    with (
        patch.object(invoke_playwright, "resolve_discovery", return_value=_discovered()),
        patch.object(invoke_playwright, "acquire_embed_configs"),
    ):
        invoke_playwright._run_single_report(config, args)

    envelope = json.loads((tmp_path / "envelope.json").read_text(encoding="utf-8"))
    assert envelope["status"] == "skipped"
    assert envelope["analyzer"] == "playwright"
    assert "plan" in envelope["message"].lower()


def test_a_run_without_plan_only_still_embeds(
    config: PlaywrightValidationConfig, tmp_path: Path
) -> None:
    """Given no --plan-only, should behave exactly as before -- the flag is
    additive, not a change to the default path."""
    args = _args(tmp_path, plan_only=False)

    with (
        patch.object(invoke_playwright, "resolve_discovery", return_value=_discovered()),
        patch.object(
            invoke_playwright, "acquire_embed_configs", return_value={"": {}}
        ) as acquire,
        patch.object(invoke_playwright, "_run_pytest") as run_pytest,
    ):
        run_pytest.return_value.returncode = 0
        run_pytest.return_value.stdout = ""
        invoke_playwright._run_single_report(config, args)

    acquire.assert_called_once()
    run_pytest.assert_called_once()


def test_plan_only_reaches_the_subprocess_command_only_when_asked(
    tmp_path: Path,
) -> None:
    """Given --plan-only on the CLI, should be forwarded to the wrapper; given
    no flag, should be absent so today's invocation is byte-for-byte unchanged."""
    artifact = tmp_path / "SalesReport.Report"
    base = {
        "playwright_env_file": None,
        "environment": "",
        "workspace_id": "",
        "impact_manifest": None,
    }

    planned = build_playwright_command(
        artifact, argparse.Namespace(plan_only=True, **base), tmp_path
    )
    normal = build_playwright_command(
        artifact, argparse.Namespace(plan_only=False, **base), tmp_path
    )

    assert "--plan-only" in planned
    assert "--plan-only" not in normal


@pytest.mark.fab_test
def test_plan_only_is_rejected_by_an_analyzer_with_no_matrix() -> None:
    """Given --plan-only on an analyzer that has no matrix to plan, should
    fail with argparse's usage error rather than accept and ignore it."""
    result = subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "bpa", "--plan-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 2
    assert "--plan-only" in (result.stderr or "")


@pytest.mark.fab_test
def test_dry_run_wins_when_both_flags_are_passed(tmp_path: Path) -> None:
    """Given --dry-run and --plan-only together, should take the cheaper one:
    list the matching artifacts and make no discovery call, rather than
    silently ignoring one of the two."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fab_test.scripts.fab_test",
            "playwright",
            "--dry-run",
            "--plan-only",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "dry run" in result.stdout.lower()
    assert "📐 Matrix" not in result.stdout
    assert not list(tmp_path.rglob("test-cases.csv"))


def test_a_paginated_report_is_planned_with_its_dataset_and_parameter_set(
    config: PlaywrightValidationConfig, tmp_path: Path
) -> None:
    """Given a paginated report, should take the dataset and parameter set its
    plan resolved -- one baseline and one parameterized case, each carrying
    the dataset GenerateToken needs."""
    import dataclasses

    from fab_test.scripts.playwright_validation.discovery import PaginatedPlan

    paginated = dataclasses.replace(config, report_type="paginated", dataset_id="")
    plan = PaginatedPlan(
        dataset_id="ds-remote",
        parameter_sets=[[{"name": "ReportParameter1", "value": "2"}]],
    )

    with patch.object(invoke_playwright, "resolve_paginated_plan", return_value=plan):
        invoke_playwright._run_single_report(paginated, _args(tmp_path))

    csv_text = (tmp_path / "test-cases" / "test-cases.csv").read_text(encoding="utf-8")
    rows = list(__import__("csv").DictReader(csv_text.splitlines()))
    assert [row["dataset_id"] for row in rows] == ["ds-remote", "ds-remote"]
    assert [json.loads(row["report_parameters"]) for row in rows] == [
        [],
        [{"name": "ReportParameter1", "value": "2"}],
    ]
