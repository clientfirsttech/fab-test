# pql-test Connection-Failure Reporting Epic

**Status**: 📋 PLANNED
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
