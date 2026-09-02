# pql-test Connection-Failure Reporting Epic

**Status**: ✅ COMPLETED (2026-09-02) — 5/5 tasks, verified live through the installed CLI against real artifacts.
**Goal**: A `pql-test` run that never connects to a model reports `skipped`, not `failed`.

## Overview

When `pql-test` cannot connect to the target model — most commonly a local Desktop
session that closed or never opened — it produces no test results at all. Today
`invoke_pql_test.py`'s `_pql_status()` only classifies a run as `skipped` when the
native output reports a non-zero `total` with every test skipped. A connection
failure has `total == 0`, so it falls through to the generic `failed` branch and
reports `"pql-test failed: 0 tests, 0 passed, 0 failed, 0 skipped"` — a message
that says "failed" while admitting nothing ran. This mirrors the existing
missing-credentials-against-remote case (vision.md: platform gaps degrade to
skips), so it should degrade the same way.

---

## 1. Report Zero-Result Runs as Skipped

Classify a run with no test results and a non-zero exit code as `skipped` rather
than `failed`, since there is nothing to report as a finding.

**Requirements**:
- Given `pql-test` exits non-zero with no parsed test results (no native output,
  or native output with zero total tests), should report status `skipped` with a
  message that says so (not "0 tests, 0 passed...failed").
- Given `pql-test` exits non-zero with parsed test results present (a real test
  failure), should still report status `failed` — unchanged from today.
- Given `pql-test` exits 0 with no test results, should keep existing behavior
  (`passed`, per current `_pql_status` logic — unaffected by this change).

**Files**: `src/fab_test/scripts/invoke_pql_test.py` (`_pql_status`)
**Tests**: `pytest -m pql_test tests/test_invoke_pql_test.py`

---

## 2. Cache Desktop Detection Within a Single Run

Detecting which file a running Power BI Desktop instance has open shells out
to PowerShell (`Get-CimInstance Win32_Process`), which costs real wall-clock
time. `_preflight()` calls this once per artifact for a `local/` target, and
`build_pql_test_command()` calls it again afterward — so a run against
several artifacts pays that PowerShell cost repeatedly for a state (which
Desktop instance has which file open) that cannot change meaningfully within
one CLI invocation.

**Requirements**:
- Given `detect_desktop_instances()` is called more than once in the same
  process with the same workspaces root, should invoke the PowerShell lookup
  at most once and reuse the result.
- Given detection was already cached and a caller passes a different
  workspaces root (e.g. a test with a different `tmp_path`), should detect
  independently rather than returning the wrong root's result.

**Files**: `src/fab_test/scripts/_desktop.py` (`detect_desktop_instances`)
**Tests**: `pytest -m fab_test tests/test_desktop_detection.py`

---

## 3. Recognize a Connection-Refused Result as Skipped, Not Failed

