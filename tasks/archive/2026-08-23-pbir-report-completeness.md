# PBIR Report Completeness Epic

**Status**: ✅ COMPLETED (2026-08-23)
**Goal**: Make the PBIR report's images actually load and its envelope carry every rule PBIR Inspector evaluated, not just violations.

## Overview

The favicon fix from the HTML Report Format epic didn't fix the images a reader actually sees broken inside the report body — FabInspCLI's own per-object screenshot thumbnails are referenced by a Windows-style relative path (`PBIInspectorPNG\<Id>.png`) instead of the data-URI form it already uses for every other image, and PBIR's envelope.json only records rule violations, so telemetry can't answer "what rules ran and passed at this point in time" the way BPA's `test_results` now can — this closes both gaps.

---

## Task: Inline PBIR's per-object screenshot images

**Requirements**:
- Given a rendered `TestRun.html` whose per-object image src builds a `PBIInspectorPNG\<Id>.png` path, should the generated report reference that image as an inlined base64 data URI instead, sourced from the sibling `PBIInspectorPNG` folder
- Given the `PBIInspectorPNG` folder is missing or a referenced file doesn't exist on disk, should the report be left with its original reference rather than raising — mirroring `fix_favicon_link`'s never-raises contract
- Given the fix has already run once on a report, should running it again be a no-op rather than double-encoding

## Task: Carry every PBIR rule result into envelope.json

**Requirements**:
- Given a completed PBIR Inspector run, should `envelope.json`'s `test_results` list contain one entry per rule result parsed from the native JSON, including passes — not only the entries already in `findings`
- Given a PBIR rule result, should its `test_results` entry use the same normalized status vocabulary BPA's `test_results` already uses (pass/error/warning), so nothing PBIR-specific needs to be added to `normalize_test_results`
- Given an older envelope with no `test_results` key, should nothing about existing `findings`-based behavior change — additive only, same contract BPA already shipped
