# Live Integration Per Command Epic

**Status**: 🔄 IN PROGRESS 2026-11-23. Tasks 1-3 done; decisions 4-6 await the user.
**Goal**: every fab-test command has a test that runs the real CLI against the real tools and, where the command talks to Fabric, the real service, and CI runs it with the `fabric-demo` credentials. Mocked unit tests alone don't count as tested.

**Decisions**:

1. **The pattern is the playwright parity tests** (accepted 2026-11-23, user): a `tests/test_<command>_live.py` that runs `python -m fab_test.scripts.fab_test ...` as a subprocess, marked `integration` plus the analyzer's marker, skipping without credentials, and named in a `fabric-demo` workflow's pytest step.
2. **Deterministic analyzers assert exact outcomes against a recording** (pql-test, playwright): a recording of which tests pass and fail, made from a model or report that fails some tests on purpose. A tester that stops seeing a failure then fails CI. **Agentic ones (data-agent) assert only that the tester worked**: the run completed and every question got a verdict, never which answers were right.
3. **A live test whose service needs a paid capacity is opt-in by a workspace variable** (`DATA_AGENT_WORKSPACE`, `PQL_TEST_WORKSPACE`) that its workflow sets, so a local full-suite run doesn't fail when the capacity is paused.
4. **Proposed: commands that never call Fabric** (`config`, `init`, `skill`, `list`, `explain`, `help`, `clean-tools`, `doctor`, `local`, `data-agent tests init|lint`, `pbir contract init|lint`) **count as covered by their existing real-CLI tests in build.yml**; they need no Fabric credentials to be tested for real.
5. **Proposed: `bpa` gets a Windows live job.** Tabular Editor is `win32` only, so no Linux workflow can run it; a `windows-latest` job in `fabric-demo` runs `bpa` locally and with `--workspace`.
6. **Proposed: `auth login` stays untested live.** It's interactive (a browser or device code), so CI can't complete it; `auth status` covers the credential chain.

## Coverage today

Inventory 2026-11-23. "Real" means the real CLI and tools with nothing patched.

| Command | Live test in a `fabric-demo` workflow | Gap |
|---|---|---|
| playwright | `test_playwright_{generation,result}_parity_live.py` (live-ci) | none |
| pql-test | `test_pql_test_live.py` (live-ci), added by this epic | Linux run unverified |
| data-agent | `test_data_agent_live.py` (data-agent-live), added by this epic | none |
| pbir (local rules) | `test_{slicer_rules,bookmark_navigators,pbir_filter_pane_rules}_live.py` (live-ci, added by this epic; they skipped in build.yml without .NET 10) | — |
| pbir `--workspace` | dry-run listing step only | export + Inspector against the service |
| rdl `--workspace` | workflow step (exit ≤ 1) | no recording: findings aren't compared |
| a11y | none | local and service |
| bpa | none | decision 5 |
| dependencies | none | service |
| all `--workspace` | none | service |
| auth status | workflow steps; `test_data_agent_live.py` | — |

---

## Data Agent Live Test ✅

`tests/test_data_agent_live.py`: auth status, a service-mode `--dry-run` listing, and one module-scoped run (every request counts against the principal's quota) asserting each envelope completed and every question got a verdict. `data-agent-live.yml` runs it instead of the CLI step and checker script. Live-verified locally 2026-11-23: 4 passed.

## pql-test Live Test ✅

`tests/test_pql_test_live.py` against `SampleModel-PQLAssert` in `fab-test-working-area`: a `--dry-run` listing, then every one of the 86 tests must pass or fail as recorded in `tests/fixtures/pql-test-live/` (78 pass, 8 fail on purpose, pql-test 0.2.1). Live-verified locally; flipping one recorded outcome fails the test, naming it. Runs in `live-ci.yml`.

## Every Live Test Runs In CI ✅

`tests/test_live_tests_run_in_ci.py` fails when a `tests/*_live.py` file is not named by a `fabric-demo` workflow. It found the three PBIR Inspector rule files, which now run in `live-ci.yml`.

---

## First Live CI Run

**Requirements**:
- Given the `fabric-demo` principal, should see `fab-test-working-area` (Member or Contributor) as well as `visual-error-testing`; the local principal in `.fab-test/.env` sees only the former (2026-11-21), so the playwright live tests 401 locally.
- Given `live-ci.yml` in its Linux container, should run `test_pql_test_live.py` green. pql-test's `pyadomd` is Windows-only; if service mode can't query XMLA on Linux, move the test to a Windows job (decision 5's job).

## rdl And pbir Against The Service

**Requirements**:
- Given `visual-error-testing`, should run `rdl --workspace` and full `pbir --workspace` (export + Inspector) and compare each item's findings (rule, object) with a recording, as the pql-test test does.

## a11y, dependencies, all

**Requirements**:
- Given a report with known accessibility defects, should run `a11y` locally and against the service and match a recording.
- Given a deployed semantic model, should list the reports that depend on it, matching a recording.
- Given `all --workspace`, should run the configured set and report one summary naming each analyzer's result.

## bpa On Windows

Depends on decision 5.

## Quality gates

Whole-repo `ruff check .`, the complexity and module-budget ratchets, the full suite with `--cov-fail-under=80` in CI's two halves, and the environment-dependent tests with `GITHUB_ACTIONS=true CI=true`.
