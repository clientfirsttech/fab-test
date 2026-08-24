# Sort Direction Indicator Epic

**Status**: ✅ COMPLETED (2026-08-24)
**Goal**: Show which column a full-list report table is sorted by, and in which direction.

## Overview

Clicking a column header in the full test-results table (Search and Sort epic) sorts it, but nothing on the page shows which column is active or whether it is ascending or descending — a reader has to infer direction from the row order alone, and loses track of it entirely after scanning the search box or a status filter. The header text should carry a visible arrow (▲/▼) on whichever column was sorted last, replacing any arrow left on a previously-sorted column.

---

## Task: Render and toggle the arrow

`_SEARCH_SORT_SCRIPT` in `_report_html.py` already tracks each header's own `ascending` flag in closure state; it has no shared way to know about *other* headers, and no DOM hook to write an arrow into.

**Requirements**:
- Given a column header is clicked, should append `▲` to its text when the resulting sort is ascending, or `▼` when descending
- Given a different column header is then clicked, should remove the arrow from the previously-sorted column's header
- Given no column has been sorted yet, should show no arrow on any header
- Given the arrow is appended to `th.textContent`, should not corrupt `th.click()`'s existing `cells[index].textContent` read used for sorting (the header cell itself is never a data cell, so this is a append-only concern, not a read-order one — confirm with a test rather than by inspection)
- Given the existing static-contract tests (`test_report_html_interactivity.py`) assert on `_SEARCH_SORT_SCRIPT`'s external-reference-free contract, should keep passing unchanged — the arrow is rendered by the same inline script, not a new one
