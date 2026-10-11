# Doctor Severity Epic

**Status**: ✅ IMPLEMENTED 2026-10-10 (5/5 tasks, gates passed). Added during the work: a tool fetched on first run ("not yet downloaded/built/installed") is ℹ, not ❌, so a fresh CI runner's `doctor` is not failed by a tool it will download; the example and demo workflows gate on `doctor --analyzer playwright`.
**Goal**: `fab-test doctor` says what is actually missing, separates "broken" from "not set up", and exits non-zero only when a run you configured would fail.

## Overview

With no workspace found, `doctor` reported "no workspace or credentials resolved" without ever probing credentials, and told a machine with a working service principal (or `az login`) to set service-principal variables. Every non-ready row was ❌, so a developer who never meant to use the service saw the same mark as a broken install, and doctor exited 0 whenever any one analyzer was ready, so a broken playwright setup still passed in CI.

Severity follows intent and consequence:

| Status | Meaning | Exit |
|---|---|---|
| ✅ ready | the run will work | 0 |
| ⚠ warning | half set up: it will be skipped, test nothing, or fail until one more thing is set | 0 (1 with `--strict`) |
| ℹ info | optional and not set up; nothing is broken | 0 |
| ❌ error | you set it up (a workspace, part of a service principal, a tool) and the run will fail | 1 |

Observed 2026-10-10 against fab-test [Dev]: with no workspace, `pql-test` runs and reports 0 tests per model (⚠); `playwright` with a service principal but no workspace exits 1; `playwright` with only `az login` exits 127 (it needs a service principal for the embed token).

---

## Honest cloud readiness

Move `_cloud_readiness` out of `fab_test_registry.py` (over its size budget) into `_cloud_readiness.py`, and give every readiness row a `status`.

**Requirements**:
- Given a full service principal and no workspace, should be ⚠ with a reason naming where the credentials came from and that no workspace is set, and a remediation naming only the workspace sources
- Given only an ambient credential (or none) and no workspace, should be ℹ "not configured", with a remediation naming a workspace and `az login` or a service principal (playwright: a service principal only)
- Given part of a service principal and no workspace, should be ❌ naming the missing variables
- Given a workspace, should keep today's answers: ✅ with credentials, ❌ without, ❌ for playwright with only an ambient credential
- Given pql_test with a running Desktop instance, should stay ✅
- Given pql_test's remediation, should name opening the .pbip in Power BI Desktop; given the playwright family's, should name `PLAYWRIGHT_WORKSPACE_ID`
- Given any readiness row, should carry `status` as one of `ready`, `warning`, `info`, `error`, derived from `ready` when a branch sets none

---

## Doctor output and exit code

**Requirements**:
- Given a ⚠ row, should print ⚠ in yellow with its remediation
- Given any ❌ row, should exit 1; given only ✅, ⚠ and ℹ rows, should exit 0
- Given `--strict` and any ⚠ row, should exit 1
- Given `--format json`, should include each row's `status` and use the same exit code

---

## Service-mode line

**Requirements**:
- Given an ambient credential with no remediation, should not print a stray `. ` before `; or pass --interactive`

---

## Documentation

**Requirements**:
- Given the change, should update the doctor troubleshooting rows in GETTING-STARTED.md and PLAYWRIGHT-CI.md, `--strict` in the fab-test skill flags reference and its packaged copy, and a **Behavior change** CHANGELOG entry for the exit code

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
