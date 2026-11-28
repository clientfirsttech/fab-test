# PBIR Bookmark Navigator Default Epic

**Status**: ✅ IMPLEMENTED (2026-11-15) on `feature/pbir-slicer-default-state`, not merged or archived: the decisions below await the user's review, and the nothing-preselected navigator awaits a Desktop save. AIDD review done (no blocking findings; three should-fix and the nits fixed). Gates pass: ruff, both ratchets, 3175 + 217 tests, coverage 90.55%, CI-env run, no known vulnerabilities (the only failures are tests/test_rtk_hook_safety.py, from a locally deleted hook file).
**Goal**: a report's slicer contract also says which bookmark each bookmark navigator opens with, and `fab-test pbir` fails when it drifts.

**Decisions** (provisional, made 2026-11-15 while the user was away; review before merge. Journey story "Bookmark navigator default", [pbir-slicer-default-state.yaml](../plan/story-map/pbir-slicer-default-state.yaml)):

1. **Scope** is the navigator's preselected bookmark (`visual.objects.bookmarks[0].properties.selectedBookmark`, the bookmark's `name` as a DAX string), as Desktop saved it on 2026-11-15. Bookmark groups on a navigator, and whether a bookmark's captured state still matches its page ("Bookmark visibility sync"), are out of scope.
2. **Contract shape**: a navigator has no table or column, and ODCS v3.1 attaches quality rules only to schema objects and properties, so navigators go in a `fabTestBookmarkNavigators` custom property beside `fabTestReport` and `fabTestCalendar`: a list of `{id, page, selected, severity?}`. pql-test ignores it.
3. **Bookmarks are named by display name** (`selected: Bookmark 2`), never by their internal name; fab-test looks the name up in `definition/bookmarks/*.bookmark.json` (only those `bookmarks.json` lists) when it compiles the rule. A display name two bookmarks share matches neither, since it can't say which. `selected: null` means nothing preselected. The preselection only highlights a bookmark; it doesn't apply it on open.
4. **Drift is a finding, never a pass**: a contract naming a bookmark the report doesn't have, a navigator preselecting a deleted bookmark, a page with no navigator, and a renamed page each fail. A malformed entry is exit 2, as for slicers.
5. **A rule checks every navigator on its page**, as a slicer rule checks every slicer on its column; `init` offers `skip` when two navigators on a page differ.
6. **`init` asks about navigators** with `keep`/`skip`, in the same question list; ids are unique across slicers and navigators.

## Overview

WHY: a bookmark navigator highlights the bookmark the report is meant to open on, and an edit can save a different one (the last one clicked) with no review noticing. Slicer contracts already pin what slicers open with; this adds the navigator to the same per-report contract and check, so one `init` and one `fab-test pbir` cover the report's opening state.

---

## Test Bed

Desktop-saved navigators and bookmarks, plus the near-miss.

**Requirements**:
- Given SampleModel-DefaultState, should hold two Desktop-saved bookmarks and a navigator on each of two pages preselecting different bookmarks (one preselects a bookmark on another page).
- Given the false-positive case, should hold a navigator with nothing preselected (hand-authored until a Desktop save confirms the shape).
- Given the packaged PBIR rules, should add no finding other than the contract's intended one.

---

## Contract Format

`fabTestBookmarkNavigators` read and validated with the rest of the contract.

**Requirements**:
- Given a navigator entry, should read id, page, selected (a display name or null) and severity, naming each error by path.
- Given ids, should refuse one shared with a slicer rule or another navigator, and the reserved `page.` prefix.
- Given a contract with only navigator entries, should be read as a fab-test contract.

---

## Navigator Rules

Compile each entry into a page-scoped PBIR Inspector rule for that report.

**Requirements**:
- Given a navigator preselecting the expected bookmark, should pass; given another bookmark, nothing, or a deleted bookmark, should fail naming what it opens with by display name.
- Given `selected: null`, should pass only a navigator with nothing preselected.
- Given a contract naming a bookmark the report doesn't have, a page without a navigator, or a missing page, should fail.
- Given the envelope, should record each navigator rule with the bookmark's resolved name.

---

## Contract Init

`init` asks about each navigator.

**Requirements**:
- Given a navigator, should ask keep or skip, showing its preselected bookmark by display name (or "no bookmark").
- Given two navigators on a page with different preselections, or one preselecting a deleted bookmark, should offer only skip.
- Given an existing contract, should append new navigator entries and change an existing one only with `--force`.
- Given the test bed, should write a contract that passes the report it came from.

---

## Callers

Docs for people, agents and pipelines.

**Requirements**:
- Given the guide, walkthrough and skill reference, should show the navigator entry and its findings.

---

## ODCS References to Names with Spaces (follow-up, added 2026-11-17)

Make sure the report-test YAML fab-test writes stays valid ODCS when a model name has a space, as Power BI names usually do (found in pql-test: `to: Date_Dim.Date ID` fails schema validation).

**Requirements**:
- Given a `table.column` reference fab-test writes (a relationship end, or any future reference field), should write it only when both names match ODCS's shorthand pattern (letters, digits, `_`; v3.2 also `-`), because ODCS has no escape syntax: quotes, brackets, backticks, `\ `, and `%20` all fail.
- Given a name outside that pattern, should give the referenced schema object and property an `id` and write the reference as `schema/<object id>/properties/<property id>` (resolved by pql-test from the release after 0.3.0), never rename the element.
- Given `init`'s output, should validate it against the bundled ODCS schema in a test whose model has a table and a column with spaces in their names.

---

## AIDD Review

`aidd-review` over the whole epic diff before the gates; fix what it finds.

---

## Quality Gates

Whole-repo ruff, the complexity and module-budget ratchets, the coverage floor on the full suite, and the CI-env run.

**Requirements**:
- Given the vision's Definition of Done, should pass every gate with all three callers documented.
