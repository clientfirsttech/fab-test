# Playwright Report Detail Epic

**Status**: 📋 PLANNED
**Goal**: Make `fab-test playwright` output as evidence-rich as the BPA/pql-test reports it sits beside.

## Overview

A passing or failing `fab-test playwright` run currently tells a caller almost nothing about what actually happened: a failure marks every generated test case with the same generic "Visual load error detected" message regardless of which case actually failed, a pass records zero findings so the HTML report renders "No findings" even though N report×page×bookmark combinations were genuinely exercised, and the screenshot/console/network evidence the pytest spec already captures to disk per case (`analyzer-results/playwright/test-cases/<case>/`) is never linked from the report or carried into the envelope, so a human has to know that directory exists and an agent has no path to it at all. `test_report_html.py` (HTML Report Format) already solved this shape for BPA and pql-test via the envelope's `test_results` field; Playwright was explicitly deferred there (see `plan.md`, Human-Readable Reports) and is deferred again now with its own actual output confirmed live: `SampleModel-PQLAssert` rendered a genuine Power BI "Something went wrong" embed error, and the resulting report said only "1 finding(s)" with no hint what went wrong or where the evidence lives.

---

## Per-Case Result Capture

`tests/test_playwright_visual.py` already writes `screenshot.png`/`console.json`/`network.json` per case in `_write_evidence`; it discards the pass/fail outcome and any Power BI error detail once the pytest process exits.

**Requirements**:
- Given a test case passes or fails, should write a `result.json` beside its other evidence recording status (`passed`/`failed`) and, on failure, the actual error string (embed error, timeout, or RDL modal detection) already available in that function
- Given `invoke_playwright.py` reads a case's `result.json` after the pytest run, should recover its true per-case status instead of assuming every case shares the run's overall outcome

## Accurate Envelope Test Results

`_write_findings` in `invoke_playwright.py` returns `[]` on any success and, on any failure, tags **every** case with the identical message — a report with 5 pages and 1 real failure currently reports 5 identical findings.

**Requirements**:
- Given any run (pass or fail), should populate the envelope's `test_results` field with one row per generated case, using the existing "tests" shape (`suite_name`/`test_name`/`expected`/`actual`/status) that `normalize_test_results` already renders
- Given a case's real per-case status from `result.json`, should report only that case as failed, not the whole set, when some cases pass and others fail
- Given a case's captured error detail, should surface it as `actual` rather than the fixed string `"Visual load error detected"`

## Evidence Links In The HTML Report

`_report_html.py`'s `_table`/`_filterable_table` render `test_results` rows with no way to reach the screenshot or console log that already exists on disk for the same case.

**Requirements**:
- Given a `test_results` row that carries a relative evidence path (screenshot and/or console/network log), should render a link to it in an added column, resolved relative to the report's own location the same way `render_index`'s `_link` helper already resolves report/envelope links
- Given a row with no evidence path (an analyzer that hasn't adopted this field), should render exactly as today — this is additive, not a schema requirement for every analyzer

## Agent-Visible Artifact Paths

An AI agent driving `fab-test playwright --format json` currently gets the same skimpy `message` string a human gets on stdout, with no path into the evidence Task 1 now captures.

**Requirements**:
- Given `--format json` output for a playwright run, should include each case's evidence paths (screenshot/console/network, when present) alongside its `test_results` entry, not only in the on-disk layout the agent would otherwise have to guess at

## Documentation

**Requirements**:
- Given the `fab-test` skill's documented output shapes, should describe the new per-case `test_results` detail and evidence paths for `playwright`
- Given the README's Playwright section, should show what a detailed report/JSON output now looks like
- Given this epic's Definition of Done in `vision.md`, should leave no caller undocumented before this epic is marked complete
