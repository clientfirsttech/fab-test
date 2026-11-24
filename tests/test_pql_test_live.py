"""Live pql-test: the real CLI against a deployed semantic model, compared with a recording.

The unit tests stub pql-test and the service; this runs ``fab-test pql-test`` through its own entry
point against SampleModel-PQLAssert, a model built to contain failing tests, and checks every test
passes or fails exactly as recorded in tests/fixtures/pql-test-live/. pql-test is deterministic, so
a difference is a regression in fab-test, pql-test or the model, never noise; and because the model
fails on purpose, a run that reports everything passing (a tester that can't see a failure) fails too.

Opt-in: skips unless PQL_TEST_WORKSPACE is set, since querying the model needs its Fabric capacity
running. `.github/workflows/live-ci.yml` sets it. To re-record after an intended change, run the
command below and copy each test's suite_name, test_name and passed into the fixture.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from .test_playwright_generation_parity_live import _credentials_present

pytestmark = [pytest.mark.pql_test, pytest.mark.integration]

_WORKSPACE = os.environ.get("PQL_TEST_WORKSPACE", "")
_RECORDING = json.loads((Path(__file__).parent / "fixtures" / "pql-test-live" / "SampleModel-PQLAssert.json")
                        .read_text(encoding="utf-8"))

pytestmark.append(pytest.mark.skipif(
    not (_WORKSPACE and _credentials_present()),
    reason="opt-in: set PQL_TEST_WORKSPACE and a service principal (FABRIC_TENANT_ID, FABRIC_CLIENT_ID, "
           "FABRIC_CLIENT_SECRET, or .fab-test/.env); querying the model needs a running Fabric capacity",
))


def _fab_test(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "fab_test.scripts.fab_test", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def _tail(proc: subprocess.CompletedProcess) -> str:
    return f"exit {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"


def test_dry_run_lists_the_deployed_model():
    proc = _fab_test("pql-test", "--workspace", _WORKSPACE, "--dry-run")
    assert proc.returncode == 0, _tail(proc)
    assert f"{_RECORDING['model']}.SemanticModel" in proc.stdout, _tail(proc)


def test_every_test_passes_or_fails_as_recorded(tmp_path):
    target = f"{_WORKSPACE}.Workspace/{_RECORDING['model']}.SemanticModel"
    proc = _fab_test("pql-test", target, "--report", "--output-dir", str(tmp_path))
    envelopes = list(tmp_path.rglob("envelope.json"))
    assert len(envelopes) == 1, f"expected one envelope, found {envelopes}\n{_tail(proc)}"
    envelope = json.loads(envelopes[0].read_text(encoding="utf-8-sig"))
    assert envelope["status"] == "failed", f"the model fails on purpose: {envelope['message']}\n{_tail(proc)}"
    assert proc.returncode == 1, _tail(proc)

    actual = {(r["suite_name"], r["test_name"]): r["passed"] for r in envelope.get("test_results") or []}
    problems = []
    for row in _RECORDING["results"]:
        key = (row["suite_name"], row["test_name"])
        if key not in actual:
            problems.append(f"  missing {key}")
        elif actual.pop(key) != row["passed"]:
            problems.append(f"  {key}: recorded {'pass' if row['passed'] else 'fail'}, "
                            f"got {'fail' if row['passed'] else 'pass'}")
    problems.extend(f"  unexpected {key}" for key in actual)
    assert not problems, "outcomes differ from the recording\n" + "\n".join(problems)
    assert (envelopes[0].parent / "report.html").is_file(), "--report wrote no report"
