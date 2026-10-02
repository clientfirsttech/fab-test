# Playwright Test-Result Parity Epic

**Status**: ✅ COMPLETED (2026-09-28)
**Goal**: Make `fab-test playwright` pass and fail the same cases as the reference implementation (`pbi-dataops-visual-error-testing`) for the dev environment's six interactive and four paginated reports, and keep a test that fails when it stops doing so.

## Overview

The Playwright Generation Parity epic proved fab-test *builds* the right matrix.
It said nothing about whether each case *passes or fails* correctly. That second
half is what a user actually relies on: a broken visual behind one bookmark under
one role has to fail, and every working combination has to pass. The reference
implementation (`pbi-dataops-visual-error-testing`, TypeScript) has been validated
by hand against the dev workspace (`c4698d28-b05c-40bc-926c-707563ac85e7`), so its
outcomes are the expected answers. This epic stores those outcomes as golden
fixtures, closes the gaps on the paginated (RDL) side where fab-test builds
different cases and gets one wrong, and adds a credential-gated live test that
compares every case's outcome with the golden.

Scope is **render outcomes only**. The reference's per-case "embed token is
accessible" and "access token" tests are not reproduced: fab-test mints one token
per role before any case runs, and a token failure already fails every affected
case with a named reason.

## Outcome (2026-09-28)

All eight tasks done. **All 32 cases match the reference live** through the
installed console script: 26 interactive (unchanged, already matching) and 6
paginated (previously 4 generated, 1 wrong).

- `PaginatedExample` now gets its dataset from the report's data sources and
  passes; it previously errored with HTTP 400.
- `PaginatedExample-WithFilter` and `-WithMultiFilter` each run a baseline and a
  parameterized case. The multi-value `[2, 4]` case fails and its baseline passes,
  exactly as in the reference.
- Parameter values come from the parameter's own `ValidValues` query. The recorded
  fixtures replay it, so the paginated generation golden runs offline.
- `_apply_report_parameters` (pane clicking) is gone; parameters are applied at
  embed time.
- An embed-error row now records the failure as `actual`. Verified through the
  real CLI with a forced token failure, since no live parity case exercises that
  path.

Full suite 1,882 passed at 87% coverage; `ruff check src/ tools/ tests/` clean.
`invoke_playwright.py` passed 1,000 lines (exemption raised to 1,003 with a
reason); the next growth there should come with a split.

## Discovery Answers (2026-09-28)

| Question | Decision |
|----------|----------|
| What must match | The pass/fail of each render case (26 interactive + 6 paginated). Token-accessibility tests are out of scope |
| Golden fixtures | JUnit XML only. Traces, screenshots, and `.last-run.json` are not committed: the traces held (expired) embed tokens, and the reference project keeps its own copy |
| Harness | Credential-gated live comparison **plus** an offline contract test proving the golden files parse and line up with the generation goldens |
| RDL parameter values | Derived from the model: run each parameter's `ValidValues` DAX query, take the first value (single-value) or first two (multi-value). No per-report configuration |
| Applying parameters | Embed-time `parameterValues`, as the reference does. Replaces today's approach of clicking options in the parameter pane |
| Interactive golden | The original interactive `results.xml` was overwritten in this repo and in the reference project. Rebuilt from the 26 outcomes captured earlier in this session, stored as an `expected_status` column on the six generation golden CSVs |
| Paginated golden | Kept as `tests/fixtures/playwright-test-results/paginated-results.xml`, renamed so a later run can't overwrite it the way the interactive one was |

## Baseline (live run, 2026-09-28)

fab-test was run against all ten reports through the installed console script
before any change. The comparison with the reference:

**Interactive: 26 of 26 match.** The two defects fixed by the generation parity epic
(legacy `report.json` bookmarks, role discovery without `PLAYWRIGHT_USE_RLS`) were
the whole gap. The four expected failures all fail and nothing else does:

| Report | Page | Bookmark | Role | Expected |
|--------|------|----------|------|----------|
| Not Working Visuals | Page 1 | — | — | ❌ fail |
| Report with Bookmarks - Broken Visuals | Page A | Bookmark 3 | — | ❌ fail |
| RLSTest-WithBookmarks | Page 2 | Show Broken | Team A | ❌ fail |
| RLSTest-WithBookmarks | Page 2 | Show Broken | Team B | ❌ fail |
| *the other 22 combinations* | | | | ✅ pass |

**Paginated: 4 cases where the golden has 6, one outcome wrong.**

