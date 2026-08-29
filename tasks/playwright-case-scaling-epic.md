# Playwright Case Scaling Epic

**Status**: 📋 PLANNED
**Goal**: A `fab-test playwright` run for a report with many pages/bookmarks/roles
neither gets killed mid-matrix by a timeout sized for one case, nor takes
proportionally longer wall-clock as the matrix grows.

## Overview

`ANALYZER_TIMEOUT`/`--timeout` (`_DEFAULT_SUBPROCESS_TIMEOUT = 200` in
`fab_test.py`) wraps the *entire* per-artifact subprocess -- for `playwright`,
that subprocess is one `pytest` invocation covering every generated case
(page x bookmark x role) for that report, run sequentially
(`_run_pytest` in `invoke_playwright.py`). The 200s default was sized for the
*inner* per-case render budget (`PLAYWRIGHT_TIMEOUT_MS`, default 60-180s) plus
headroom for auth and browser startup -- a budget that assumes roughly one
case per artifact. It does not account for the matrix `resolve_discovery`/
`generate_test_cases` can produce for a single report: `Report with Bookmarks -
Broken Visuals` already generates enough page/bookmark cases that their
render times, run one after another in a single pytest process, exceed 200s
before the run finishes -- observed live: two cases complete
(`PASSED`/`FAILED`), then the whole subprocess is killed
(`⏰ fab-test playwright: timed out after 200s`) with the remaining cases
never attempted, and the run reported as a single opaque timeout finding
instead of per-case results.

The `Playwright Render Diagnostics Epic` already raised both budgets once
(inner default 60s -> 180s, outer default 120s -> 200s) but kept the outer
timeout a flat constant -- it did not make the outer timeout scale with case
count, which is the actual mismatch: the wrapper is suite-scoped, but sized
like it's per-test.

Two related, independently-shippable changes:
1. Scale the outer subprocess timeout to the number of generated cases,
   instead of a single flat default regardless of matrix size.
2. Run the generated cases concurrently (`pytest-xdist`) instead of
   sequentially, so a large matrix finishes in roughly one case's wall-clock
   time rather than the sum of all of them -- reducing how often (1) even
   needs to reach for a very large ceiling.

---

## Scale the outer subprocess timeout to the generated case count

**Requirements**:
- Given `_run_single_report` has already generated `cases` before invoking
  pytest, should compute a per-run timeout floor from `len(cases)` (a
  per-case budget plus fixed overhead for auth/browser startup) rather than
  relying solely on the flat `ANALYZER_TIMEOUT`/`--timeout` default
- Given an explicit `--timeout`/`ANALYZER_TIMEOUT`/config-file value is set,
  should still honor it as a floor or override rather than silently replacing
  a caller's explicit choice with the computed value
- Given a report that generates only one or two cases, should not regress
  today's behavior (the computed value should not fall below the existing
  200s default)
- Given the CLI help, config schema, and `fab-test.yml` template comment,
  should describe the scaling behavior so a reader is not misled by a single
  static number

## Run generated Playwright cases concurrently via pytest-xdist

**Requirements**:
- Given more than one generated case for a report, should invoke pytest with
  `-n <workers>` (`pytest-xdist`) so cases run across multiple worker
  processes instead of one after another in `_run_pytest`
- Given the number of workers, should default to something bounded (e.g.
  `auto` capped at a sane maximum, or the existing `--jobs`/config precedent
  from `fab_test.py`) rather than unconditionally maximal parallelism that
  could exhaust local browser/resource limits
- Given per-case evidence writing (`_write_evidence`, `result.json`,
  screenshots) and the shared `--html`/`--junitxml` report output, should
  continue to produce one correct, non-corrupted report and one `result.json`
  per case when multiple workers write concurrently
- Given embed token acquisition already happens once per role before pytest
  starts (`acquire_embed_configs` in `_run_single_report`), should remain
  unaffected -- xdist parallelizes case execution only, not token
  acquisition
- Given `pytest-xdist` is a new dependency, should be added to the project's
  test/dev dependency group and to `doctor`'s readiness checks if pytest
  itself is checked there
