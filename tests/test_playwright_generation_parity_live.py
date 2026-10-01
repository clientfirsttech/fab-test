"""Live parity: what the real CLI generates against the dev workspace.

The replayed test beside this one
(``tests/test_playwright_generation_parity.py``) proves the generator turns
recorded discovery responses into the golden matrix. It cannot notice the
recordings themselves going stale -- a page added, a bookmark renamed, an API
shape changed. This does, by driving ``fab-test playwright --plan-only``
through the installed console script once per report and diffing what it
writes against the same golden CSVs.

Skips, loudly, without service-principal credentials for the dev tenant. It
is marked ``integration`` as well as ``playwright`` so the coverage-gated
default suite never waits on the network.
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .test_playwright_generation_parity import (
    GOLDEN_CSVS,
    PARITY_FIELDS,
    _describe,
    _golden_keys,
)

pytestmark = [pytest.mark.playwright, pytest.mark.integration]

_REQUIRED_CREDENTIALS = ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET")


def _credentials_present() -> bool:
    """Whether a service principal is reachable from the environment or .env."""
    if all(os.environ.get(name) for name in _REQUIRED_CREDENTIALS):
        return True
    env_file = Path(".fab-test/.env")
    if not env_file.exists():
        return False
    text = env_file.read_text(encoding="utf-8")
    return all(f"{name}=" in text and f"{name}=\n" not in text for name in _REQUIRED_CREDENTIALS)


def _golden_target(csv_path: Path) -> dict[str, str]:
    """Read the workspace, report, and RLS user the golden CSV pins."""
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return {
        "workspace_id": rows[0]["workspace_id"],
        "report_name": rows[0]["report_name"],
        "user_name": next((row["user_name"] for row in rows if row.get("user_name")), ""),
    }


def _run_plan_only(target: dict[str, str], output_dir: Path) -> Path:
    """Drive the real CLI for one report and return its test-cases.csv."""
    env = dict(os.environ)
    # Set only for the RLS reports, and only from what the golden CSV already
    # states -- an RLS run with no effective identity is refused before any
    # matrix is written.
    if target["user_name"]:
        env["PLAYWRIGHT_USER_NAME"] = target["user_name"]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fab_test.scripts.fab_test",
            "playwright",
            "--artifact",
            target["report_name"],
            "--workspace-id",
            target["workspace_id"],
            "--plan-only",
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"{target['report_name']}: plan-only run failed\n{result.stdout}\n{result.stderr}"
    )

    written = list(output_dir.rglob("test-cases.csv"))
    assert len(written) == 1, (
        f"{target['report_name']}: expected one test-cases.csv, found {written}"
    )
    return written[0]


@pytest.mark.skipif(
    not _credentials_present(),
    reason=(
        "needs a dev-tenant service principal: set FABRIC_TENANT_ID, "
        "FABRIC_CLIENT_ID, and FABRIC_CLIENT_SECRET (or fill .fab-test/.env)"
    ),
)
@pytest.mark.parametrize("csv_path", GOLDEN_CSVS, ids=lambda p: p.stem)
def test_live_matrix_matches_the_golden_csv(csv_path: Path, tmp_path: Path) -> None:
    """Given the real dev workspace, should generate exactly the combinations
    the golden CSV lists. A difference means the recorded fixtures have gone
    stale against the live API -- which is the only thing this test is here
    to notice."""
    target = _golden_target(csv_path)
    produced = _run_plan_only(target, tmp_path)

    with open(produced, newline="", encoding="utf-8") as fh:
        actual = {
            tuple((row.get(field) or "") for field in PARITY_FIELDS)
            for row in csv.DictReader(fh)
        }
    expected = _golden_keys(csv_path)

    missing = expected - actual
    extra = actual - expected
    assert not missing and not extra, (
        f"{csv_path.stem}: the live run differs from the golden CSV -- "
        "re-record with tools/record_playwright_parity_fixtures.py if the dev "
        "environment changed on purpose\n"
        f"  missing ({len(missing)}):\n{_describe(missing)}\n"
        f"  unexpected ({len(extra)}):\n{_describe(extra)}"
    )
