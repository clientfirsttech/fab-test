# Run Timing Epic

**Status**: 🔄 IN-PROGRESS (task 1 of 4 done)
**Goal**: Every run records and shows how long it took, where the time went, and which execution settings produced it. Two runs, for example local `jobs: 1` against Azure `jobs: 4, workers: 8`, can then be compared side by side to show what parallelism and Azure-hosted browsers save.

## Overview

Playwright runs are the slowest thing fab-test does. The point of the execution YAML's `workers`/`jobs` and Azure-hosted browsers is to shorten them, but today a run cannot show whether they did:

| Where | What is recorded today |
|---|---|
| Playwright `envelope.json` | `duration_ms`, timing only the pytest phase. Report discovery, case generation and embed-token minting are not timed. No `started_at`. |
| Playwright `test_results[]` | No per-case duration. pytest's own `report/results.xml` has one, but nothing reads it. |
| `run.json` | No start time, end time, wall clock, or per-artifact duration. Nothing about `backend`, `workers` or `jobs`. |
| Summary table and `index.html` | No time column and no run total. |
| Report `report.html` | Shows the envelope's `duration_ms`. |
| Telemetry | Sends the whole envelope, so `duration_ms` already reaches Eventhouse; no run-level timing. |

The number that tells the story is the ratio of the **sum of report durations** (the time the run would take with nothing in parallel) to the **wall clock** (what the caller waited). With `jobs: 1` the ratio is about 1×; with `jobs: 4` on Azure it should approach 4×. This epic makes both numbers, and the settings behind them, part of every run.

The [Playwright Shared Worker Pool](playwright-shared-worker-pool-epic.md) epic's Task 1 ("measure before building") depends on this epic. Its measurements should be taken with these numbers, not with a stopwatch.

## Decisions

1. ~~**How runs are compared.**~~ **Decided: by hand.** No compare command, no delta view, no KQL. Each run keeps its own `--output-dir`, and the reader opens both with `fab-test open-report` and reads the timing side by side. So the timing must be visible in the opened pages, not only in `run.json`.
2. ~~**Where per-case timing comes from.**~~ **Decided: the packaged pytest plugin's hooks.** Not `results.xml`: JUnit output exists only for the native report, and a hook records duration whether or not it is on.
3. ~~**Scope beyond playwright.**~~ **Decided: phase timing (Task 2) is playwright-only.** Run-level timing (Task 1) is cheap and generic, so it still applies to every analyzer; the others finish in seconds and need no phase breakdown.

---

## Task 1: Record run and artifact timing in `run.json` (completed 2026-10-09)

`run.json` gains `started_at`, `finished_at`, `wall_ms` and `execution` (null unless playwright ran), and each artifact gains `duration_ms`: the parent's subprocess wall time, the timeout length for a timeout, null for `preflight_failed` (never ran). `execution` resolves through `execution_summary` in `execution_config.py`, beside `resolve_jobs`/`resolve_workers`, which moved there from `execution_runtime.py` (re-exported) so the parent does not import Playwright to describe a run. Schema version stays 1: every field is additive. SKILL.md documents the fields and corrects the aborted-run line: `envelope_path` now points at the envelope fab-test writes in its place.

**Requirements**:
- Given any run, should add `started_at` and `finished_at` (UTC, ISO 8601) and `wall_ms` to `run.json`, measured by the parent around the whole run.
- Given each artifact, should record the parent-measured subprocess wall time as `duration_ms` beside the existing status and counts, including for aborted, timed-out and preflight-failed artifacts.
- Given a playwright run, should record an `execution` block with `backend`, the resolved `workers` and `jobs`, and each setting's origin (flag, environment, YAML, config, default). It must never include the service URL, tokens or credential values.
- Given an existing `run.json` consumer, should keep every change additive under the current `schema_version`, or bump it if a reviewer finds any field's meaning changed.

## Task 2: Time each playwright phase and case

**Requirements**:
- Given a playwright report, should record `started_at` and a `timings` object in its envelope with `discovery_ms`, `token_ms`, `render_ms` and `total_ms`. `duration_ms` keeps meaning the render phase, so existing readers are unaffected.
- Given each generated case, should add its `duration_ms` to `test_results[]` recorded by the pytest plugin's hooks (decision 2), and leave it absent rather than zero when unknown.
- Given an Azure run, should record the browser connection time separately from rendering when the adapter can measure it, so a slow service connection is not read as slow Power BI rendering.

## Task 3: Show timing where people look

**Requirements**:
- Given a multi-artifact run, should end the terminal summary with one line naming the wall clock, the sum of artifact durations, the ratio between them, and the execution settings, for example `Wall 4m12s · artifact time 14m30s · 3.5x parallel · azure, jobs 4, workers 8`.
- Given `index.html`, should add a Duration column and the same run line under the title. `render_index` stays a pure function: durations come from its inputs, never from the clock.
- Given a playwright `report.html`, should show the phase breakdown and a per-case duration column, sorted to put the slowest cases where a reader looks first.
- Given `-q` or `--format json`, should add timing to the JSON summary and leave the quiet one-line-per-artifact format unchanged.
- Given `fab-test open-report` on a finished run, should show the run line (wall clock, artifact time, ratio, execution settings) on the page it opens, so two runs can be compared by opening each one (decision 1).

## Task 4: Benchmark and document

**Requirements**:
- Given the `visual-error-testing` workspace (12 reports), should record local `jobs: 1`, Azure `jobs: 1`, and Azure `jobs: 4` with `workers: 8`, all with the same verdicts, in PLAYWRIGHT-CI.md as a worked example of reading the timing.
- Given that worked example, should show how to compare two runs by hand: give each run its own `--output-dir`, open both with `open-report`, and check that the report set and verdicts match before reading a faster run as a speedup.
- Given those numbers, should hand the Shared Worker Pool epic's Task 1 its baseline.

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
