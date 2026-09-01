# Open Report Flag Epic

**Status**: ✅ COMPLETED
**Goal**: Let a human skip the three-click "find it in Explorer, double-click" dance after a run by adding `--open-report`, which launches the produced HTML report in the default browser.

## Overview

A human running `fab-test` locally with `--report` on gets a path printed to stdout and then has to go find it — Explorer, navigate, double-click. `--open-report` closes that gap for the one caller (vision.md's "Human") who benefits from it, while staying inert for the other two: a pipeline never wants a build step popping a browser, and an agent has no display to pop one onto. Off by default, opt-in, and auto-detects CI so it degrades to "just print the path" instead of hanging or erroring on a headless runner.

Discovery findings that shaped scope (see vision.md's Blast Radius — `--report` surfacing already bit this codebase twice: once for not saying where the file went, once for saying it twice):

- **Report location varies by run shape.** `fab-test all` (>1 analyzer) writes a per-run `index.html` via `write_index` ([_report_html.py](../src/fab_test/scripts/_report_html.py)); a single analyzer with one artifact has exactly one `report.html`/native report (`_report_path_for` in [fab_test_summary.py](../src/fab_test/scripts/fab_test_summary.py)); a single analyzer with *multiple* artifacts had neither at first — `_print_summary` never called `write_index`, only the `all` path did. Original decision: open the index when one exists, open the single report when there's exactly one, and print a note (no browser launch) for the multi-artifact/single-analyzer case rather than building a second index path this epic doesn't need.
  **Revisited 2026-08-31**, same day: a real `fab-test a11y` run against four artifacts hit exactly this note ("multiple reports were generated; open one directly above") and read as an inconsistency, not a documented scope cut — `all` gets a page to open, one analyzer with several artifacts didn't. `_open_single_analyzer_report` now builds the same per-run `index.html` `_write_and_open_index` builds for `all` (via a shared `_index_row_fields` helper reusing `build_all_summary_rows`'s envelope-reading rules), written whenever `--report` is on and there's more than one artifact — independent of `--open-report`, matching `all`'s own index-writing condition — and opened under `--open-report` the same way. Only a single analyzer against exactly one artifact still has no index, because that shape already has one report to point at.
- **`--open-report` implies `--report`.** Passing it alone should not be a silent no-op or a hard error; it turns report generation on for that run so the flag always does something.
- **CI must not attempt to open anything.** `fab_test_execution.py`, `_analyzer_annotations.py`, and `_analyzer_tool_bootstrap.py` each already carry their own `_is_ci()` (`GITHUB_ACTIONS` or `CI` env var) — this epic reuses that exact check rather than inventing a fourth detection strategy. Consolidating the four copies into one shared helper is a real but separate cleanup, deferred below.
- **Scope of the flag**: lives in the same mutually-exclusive `report_group` in [fab_test_parser.py](../src/fab_test/scripts/fab_test_parser.py) as `--report`/`--no-report`, so every subcommand that accepts one accepts the other — no per-command special-casing.

---

## Task 1: Add the `--open-report` flag and its resolution

`fab-test <cmd> --open-report` should turn on both opening and (if not already on) report generation, resolved through the same CLI > env > config-file > default precedence every other setting uses.

**Requirements**:
- Given `--open-report` is passed, should resolve `open_report=True` via `resolve_setting("open_report", cli_value=..., env_var="ANALYZER_OPEN_REPORT", ...)`, mirroring `resolve_report`'s shape in [_report_html.py](../src/fab_test/scripts/_report_html.py)
- Given `--open-report` is passed without `--report`/`--no-report`, should still resolve `report=True` for that invocation (auto-enable), without requiring the user to pass both flags
- Given `--no-report --open-report` (explicit conflict), should refuse with a clear error naming both flags, rather than silently picking one
- Given neither flag is passed, should resolve `open_report=False` (default off), matching `--report`'s existing default-off behavior
- Given `ANALYZER_OPEN_REPORT=true` is set in the environment, should behave the same as passing `--open-report` on the CLI, one level below the CLI flag in precedence

## Task 2: CI-safe browser-opening helper

A small, testable function that opens a path in the default browser, refusing to do so under CI.

**Requirements**:
- Given `open_report` resolves true and the process is not running under CI (no `GITHUB_ACTIONS`/`CI` env var set), should call `webbrowser.open()` on the resolved report/index path (as a `file://` URL) and return that it opened
- Given `open_report` resolves true and the process **is** running under CI, should skip calling `webbrowser.open()` entirely and print the same "path printed" line the non-open path already prints today, so no behavior is lost — never attempt to launch a browser on a runner
- Given `webbrowser.open()` raises or returns `False` (no browser available, e.g. a bare Linux dev container), should print the path as a fallback rather than raising — a convenience failing must not fail the run, matching `attach_report`'s existing "never raises" contract
- Given the target path does not exist on disk (report generation failed upstream), should skip opening and print the failure context already being printed, not attempt to open a dangling path

## Task 3: Wire the resolved path into each run shape

**Requirements**:
- Given `fab-test all` with more than one analyzer and `--open-report`, should open the run's `index.html` exactly once after the summary prints — not once per analyzer
- Given a single-analyzer command (e.g. `fab-test bpa`, `fab-test playwright`) with exactly one artifact and `--open-report`, should open that artifact's report path (`_report_path_for`'s result) — the same path already printed as the one clickable line
- Given a single-analyzer command with more than one artifact and `--report` on, should write a per-run `index.html` the same way `fab-test all` does, listing every artifact the way the existing per-artifact print already does; given `--open-report` is also set, should open that index — **revisited 2026-08-31**, see the Overview note above (originally: print a note and open nothing for this shape)
- Given `--open-report` resolves true but `resolve_report(args)` still resolves false after Task 1's auto-enable logic runs (should not happen, but as a guard), should skip opening and warn rather than opening a stale or nonexistent report from a prior run

## Task 4: Documentation (all three callers)

Per vision.md's Definition of Done — not complete until all three ship together. Use the `document` skill so they can't drift apart.

**Requirements**:
- Given the fab-test skill (`.github/skills/fab-test/SKILL.md`), should document `--open-report`, `ANALYZER_OPEN_REPORT`, its auto-enable of `--report`, and the CI no-op behavior
- Given `README.md`/`docs/QUICK-VALIDATION.md`, should show a human-facing example (`fab-test bpa --open-report`) and note it is a local convenience, not something to add to a pipeline YAML
- Given any CI workflow snippet in the docs, should confirm none of them add `--open-report` — it is dead weight there since the CI guard suppresses it anyway
