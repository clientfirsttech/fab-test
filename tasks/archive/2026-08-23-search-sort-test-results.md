# Search and Sort for Test Result Tables Epic

**Status**: ✅ COMPLETED (2026-08-23)
**Goal**: Let a reader search and sort the full BPA/pql-test result tables without leaving the report.

## Overview

The full test-results table (from the HTML Report Format epic) already filters by status, but with hundreds of rows there's no way to jump to a specific rule, test, or object short of Ctrl+F, and no way to reorder by anything but the status buckets already provided — this adds a search box and clickable sortable column headers so a reader can narrow and reorder the table themselves. Because the report must stay self-contained (uploaded as a CI artifact with no network access), and live substring search can't be expressed in CSS alone, this introduces a small amount of inline (non-external) JavaScript into the shared renderer — the first departure from the report's pure-CSS history, scoped tightly and reflected in an updated no-JS test.

---

## Task: Add sortable column headers

Each header cell of the full test-results table becomes clickable, reordering rows by that column ascending on first click, descending on second.

**Requirements**:
- Given a reader clicks a column header, should rows in that table re-order by that column's text, ascending; given they click it again, should the order reverse
- Given rows are reordered, should the active status filter (`data-status` + radio) and the search box still apply correctly against the new order
- Given an envelope has no `test_results` (legacy findings-only table, or the run index), should headers stay plain — no sort affordance, no script emitted

## Task: Add free-text search

A search input above the full test-results table hides any row whose visible text doesn't match, live as the reader types.

**Requirements**:
- Given a reader types in the search box, should every row whose cell text doesn't contain the (case-insensitive) query hide immediately, with no page reload
- Given the search box is cleared, should every row hidden only by the search reappear, without disturbing the active status filter
- Given the combination of search text and status filter matches zero rows, should a "No matching rows" message appear in place of an empty table

## Task: Scope the inline script to the shared full-list renderer

One small script, emitted once per report, drives both features; it must not leak into paths that don't have a full test list.

**Requirements**:
- Given `render_report` takes an envelope with no `test_results`, should the output contain no `<script>` tag and render exactly as before
- Given the run index (`render_index`) links to reports rather than rendering test rows itself, should it stay untouched — no search, sort, or script
- Given the script is present, should it contain no external references (no `src=`, no `fetch`, no `http(s)://`) — the only relaxation from the prior no-JS rule is that inline script is now permitted, not that external resources are

## Task: Update the no-JS test and the module's stated contract

The existing test and docstring both assert zero JavaScript; both need to describe the new, narrower invariant.

**Requirements**:
- Given `test_full_list_filter_control_uses_no_javascript`, should it be renamed and rewritten to assert no *external* script/resource reference rather than no script at all
- Given `_report_html.py`'s module docstring and inline comments describe the filter as "pure CSS, no script", should they be corrected to describe the inline-JS search/sort behavior and the self-contained (no external fetch) invariant that actually holds

## Task: Document the change for all three callers

**Requirements**:
- Given a human reads `.github/skills/fab-test/SKILL.md` or `README.md`, should they learn the full test-results table can be searched and sorted, and that the report is no longer strictly script-free (still fully offline/self-contained)
- Given a future contributor adds a new analyzer's `test_results`, should the docs make clear search/sort come for free from the shared renderer — no per-analyzer work required
