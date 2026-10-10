# Playwright Shared Worker Pool Epic

**Status**: 📋 PLANNED (decisions open; see below)
**Goal**: A multi-report `fab-test playwright` run keeps `workers` browsers busy until every case across every report has run, instead of running reports one at a time with each report's workers capped at its case count.

## Overview

A workspace run today starts one `invoke_playwright` subprocess per report. Each subprocess resolves the report, generates its cases, mints embed tokens, and runs one pytest-xdist session with `min(case count, workers)` workers. Reports run one after another unless `--jobs` (or the execution YAML's `jobs`, added 2026-10-09) runs several at once. Most reports have 2-6 cases, so `workers: 8` on Azure-hosted browsers leaves most of the pool idle, and `jobs x workers` is only an upper bound that is hard to size against the service quota.

This epic gathers every report's cases into **one** pytest session, so `workers` becomes the actual browser concurrency for the whole run. `--impact-manifest` does not do this today: it loops over its reports, one session each ([invoke_playwright.py](../src/fab_test/scripts/invoke_playwright.py) `run_playwright_validation`).

The live run that prompted this (2026-10-09, `visual-error-testing`, 12 reports): reports ran one after another with 2-6 browsers each, even though the YAML set `workers: 8`.

## Open decisions

1. **Is the gain worth it after `jobs`?** Task 1 measures this. If `jobs` gets within ~15% of the pooled estimate, close this epic.
2. **Which component owns the pool?** Either the parent passes every discovered report to one `invoke_playwright` invocation (a repository-scoped run, like `--impact-manifest`), or a new pooled mode inside the wrapper. Either way, the parent must record N artifacts from one subprocess.
3. **Embed token lifetime.** Tokens are minted per report and role before pytest starts. A long pooled session can outlive them (about 1 hour). Options: mint lazily per case from the worker, refresh on expiry, or split the pool into time-bounded batches.
4. **Opt-in or default.** ✅ Decided 2026-10-09: it is for every multi-report run, local and CI, not only Azure-hosted browsers. The aim is to speed up full test runs wherever playwright is involved (`playwright --workspace`, `all` including playwright, and the CI workflows). Task 1 should therefore also measure a local-browser run and a CI run, not only Azure.

---

## Task 1: Measure before building

Depends on the [Run Timing](run-timing-epic.md) epic, so the numbers come from `run.json` rather than a stopwatch.

**Baseline recorded 2026-10-09** (Run Timing task 4, same verdicts in every run): Azure `jobs 1` 6m22s, Azure `jobs 4, workers 8` 1m54s, local `jobs 1` 6m18s, local `jobs 4` 2m53s. Discovery and embed tokens sum to about 1m45s per run, once per report, and pooling does not reduce that; `jobs` already overlaps it. The pooled session can only beat `jobs 4` on the render phase (4m20s summed on Azure), so the remaining requirement is the hand-pooled run.

**Requirements**:
- Given the 12-report `visual-error-testing` workspace on Azure-hosted browsers, should record wall-clock for `jobs: 1`, `jobs: 4`, and a hand-pooled single session (all `test-cases.json` merged into one run with `workers: 8`), with the same verdicts in all three.
- Given the pooled time is not materially better than `jobs: 4`, should close this epic with the measurements recorded and recommend a `jobs` default for Azure runs instead.

## Task 2: Prepare every report before rendering

**Requirements**:
- Given N discovered reports, should resolve each report, generate its cases, and mint its embed tokens before starting pytest, running the independent API calls concurrently.
- Given one report fails discovery, case generation, or token acquisition, should write that report's error envelope and continue with the others. One report's failure must never fail the whole run.
- Given `--plan-only`, should write every report's plan envelope without starting a session.

## Task 3: Run one pytest session across all cases

**Requirements**:
- Given cases from several reports, should run them in one xdist session with `workers` workers. Each case keeps its own embed configuration and evidence directory.
- Given cases of uneven cost (RLS roles, paginated parameter sets), should schedule the longest cases first so the pool drains evenly.
- Given the case-count-scaled outer timeout, should scale it from the total case count across all reports.
- Given an Azure connection or authentication failure, should report `playwright_execution_error` for every report in the session, never a visual finding and never a local fallback.

## Task 4: Split results back into per-report envelopes

**Requirements**:
- Given a finished pooled session, should write each report's `envelope.json`, `report.html`, native pytest HTML/JUnit, and case evidence exactly where a per-report run writes them today.
- Given the parent runs a pooled invocation, should record one `run.json` row, one index row, and one telemetry event per report, as it does today.
- Given `-q`, `--format json`, and CI annotations, should produce the same per-report output as a per-report run.

## Task 5: Document and verify live

**Requirements**:
- Given README, PLAYWRIGHT-CI.md, and the skill's flags reference, should describe `workers` as the run's browser concurrency and say when `jobs` still applies.
- Given a live Azure run of `visual-error-testing`, should match the per-report verdicts and record the wall-clock against Task 1's numbers.

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