| Report | Parameters | Expected | fab-test today |
|--------|------------|----------|----------------|
| PaginatedExample | none | ✅ pass | ❌ **error**: `At least one dataset is required` (HTTP 400 from GenerateToken) |
| PaginatedExample-BrokenRDL | none | ❌ fail | ❌ fail ✓ |
| PaginatedExample-WithFilter | none | ✅ pass | ✅ pass (one merged case) |
| PaginatedExample-WithFilter | `ReportParameter1 = 2` | ✅ pass | *(merged into the case above)* |
| PaginatedExample-WithMultiFilter | none | ✅ pass | ❌ fail (one merged case, cannot tell which render broke) |
| PaginatedExample-WithMultiFilter | `ReportParameter1 = 2, 4` | ❌ fail | *(merged into the case above)* |

Root causes, each verified live:

1. **No dataset binding for a report with no local `.rdl`.** `PaginatedExample`
   exists only in the workspace, and fab-test reads the binding from a local file.
   `GET /reports/{id}/datasources` returns it for every paginated report as
   `connectionDetails.database = "sobe_wowvirtualserver-<datasetId>"`. For all
   three reports probed, that id is exactly the golden `dataset_ids`.
2. **One case per paginated report.** `_build_paginated_case` emits a single case
   and `_apply_report_parameters` then clicks the first options in the parameter
   pane in the same render. The golden has a separate baseline case and
   parameterized case per report, so a failure can be traced to the parameters
   that caused it.
3. **Parameter values.** `ValidValues` in both `.rdl` files is
   `EVALUATE SUMMARIZECOLUMNS('Table'[Column B])`, and `executeQueries` against
   dataset `4c353b5c…` returns exactly `[2, 4]`. So "first value" and "first two
   values" reproduce the golden sets `[2]` and `[2, 4]` exactly.
4. **Misleading row on an embed error.** The `PaginatedExample` row records
   `status: error` but `actual: "rendered"`. A reader sees a report that rendered
   and failed anyway.

## Reference Semantics (read from the reference project's spec source)

- **Interactive**: embed with `pageName`, plus `bookmark: {name}` when set. The
  first of `error` or `rendered` on `document.body` decides the outcome. fab-test
  also lets a late `error` override `rendered` for 5 s (`PLAYWRIGHT_VISUAL_ERROR_GRACE_MS`);
  that produced no divergence on these 26 cases, so it stays.
- **Paginated**: embed with `parameterValues: [{name, value}, …]` (a multi-value
  parameter is the same name repeated), wait `wait_seconds` (20), wait for
  `networkidle`, then fail if the page or any iframe contains `"ms-Dialog-content`.
  fab-test's scan already does the same check.

---

## Restore the interactive golden outcomes

**Requirements**:
- Given the six generation golden CSVs, should add an `expected_status` column
  (`pass`|`fail`) holding the 26 outcomes captured from the original interactive
  `results.xml`, so one file per report states both what to generate and what
  should pass.
- Given the column is added, should leave the generation parity test green:
  `expected_status` is not a parity field, and the loader reads only the fields
  it compares.
- Given a golden CSV row whose `expected_status` is missing or not `pass`/`fail`,
  should fail the offline contract test naming the file and row.

---

## Add the paginated generation golden

The four JSON files under `tests/fixtures/playwright-parity/` are the paginated
counterpart of the interactive CSVs.

**Requirements**:
- Given each RDL golden JSON, should compare fab-test's generated paginated cases
  on the unordered set of `(workspace_id, report_id, report_name, dataset ids,
  parameter set)`, with the parameter set compared as a multiset of
  `(name, value)` pairs. `test_case`, `xmlaPermissions`, and `wait_seconds` are
  ignored.
- Given recorded discovery fixtures, should replay the three new calls (report
  datasources, report definition parameters, `ValidValues` query results) with no
  network, as the interactive parity test replays pages/bookmarks/roles.
- Given recorded fixtures and golden inputs now share one directory and one
  extension, should move the recorded discovery responses to
  `tests/fixtures/playwright-parity/recorded/`. That keeps the directory's
  `*.csv`/`Paginated*.json` rule unambiguous: those are always goldens.
- Given `tools/record_playwright_parity_fixtures.py`, should record the paginated
  reports too.

---

## Resolve a paginated report's dataset without a local `.rdl`

**Requirements**:
- Given a paginated report with no local `.rdl`, should read its dataset ids from
  `GET /reports/{id}/datasources` (`sobe_wowvirtualserver-<id>`), so
  `PaginatedExample` gets a token instead of HTTP 400.
