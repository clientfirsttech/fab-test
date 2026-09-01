# Paginated Report Parameter Testing Epic

**Status**: ✅ COMPLETED — 3 of 3 tasks done
**Goal**: `fab-test playwright` catches a paginated report's filter/parameter errors, not only its no-filter render.

## Overview

`PaginatedExample-WithMultiFilter` renders clean with no parameter applied, but
selecting real values in the live report throws "Unable to render paginated
report / The processing of FilterExpression for the dataset 'DataSet1' cannot
be performed. Cannot compare data of types System.Int64 and System.Object[]."
`_test_paginated_report` (`tests/test_playwright_visual.py`) never applies a
parameter value at all — it embeds, waits, and scans once — so this whole
class of error is invisible to it. A validated reference implementation
catches it by driving the report's own rendered parameter panel like a human:
open each parameter's dropdown, pick the first value (first two for a
multi-value parameter), submit, and re-check for the error modal.

Live DOM recon against `PaginatedExample-WithMultiFilter`/`-WithFilter` in DEV
found the real, stable selectors (Fluent UI, `data-testid`-based):

- `#{ParamName}-input` — the combobox input; click opens its dropdown
- Options render as `[id^="{ParamName}-list"]`; single-value parameters use
  `role="option"`, multi-value ones use `role="menuitemcheckbox"` with a
  `title="Select All"` entry at index 0 that must be skipped
- `[data-testid="parameter-pane-submit-action"]` — the "View report" submit button

## Parse a paginated report's declared parameters

**Requirements**:
- Given an `.rdl` file with a `<ReportParameters>` block, parsing returns each parameter's name and whether `<MultiValue>true</MultiValue>` is set
- Given an `.rdl` file with no `<ReportParameters>` block, parsing returns an empty list rather than erroring

## Thread parameter metadata from local discovery to the pytest spec

**Requirements**:
- Given a local `.rdl` artifact with declared parameters, `fab_test_registry.py` passes them to `invoke_playwright.py` (mirroring how dataset id/workspace are already passed for the same artifact)
- Given `--report-parameters` is not supplied (remote/static targets), config carries an empty list — no behavior change
- Given a paginated `TestCase`, its declared parameters are carried through to the CSV/JSON test-case files the pytest spec reads

## Apply parameter values and re-check for the error modal

**Requirements**:
- Given a paginated report with no declared parameters, behavior is unchanged: embed, wait, scan once
- Given a paginated report with declared parameters and a clean first scan, the spec opens each parameter's dropdown, selects the first value (first two for multi-value, skipping "Select All"), submits, waits again, and re-scans for the error modal
- Given the second scan finds the error modal, the case fails and the evidence/error message distinguishes "no filter" pass from "filter applied" failure
- Given a live DEV run, `PaginatedExample-WithMultiFilter` fails with the filter-driven error and `PaginatedExample-WithFilter`/`PaginatedExample-LocalSemanticModel` continue to pass

## Live verification (DEV)

All four DEV fixtures behave exactly as expected after applying the report's
own declared parameters:

- `PaginatedExample-WithMultiFilter` (multi-value `ReportParameter1`) — now
  **fails**, with the screenshot capturing Power BI's own error dialog
  verbatim: "Unable to render paginated report / The processing of
  FilterExpression for the dataset 'DataSet1' cannot be performed. Cannot
  compare data of types System.Int64 and System.Object[]."
- `PaginatedExample-WithFilter` (single-value `ReportParameter1`) — still
  **passes**; this report's filter genuinely works, so selecting a real
  value and re-checking correctly finds nothing wrong
- `PaginatedExample-LocalSemanticModel` (no declared parameters) — still
  **passes**, confirming the no-parameter path is unchanged (single scan,
  no second embed check)
- `PaginatedExample-BrokenRDL` — still **fails** at the first (no-filter)
  scan, as before this epic
