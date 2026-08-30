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

## Scale the outer subprocess timeout to the generated case count  ✅

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

Done: A real architectural fork surfaced immediately on investigation and
was resolved with the user before writing code, not guessed at: discovering
the real case count (`resolve_discovery` in `playwright_validation/
discovery.py`) always requires a live Fabric REST call (pages, bookmarks,
roles) — there is no cheap local-file-only path, so a naive "count cases,
then decide the timeout" design would either double the network/auth cost
per artifact or need the generic, analyzer-agnostic execution layer
(`fab_test_execution.py`) to grow real knowledge of playwright's discovery
internals. Chose (with the user, after presenting the tradeoff) sharing one
discovery pass rather than paying for it twice.

The mechanism that emerged, once the real constraint was clear, is simpler
than either original option: `_run_single_report` already writes its
generated cases to `test-cases.json` well before pytest starts (line 585,
long before the pytest invocation at line 640) — that file is a sentinel
the *parent* can watch, without re-running discovery itself. So the outer
`subprocess.run(cmd, timeout=ctx.timeout)` call (`fab_test_execution.py`,
used identically by every analyzer) was replaced, for playwright only, with
`_playwright_timeout_scaling.run_playwright_with_scaled_timeout`: a
`Popen`-based runner that polls for that same file, and once it appears,
extends its own deadline to `max(200, 60 + PLAYWRIGHT_TIMEOUT_SECONDS *
len(cases))` — one live Fabric discovery call, shared between "how long do
we wait" and "what does the run actually do," not two.

`resolve_setting`'s existing `(value, origin)` return already distinguished
an explicit choice from the packaged default — `_resolve_timeout` was
extended to return `(value, is_default)` and `_RunContext` gained a
`timeout_is_default` field, so the requirement "still honor an explicit
choice" reduces to one `if` in `_run_artifact_process`: the new scaled path
only ever activates when `name == "playwright" and ctx.timeout_is_default`
— any `--timeout`/`ANALYZER_TIMEOUT`/config-file value at all reaches
every other analyzer exactly as before, and playwright itself, byte-
identical to today, whenever a caller has set one.

Real correctness work, not just a config tweak: `Popen` with `PIPE` for
stdout/stderr needs *someone* draining those pipes continuously or a
verbose, long-running pytest process can fill the OS pipe buffer and
deadlock while the main thread is busy polling for the cases file instead
of blocking in `communicate()` the way `subprocess.run` does internally —
`_drain_pipe` runs in a background thread for the process's whole
lifetime, and the final `subprocess.CompletedProcess` is assembled by hand
from what those threads collected, so every downstream caller
(`_emit_process_output`, envelope loading, `_finalize_artifact_run`) sees
an object indistinguishable from what `subprocess.run` would have
returned — none of them needed to change.

Verified with real subprocesses under real timing, not just mocked logic:
a fake child (`python -c ...`) that writes 3 cases immediately and then
sleeps 3s, against a flat 2s default and a 6s scaled one, survives; the
same shape with no cases file ever written is still killed at the flat
default (today's exact behavior, preserved); a scaled deadline that is
*also* exceeded is still killed (scaling raises the ceiling, it does not
remove one). `playwright_test_cases_dir` (new, `fab_test_registry.py`) is
the single source of truth both `build_playwright_command` (passes
`--test-cases-dir` explicitly now, where before it silently relied on the
package's shared unversioned default — a latent collision risk under
`--jobs N` running multiple playwright artifacts, fixed as a side effect)
and the poller read, confirmed to agree byte-for-byte by constructing both
independently and comparing. `playwright --impact-manifest` (a genuinely
different, repository-scoped mode with no single per-report cases file)
was excluded from the new path entirely and keeps the flat timeout
unchanged — caught by an existing test
(`test_run_analyzer_playwright_with_impact_manifest_is_repository_scoped`)
that started failing the moment the dispatch condition was too broad, not
by reasoning about it in advance.

`fab_test_execution.py` crossed its 800-line hard budget adding this, with
no prior exemption on record — rather than accept one, the new mechanism
was split into its own module, `_playwright_timeout_scaling.py` (167
lines): a cohesive, playwright-specific unit that every other analyzer's
execution path has no reason to carry, matching this repo's established
precedent of splitting by behavior over raising a ceiling. `ctx` is
duck-typed there (not importing `_RunContext`, which would create an
import cycle back into the module that calls this one); the two narration
callables the caller injects (`_reemit_lines`/`narrate`, so nothing is
duplicated) are bundled into one `Narration` dataclass rather than passed
as two separate parameters, keeping the function under the complexity
ratchet's argument-count ceiling (9 > 8 without it).

`tests/test_playwright_timeout_scaling.py` (new, 14 tests): the pure
formula and file-reading logic, three real-subprocess timing scenarios
above, and three dispatch-condition tests (`_run_artifact_process` takes
the scaled path only for playwright with a default timeout; an explicit
timeout bypasses it; every other analyzer is unaffected). `--timeout`'s CLI
help, the JSON config schema's `timeout` description, and `fab-test.yml`'s
scaffold comment all now name the scaling behavior and that an explicit
value overrides it — verified live via `fab-test playwright --help`, not
just written and assumed correct. `fab_test_registry.py`'s and
`fab_test_parser.py`'s exemption ceilings updated (888 and 941 lines) for
`playwright_test_cases_dir` and the expanded `--timeout` help text. Full
suite: **1561 passed, 0 failed, 3 skipped**, coverage held (floor 80%);
complexity and module budgets re-confirmed clean.

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
