# Live Integration Per Command Epic

**Status**: 🔄 IN PROGRESS 2026-11-23. Tasks 1-4 done; decision 5 accepted (user: "the same for bpa"); decisions 4 and 6 await the user.
**Goal**: every fab-test command has a test that runs the real CLI against the real tools and, where the command talks to Fabric, the real service, and CI runs it with the `fabric-demo` credentials. Mocked unit tests alone don't count as tested.

**Decisions**:

1. **The pattern is the playwright parity tests** (accepted 2026-11-23, user): a `tests/test_<command>_live.py` that runs `python -m fab_test.scripts.fab_test ...` as a subprocess, marked `integration` plus the analyzer's marker, skipping without credentials, and named in a `fabric-demo` workflow's pytest step.
2. **Deterministic analyzers assert exact outcomes against a recording** (pql-test, playwright): a recording of which tests pass and fail, made from a model or report that fails some tests on purpose. A tester that stops seeing a failure then fails CI. **Agentic ones (data-agent) assert only that the tester worked**: the run completed and every question got a verdict, never which answers were right.
3. **A live test whose service needs a paid capacity is opt-in by a workspace variable** (`DATA_AGENT_WORKSPACE`, `FAB_TEST_LIVE_WORKSPACE`) that its workflow sets, so a local full-suite run doesn't fail when the capacity is paused.
4. **Proposed: commands that never call Fabric** (`config`, `init`, `skill`, `list`, `explain`, `help`, `clean-tools`, `doctor`, `local`, `data-agent tests init|lint`, `pbir contract init|lint`) **count as covered by their existing real-CLI tests in build.yml**; they need no Fabric credentials to be tested for real.
5. **`bpa` gets a Windows live job** (accepted 2026-11-23). Tabular Editor is `win32` only, so no Linux workflow can run it; a `windows-latest` job in `fabric-demo` runs `bpa` locally and with `--workspace`.
6. **Proposed: `auth login` stays untested live.** It's interactive (a browser or device code), so CI can't complete it; `auth status` covers the credential chain.

## Coverage today

Inventory 2026-11-23. "Real" means the real CLI and tools with nothing patched.

| Command | Live test in a `fabric-demo` workflow | Gap |
|---|---|---|
| playwright | `test_playwright_{generation,result}_parity_live.py` (live-ci) | none |
| pql-test | `test_pql_test_live.py` (live-ci), added by this epic | Linux run unverified |
| data-agent | `test_data_agent_live.py` (data-agent-live), added by this epic | none |
| pbir (local rules) | `test_{slicer_rules,bookmark_navigators,pbir_filter_pane_rules}_live.py` (live-ci, added by this epic; they skipped in build.yml without .NET 10) | — |
| pbir, a11y, bpa, rdl | `test_analyzers_live.py` (live-ci; bpa in its Windows job), added by this epic | pbir contracts under `--workspace`: Service Mode Parity epic |
| dependencies | none | service |
| all `--workspace` | none | service |
| auth status | workflow steps; `test_data_agent_live.py` | — |

---

## Data Agent Live Test ✅

`tests/test_data_agent_live.py`: auth status, a service-mode `--dry-run` listing, and one module-scoped run (every request counts against the principal's quota) asserting each envelope completed and every question got a verdict. `data-agent-live.yml` runs it instead of the CLI step and checker script. Live-verified locally 2026-11-23: 4 passed.

**Requirements**:
- Given push and pull-request workflows can target the same deployed Data Agent workspace, should serialize their live runs across Git refs so one never races a run already in progress.

## pql-test Live Test ✅

`tests/test_pql_test_live.py` against `SampleModel-PQLAssert` in `fab-test-working-area`: a `--dry-run` listing, then every one of the 86 tests must pass or fail as recorded in `tests/fixtures/pql-test-live/` (78 pass, 8 fail on purpose, pql-test 0.2.1). Live-verified locally; flipping one recorded outcome fails the test, naming it. Runs in `live-ci.yml`.

## Every Live Test Runs In CI ✅

`tests/test_live_tests_run_in_ci.py` fails when a `tests/*_live.py` file is not named by a `fabric-demo` workflow. It found the three PBIR Inspector rule files, which now run in `live-ci.yml`.

**Requirements**:
- Given artifacts of the same type under differently named parent folders, should discover them in one stable artifact-name order on Windows and Linux so fixture recordings do not drift by platform.
- Given Playwright parity fixtures move to another Fabric workspace, should rebind each golden and recording by report/page/bookmark/dataset names rather than replace only the workspace ID.

---

## Analyzers Locally And Against The Workspace ✅

`tests/test_analyzers_live.py`: pbir, a11y, bpa and rdl each run on `fabric-artifacts/` and with `--workspace fab-test-working-area` (its Git-connected workspace), and each mode's findings (rule, severity, object) must match `tests/fixtures/analyzers-live/`; local and service must agree item by item; `rdl --workspace` without `--all` must refuse the 68-item workspace (exit 2), closing the Service Targeting epic's blocked >50-item check. Live-verified 2026-11-23: 13 passed. It found two defects: `pbir --workspace` skips slicer contracts (Service Mode Parity epic, held in `_KNOWN_GAPS`) and a DNS failure during an export poll crashes the run (Playwright REST clients task).

## First Live CI Run

**Requirements**:
- Given the `fabric-demo` principal, should see `fab-test-working-area` (Member or Contributor), where analyzer and Playwright parity fixtures now live.
- Given `live-ci.yml` in its Linux container, should run `test_pql_test_live.py` and `test_analyzers_live.py` green (a11y needs Node; pbir needs the .NET 10 set up there), and the Windows job should run bpa's.
- Given `live-ci.yml`, should run `test_pql_test_live.py` green. pql-test's `pyadomd` is Windows-only; if service mode can't query XMLA on Linux, move the test to a Windows job (decision 5's job).

## dependencies, all

**Requirements**:
- Given a deployed semantic model, should list the reports that depend on it, matching a recording.
- Given `all --workspace`, should run the configured set and report one summary naming each analyzer's result.

## Quality gates

Whole-repo `ruff check .`, the complexity and module-budget ratchets, the full suite with `--cov-fail-under=80` in CI's two halves, and the environment-dependent tests with `GITHUB_ACTIONS=true CI=true`.