- Given a local `.rdl` is present, should keep preferring it. That path is
  released and verified.
- Given the datasources call fails or returns no Power BI dataset, should write an
  embed-error envelope naming the missing dataset and the flag that supplies it
  (`--dataset-id`), not a bare HTTP 400.

---

## Generate one baseline plus one parameterized case per paginated report

**Requirements**:
- Given a paginated report that declares no parameters, should generate exactly
  one case, as today.
- Given a report that declares parameters, should generate a baseline case with
  no parameters plus one case holding a parameter set: for each parameter, the
  first valid value (single-value) or the first two (multi-value).
- Given no local `.rdl`, should read the declared parameters from the report's own
  definition (Fabric `getDefinition`), through the same
  `parse_rdl_report_parameters` the local path uses.
- Given a parameter's `ValidValues` is a dataset query, should run it through
  `executeQueries` against the report's own dataset. Given it is a static list,
  should use the list without any call.
- Given a parameter with no `ValidValues` (free text), or a query that fails
  (commonly the "Dataset Execute Queries REST API" tenant setting being off),
  should keep the baseline case, log a warning naming the parameter and the
  setting, and not fail the run.
- Given the parameterized case, should give it an id that cannot collide with the
  baseline's, and a `test_results` row whose `parameters` field names the values
  tested (empty on the baseline row).
- Given the RDL generation golden, should match it: 6 cases across the 4 reports.

---

## Apply parameter sets at embed time

**Requirements**:
- Given a parameterized case, should pass `parameterValues` in the embed config
  (a multi-value parameter as repeated `{name, value}` entries), and render and
  scan it as an independent case.
- Given the change, should remove `_apply_report_parameters` and its pane-clicking
  second pass. Every value it tested is now its own case, and its DOM selectors
  were the most fragile code in the render path.
- Given the RDL golden outcomes, should fail `PaginatedExample-WithMultiFilter`'s
  `[2, 4]` case and pass its baseline.

---

## Record what actually happened on an embed error

**Requirements**:
- Given a case that never rendered because the embed token or context failed,
  should record `actual` as the failure (e.g. `embed error: At least one dataset
  is required`), never `rendered`.
- Given the change touches `_test_results_rows`, which both the embed-error path
  and the normal path use, should verify both paths through the real CLI (vision.md:
  Blast Radius).

---

## Offline contract for the result goldens

**Requirements**:
- Given `paginated-results.xml`, should parse every "for visual errors" test case
  into `(test_case, expected_status)`, and should fail if any `test_case` GUID has
  no row in the RDL generation goldens, or the other way round.
- Given the interactive CSVs, should fail if the goldens do not total 26
  interactive and 6 paginated expectations. A golden that silently shrinks proves
  nothing.
- Given the test is offline, should run in the default suite under
  `-m playwright`.

---

## Live result parity

**Requirements**:
- Given dev-tenant credentials, should run `fab-test playwright` once per report
  (all ten) through the installed console script, pinned to the dev workspace,
  and compare each case's `test_results` status with its golden `expected_status`,
  keyed by report + page + bookmark + role (interactive) or report + `parameters`
  (paginated).
- Given any mismatch, should fail naming the case, the expected and actual
  outcome, and fab-test's recorded reason for it.
- Given no credentials, should skip with a message naming what to set.
- Given the run takes several minutes, should be marked `integration` and
  `playwright` so the coverage-gated default suite never runs it.

---

## Documentation (Definition of Done)

**Requirements**:
- Given a human, should document the paginated matrix (baseline + one
  parameterized case), where parameter values come from, and what the
  `executeQueries` tenant setting controls, in the README and
  `docs/PLAYWRIGHT-CI.md`.
- Given a pipeline, should note in the example workflow that the paginated
  parameter cases need the "Dataset Execute Queries REST API" tenant setting.
- Given an agent, should update `.github/skills/fab-test/` and its packaged copy
  with the paginated case shape and the new `test_results` fields.
- Given the epic is closing, should run `ruff check src/`, the full suite with
  coverage at or above 80%, and the live result parity test green for all 32 cases.

---

## Decisions Taken (2026-09-28)

- **Row identity for a parameterized case**: the `test_results` row gains a
  `parameters` field holding the parameter set tested (`[{name, value}, …]`,
  empty for a baseline case). The live parity test keys paginated rows on
  report + `parameters`.
- **Multi-value parameters**: one parameterized case built from the first two
  valid values, whatever the model holds. One case per value would make the
  matrix grow with the model's data rather than with the report.
