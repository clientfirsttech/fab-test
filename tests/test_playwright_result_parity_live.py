"""Live result parity: does every dev-environment case pass or fail as the reference did?

Runs ``fab-test playwright`` through the installed console script once per
report -- six interactive, four paginated -- pinned to the dev workspace, and
compares each case's ``test_results`` status with its expectation from
``test_playwright_result_parity.expectations()``. A mismatch names the case,
both outcomes, and fab-test's own recorded reason.

Renders every case in a real browser, so it takes several minutes. Skips
without dev-tenant credentials; marked ``integration`` so the coverage-gated
default suite never runs it.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest

from .test_playwright_generation_parity_live import _credentials_present
from .test_playwright_result_parity import FIXTURE_DIR, expectations, parameters_key

pytestmark = [pytest.mark.playwright, pytest.mark.integration]

DEV_WORKSPACE_ID = "c4698d28-b05c-40bc-926c-707563ac85e7"

_BY_REPORT = defaultdict(list)
for _expectation in expectations():
    _BY_REPORT[_expectation.report_name].append(_expectation)


def _rls_user(report_name: str) -> str:
    """The effective-identity user the report's golden CSV was captured with."""
    for csv_path in FIXTURE_DIR.glob("*.csv"):
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if row["report_name"] == report_name and row.get("user_name"):
                    return row["user_name"]
    return ""


def _run(report_name: str, output_dir: Path) -> list[dict]:
    """Run one report through the real CLI and return its test_results rows."""
    env = dict(os.environ)
    user = _rls_user(report_name)
    if user:
        env["PLAYWRIGHT_USER_NAME"] = user
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fab_test.scripts.fab_test",
            "playwright",
            "--artifact",
            report_name,
            "--workspace-id",
            DEV_WORKSPACE_ID,
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    envelopes = list(output_dir.rglob("envelope.json"))
    assert len(envelopes) == 1, (
        f"{report_name}: expected one envelope, found {envelopes}\n"
        f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )
    return json.loads(envelopes[0].read_text(encoding="utf-8")).get("test_results", [])


@pytest.mark.skipif(
    not _credentials_present(),
    reason=(
        "needs a dev-tenant service principal: set FABRIC_TENANT_ID, "
        "FABRIC_CLIENT_ID, and FABRIC_CLIENT_SECRET (or fill .fab-test/.env)"
    ),
)
@pytest.mark.parametrize("report_name", sorted(_BY_REPORT))
def test_live_outcomes_match_the_reference(report_name: str, tmp_path: Path) -> None:
    """Given a dev report, should pass exactly the cases the reference passed
    and fail exactly the ones it failed."""
    rows = _run(report_name, tmp_path)
    actual = {
        (
            row.get("suite_name", ""),
            row.get("page_name", "") or "",
            row.get("bookmark_name", "") or "",
            row.get("role", "") or "",
            parameters_key(row.get("parameters") or []),
        ): row
        for row in rows
    }

    problems = []
    for expectation in _BY_REPORT[report_name]:
        row = actual.pop(expectation.key, None)
        if row is None:
            problems.append(f"  missing case {expectation.key}")
            continue
        status = "pass" if row["status"] == "pass" else "fail"
        if status != expectation.expected_status:
            problems.append(
                f"  {expectation.key}: expected {expectation.expected_status}, got {status} "
                f"-- {row.get('actual', '')[:200]}"
            )
    problems.extend(f"  unexpected case {key}" for key in actual)

    assert not problems, f"{report_name}: outcomes differ from the reference\n" + "\n".join(
        problems
    )
