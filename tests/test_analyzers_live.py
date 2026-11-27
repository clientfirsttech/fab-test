"""Live analyzers: each one run locally and against the workspace, compared with a recording.

``fabric-artifacts/`` is the Git-connected folder of FAB_TEST_LIVE_WORKSPACE, so each item exists both
on disk and deployed. For pbir, a11y, bpa and rdl this runs the real CLI twice, on the local folder
and with ``--workspace`` (export, then analyze), and checks:

- every item's findings (rule, severity, object) match tests/fixtures/analyzers-live/<analyzer>.json,
  in each mode. The items carry defects on purpose, so a tester that stops seeing one fails here;
- local and service agree item by item, so an export that changes what an analyzer sees fails too.

Opt-in: skips unless FAB_TEST_LIVE_WORKSPACE is set (`.github/workflows/live-ci.yml` sets it). To
re-record after an intended change, run with FAB_TEST_LIVE_RECORD=1 and review the fixture diff.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from .test_playwright_generation_parity_live import _credentials_present

pytestmark = [pytest.mark.integration, pytest.mark.analyzers]

_ROOT = Path(__file__).resolve().parent.parent
_WORKSPACE = os.environ.get("FAB_TEST_LIVE_WORKSPACE", "")
_RECORD = os.environ.get("FAB_TEST_LIVE_RECORD") == "1"
_FIXTURES = Path(__file__).parent / "fixtures" / "analyzers-live"
# The slicer contract's calendar rules resolve against a date; pin it so the recording holds.
_AS_OF = "2026-11-23"
_COMPLETED = ("passed", "warning", "failed")  # error or skipped: the tester did not work
_EXTRA = {"pbir": ["--as-of", _AS_OF], "rdl": ["--all"]}
# Local names that collide (ACC-03.rdl beside ACC-03.PaginatedReport) get suffixed stems.
_LOCAL_ONLY_STEMS = {"rdl": {"ACC-03"}}
# Items whose local and service runs differ for a known product gap, each with its epic. A ratchet:
# when the gap closes the agreement test fails, asking for the entry to go.
_KNOWN_GAPS = {
    # pbir --workspace skips slicer contracts: an exported report has no logicalId to pair on.
    # tasks/service-mode-parity-epic.md
    "pbir": {"SampleModel-DefaultState"},
}
_ANALYZERS = [
    "pbir", "a11y", "rdl",
    pytest.param("bpa", marks=pytest.mark.skipif(sys.platform != "win32",
                                                 reason="Tabular Editor runs on Windows only")),
]

pytestmark.append(pytest.mark.skipif(
    not (_WORKSPACE and _credentials_present()),
    reason="opt-in: set FAB_TEST_LIVE_WORKSPACE and a service principal (FABRIC_TENANT_ID, FABRIC_CLIENT_ID, "
           "FABRIC_CLIENT_SECRET, or .fab-test/.env)",
))


def _fab_test(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "fab_test.scripts.fab_test", *args], cwd=_ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def _tail(proc: subprocess.CompletedProcess) -> str:
    return f"exit {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"


@pytest.fixture(scope="module")
def out_root():
    # Short on purpose: a deployed report's export nests deep enough to pass Windows' 260-character limit.
    root = Path(tempfile.mkdtemp(prefix="ft-"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


@functools.cache
def _run(analyzer: str, mode: str, out_root: Path) -> dict[str, dict]:
    """Run once per analyzer and mode; return {item: {status, findings}}."""
    output = out_root / mode
    source = ["--artifact-dir", "fabric-artifacts"] if mode == "local" else ["--workspace", _WORKSPACE]
    proc = _fab_test(analyzer, *source, *_EXTRA.get(analyzer, []), "-q", "--output-dir", str(output))
    assert proc.returncode in (0, 1), f"{analyzer} {mode}: not findings but a failure\n{_tail(proc)}"
    items = {}
    for path in sorted((output / analyzer).glob("*/envelope.json")):
        envelope = json.loads(path.read_text(encoding="utf-8-sig"))
        items[path.parent.name] = {
            "status": envelope["status"],
            "findings": sorted([f.get("rule"), f.get("severity"), str(f.get("object"))]
                               for f in envelope.get("findings") or []),
        }
    assert items, f"{analyzer} {mode}: no envelopes\n{_tail(proc)}"
    broken = sorted(name for name, item in items.items() if item["status"] not in _COMPLETED)
    assert not broken, f"{analyzer} {mode}: items did not complete: {broken}"
    return items


def _differences(recorded: dict, actual: dict) -> list[str]:
    problems = [f"  missing item {name}" for name in sorted(set(recorded) - set(actual))]
    problems += [f"  unexpected item {name}" for name in sorted(set(actual) - set(recorded))]
    for name in sorted(set(recorded) & set(actual)):
        want, got = recorded[name], actual[name]
        if want["status"] != got["status"]:
            problems.append(f"  {name}: recorded {want['status']}, got {got['status']}")
        lost = [f for f in want["findings"] if f not in got["findings"]]
        new = [f for f in got["findings"] if f not in want["findings"]]
        problems += [f"  {name}: no longer finds {f}" for f in lost]
        problems += [f"  {name}: now also finds {f}" for f in new]
    return problems


@pytest.mark.parametrize("mode", ["local", "service"])
@pytest.mark.parametrize("analyzer", _ANALYZERS)
def test_findings_match_the_recording(analyzer, mode, out_root):
    actual = _run(analyzer, mode, out_root)
    fixture = _FIXTURES / f"{analyzer}.json"
    if _RECORD:
        recording = json.loads(fixture.read_text(encoding="utf-8")) if fixture.is_file() else {}
        recording.update({"workspace": _WORKSPACE, "as_of": _AS_OF, mode: actual})
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(json.dumps(recording, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip(f"recorded {fixture.name} ({mode})")
    problems = _differences(json.loads(fixture.read_text(encoding="utf-8"))[mode], actual)
    assert not problems, f"{analyzer} {mode}: findings differ from the recording\n" + "\n".join(problems)


@pytest.mark.parametrize("analyzer", _ANALYZERS)
def test_local_and_service_agree(analyzer, out_root):
    local, service = _run(analyzer, "local", out_root), _run(analyzer, "service", out_root)
    unmatched = set(service) - set(local) - _LOCAL_ONLY_STEMS.get(analyzer, set())
    assert not unmatched, f"{analyzer}: deployed items with no local counterpart: {sorted(unmatched)}"
    differ = {name for name in set(local) & set(service) if local[name] != service[name]}
    known = _KNOWN_GAPS.get(analyzer, set())
    assert not differ - known, f"{analyzer}: local and service disagree on {sorted(differ - known)}"
    assert not known - differ, (f"{analyzer}: {sorted(known - differ)} now agree; the gap is fixed, "
                                "so remove it from _KNOWN_GAPS")


def test_rdl_refuses_a_workspace_over_the_item_limit():
    """The workspace holds 68 paginated reports, past the 50-item limit: refuse before exporting any."""
    proc = _fab_test("rdl", "--workspace", _WORKSPACE, "--dry-run")
    assert proc.returncode == 2, _tail(proc)
    assert "--all" in proc.stdout + proc.stderr, _tail(proc)