Task 1 assumed a connection failure produces zero test results. A real run
against a closed Desktop file shows otherwise: `pql-test` discovers its 8
tests **statically** from the `.SemanticModel`'s PQL definitions (no live
connection needed to enumerate them), then tries to execute each one, and
each execution fails with an `AdomdConnectionException` ("A connection
cannot be made... target machine actively refused"). `pql-test` reports
these as ordinary `passed: false, skipped: false` results with the
exception text in `error` — so `total=8, failed=8`, which task 1's
`total == 0` check does not catch, and `_pql_status` reports `failed`.

**Requirements**:
- Given every failing result's `error` field is a connection-refused/
  cannot-connect signature (ADOMD "A connection cannot be made"), should
  report status `skipped`, not `failed`.
- Given at least one failing result is a genuine assertion failure (no
  connection-error signature), should still report `failed` — a real
  failure must never be hidden behind a platform-availability skip, even
  when other failures in the same run are connection errors.

**Files**: `src/fab_test/scripts/invoke_pql_test.py` (`_pql_status`)
**Tests**: `pytest -m pql_test tests/test_invoke_pql_test.py`

---

## 4. Report Nothing Ran, and Warn About It

Task 3 reclassified the run but left `test_summary` as pql-test wrote it, so
the summary line read `8 tests, 0 passed, 8 failed, 0 skipped` under a
skipped run — the status and the counts contradicted each other, and the
counts are what a reader believes.

The count of 8 comes from pql-test discovering tests statically from the
model's TMDL/`DAXQueries` files, which it can do without a connection. But
none of those 8 executed, so reporting any number of tests overstates what
happened: the honest count is zero. And a run where nothing executed is not
a green pass — a developer who thinks their tests ran when they did not is
worse off than one who is told nothing ran. `warning` already exists as an
envelope status (pbir-a11y uses it): yellow in the table, `::warning::` in
CI, exit code 0.

**Requirements**:
- Given no test actually executed because the model was unreachable, should
  report zero counts (`0 tests, 0 passed, 0 failed, 0 skipped`) rather than
  the statically-discovered count.
- Given the same run, should report status `warning` — not `passed`, not
  `skipped`, not `failed` — and still exit 0 so a platform gap does not turn
  CI red.
- Given the same run, should render as a warning rather than a green check
  in both the per-artifact line and the aggregate summary table.

**Files**: `src/fab_test/scripts/invoke_pql_test.py`,
`src/fab_test/scripts/fab_test_summary.py` (`_artifact_status`,
`_artifact_summary_prefix`)
**Tests**: `pytest -m pql_test tests/test_invoke_pql_test.py`,
`pytest -m fab_test tests/test_fab_test_summary.py`

---

## 5. A Clean Exit That Ran Nothing Is Not a Pass

`_pql_status` asked "did it pass?" before "did anything run?": its first
check was `returncode == 0 and not findings → passed`, so an artifact whose
model was never reached — or which declares no tests at all — reported
`✅ pql-test passed: 0 tests, 0 passed, 0 failed, 0 skipped`. Zero tests
passing is not a pass, and that green check is precisely how a developer
comes to believe their tests ran when none did.

**Requirements**:
- Given pql-test exits cleanly having run no tests, should report `warning`
  rather than `passed`, naming that no tests were found to run.
- Given pql-test exits non-zero having run no tests, should report
  `warning` rather than `passed` or `failed`.
- Given tests actually ran and passed, should still report `passed`.

**Files**: `src/fab_test/scripts/invoke_pql_test.py` (`_pql_status`)
**Tests**: `pytest -m pql_test tests/test_invoke_pql_test.py`

---

## Closeout (2026-09-02)

All five tasks implemented and verified. Tasks 1 and 3 were superseded in part by
tasks 4 and 5: a run that reached no tests reports `warning`, not `skipped` —
`skipped` stays reserved for a run pql-test itself reported as all-skipped, and
`warning` covers "nothing executed", so a zero-count line can never sit under a
green check. `_pql_status`'s ordering encodes that: "did anything run?" is asked
before "did it pass?"

Verified through the real entry point across every caller of the changed code
(vision.md Blast Radius):

| Caller | Observed |
|--------|----------|
| `fab-test pql-test` | `⚠️ pql-test found no tests to run in this model`, exit 0 |
| `fab-test pql-test --report` | `index.html` status column reads `warning` |
| `fab-test local` | `⚠️` on the zero-run artifact, `❌` on the genuinely failing one |
| `fab-test all` | aggregate table renders `warning` alongside `FAILED` rows |
| `fab-test doctor --local` | unaffected by the `detect_desktop_instances` cache |

A real assertion failure still fails: the same run reported
`SampleModel-PQLAssert — 86 tests, 78 passed, 8 failed` as `FAILED` with exit 1,
confirming a genuine failure is never hidden behind the platform skip.

**1681 passed, 3 skipped**, coverage **88%**, `ruff check src/` clean.
Documented for all three callers: README (local workflow), `docs/QUICK-VALIDATION.md`
(the CI snippet's degradation note, which still said `skipped`),
`references/flags.md` (pql-test connection semantics as a SudoLang `Constraints`
block), and `references/operations.md` (the envelope `status` list had only four
of the seven values the code emits) — both authored and packaged skill copies in
sync per `tests/test_skill_resource.py`.

**Found, not fixed** (pre-existing, out of scope): `--output-dir` is not honored
for `native.json`. `native_output_path` resolves through `results_dir`, which
reads the fixed results root, so an envelope lands under `--output-dir` while its
native output lands under `fab-test-results/`. Consistent across all six
analyzer wrappers, so it is a design question, not a regression from this epic.
