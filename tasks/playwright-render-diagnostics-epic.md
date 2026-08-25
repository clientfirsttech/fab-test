# Playwright Render Diagnostics Epic

**Status**: 🔧 IN-PROGRESS
**Goal**: A `fab-test playwright` render timeout tells the caller *why* the report failed
to render instead of a bare "did not render within Xms".

## Overview

`SampleModel-PQLAssert` failed with `Report did not render within 60000ms`. The
evidence showed the Power BI iframe rendered its own generic
`Something went wrong` error page, and console.json recorded 403s against
Power BI telemetry endpoints -- but the embed SDK's own `report.on('error', ...)`
handler never fired, so `test_report_visual_renders` recorded a plain timeout
with no indication of *why* the embed failed. Meanwhile `generate_embed_token`
in `power_bi_api.py` already raises `PowerBiApiError` on any non-200 response,
so a legitimately-issued token was confirmed -- the failure is downstream of
token issuance, at the embed/report-server level, and currently invisible.

Two related, independently-shippable changes:
1. Raise the render-wait budget so a genuinely slow (not broken) report has
   room to finish, without silently being killed early by the *outer*
   per-artifact subprocess timeout that wraps every analyzer invocation.
2. Capture Power BI's own "Show details" error panel text when the render
   times out, so the next failure's `envelope.json` names the real cause
   (e.g. a permissions or token-scope problem) instead of restating the
   timeout.

---

## Raise the Playwright render-wait budget without breaking the outer subprocess timeout

`PLAYWRIGHT_TIMEOUT_SECONDS` (render-wait, default 60s) is bounded by
`ANALYZER_TIMEOUT`/`--timeout` (per-artifact subprocess timeout, default
120s, `_DEFAULT_SUBPROCESS_TIMEOUT` in `fab_test.py`) -- the comment there
says it "matches the longest wrapper timeout". Raising the inner budget
without raising the outer one would make the subprocess get killed *before*
the new, longer render wait ever completes, which is worse than today.

**Requirements**:
- Given no `PLAYWRIGHT_TIMEOUT_SECONDS` override, should default to 180
  seconds (`config.py`)
- Given no `--timeout`/`ANALYZER_TIMEOUT` override, should default to 200
  seconds so it still exceeds the playwright wrapper's render-wait budget
  plus auth/startup overhead (`fab_test.py`)
- Given the CLI help, config schema, and `fab-test.yml` template comment,
  should state the new default so a reader is not misled by a stale number

## Capture the embed error panel's details when a render times out

**Requirements**:
- Given a report render race that never fires `rendered` or `error` (the
  `result is None` branch in `test_report_visual_renders`), should look for
  Power BI's generic error panel across `page.frames`, best-effort click
  "Show details", and fold any found text into the failure message and a
  new `embed_error_details.txt` evidence file
- Given no such panel is found (a genuine slow-render timeout with no error
  UI), should fall back to today's plain "did not render within Xms"
  message with no new evidence file

## Catch a broken visual by listening at the document level, not report.on()

`Not Working Visuals` renders its shell successfully -- the embed SDK fires
`rendered` -- while Page 1 shows two visuals with Power BI's own
"Something's wrong with one or more fields" error banner. `test_report_visual_renders`
recorded `"status": "pass"` even though the evidence screenshot showed a
clearly broken page, because it bound `report.on('rendered'/'error')` on the
report object returned by `embed()`. A per-visual failure fires an `error`
CustomEvent that the SDK dispatches on `document.body` but that never
reaches the report object's own `.on('error')` binding -- confirmed against
a working reference implementation that listens on `document.body` instead
and does catch it.

**Requirements**:
- Given a report embed, should race `rendered` vs `error` by listening on
  `document.body`, not by calling `report.on(...)` on the object `embed()`
  returns
- Given a broken visual that fires a document-level `error` event after
  embedding, should fail the case with that event's detail in the error
  message instead of recording `pass`
- Given a report with no visual errors, should continue to record `pass` as
  before once `rendered` fires on `document.body`
