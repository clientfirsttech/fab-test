# PBIR Visual Filter Panel Double-Count Epic

**Status**: ✅ IMPLEMENTED 2026-10-31. Cross-rule "double counting" investigated and closed as by-design (no code bug); the hidden-visual false positive was real and is fixed.
**Goal**: `NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL` reports each offending visual once in whatever fab-test surfaces as "the count," and never flags a visual whose dev-only filter is hidden from the viewer by the visual itself being hidden.

## Overview

Two separate problems were reported together and need to be told apart before either gets fixed:

**Double counting.** The rule JSON itself ([src/fab_test/metadata/rules/pbi-inspector-custom-rules.json:833-887](src/fab_test/metadata/rules/pbi-inspector-custom-rules.json#L833)) adds each visual name once via `map`/`filter` over `{"part": "Visuals"}` — it doesn't double-add a single visual internally. The most likely real source: `NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL` and its sibling `NO_VISUAL_LEVEL_FILTERS_UNLOCKED_IN_FILTER_PANEL` ([:889-943](src/fab_test/metadata/rules/pbi-inspector-custom-rules.json#L889)) were deliberately made independent rules in `tasks/archive/2026-09-18-pbir-visual-filter-hidden-locked.md`. A dev filter that's both visible *and* unlocked — the common case when someone forgets to clean it up — legitimately fails both rules, so it shows up as 2 entries in whatever totals `summary`/`invoke_pbir_inspector` roll up ([src/fab_test/scripts/fab_test_summary.py:673](src/fab_test/scripts/fab_test_summary.py#L673) sums errors across all findings). That may be "double counting" by design (two distinct, independently-actionable rule violations) rather than a bug — needs a decision, not just a fix. Separately, `tests/test_pbir_filter_pane_rules_live.py:60-85` (`_flagged`) tolerates two different native PBIR Inspector result shapes (per-visual Result vs. per-report Result with an `Actual` list of names) and branches on which one it got; if the production path in `invoke_pbir_inspector.py` doesn't branch the same way, a given run could surface the same visual through two differently-shaped findings. This needs confirming against the real (non-test) parsing path, not assumed from the test's tolerance.

**Hidden-visual false positive.** The rule only reads filter-level `isHiddenInViewMode` on each visual's `filterConfig.filters`; it never looks at the visual's own visibility (e.g. an `isHidden`/hidden-in-view state on the visual itself, used for dev-only visuals parked off-canvas or toggled by a bookmark). So a visual that's entirely hidden from the viewer, but whose filter is internally marked visible/unlocked, still gets flagged — a false positive, because nothing in the filter panel can actually show that filter if the visual itself never renders. No existing fixture exercises "visual is hidden, its filter is not" — `tests/test_pbir_filter_pane_rules_live.py` only covers filter-level hidden/locked/neither/none permutations on visible visuals (visuals `2524…`/`4230…`/`7a1f…`/`ae85…`/`df89…` in `ThinReport`).

Decisions to approve:

1. **Is cross-rule double counting a bug or by design?** Default position: by design — `VISIBLE` and `UNLOCKED` are independently actionable (you can fix one without the other), so one dev filter legitimately produces two findings. If approved, the fix is scoped to documentation/summary presentation (e.g. grouping by visual in human-readable output), not to the rules themselves. If the user disagrees and wants one combined finding per visual, that's a larger rule-authoring change and should be split into its own epic.
2. **Confirm or rule out the result-shape double-count** by reproducing against the actual `invoke_pbir_inspector.py` parsing path (not just the test's tolerant branch) before writing a fix — this epic's first workstream is that reproduction, and later workstreams depend on its outcome.
3. **Hidden-visual semantics**: use whatever field PBIR already uses elsewhere for "visual itself is hidden" (confirm exact JSON path during implementation — e.g. visual group/bookmark-driven hidden state in `visual.json`) rather than inventing a new one.
4. **Scope**: `NO_VISUAL_LEVEL_FILTERS_UNLOCKED_IN_FILTER_PANEL` has the same `some(..., isHiddenInViewMode != true)` shape and the same missing visual-visibility check, so the hidden-visual fix applies to both rules, not just `VISIBLE`.

---

## Reproduce the double-count against the production path

**Requirements**:
- Given `ThinReport`'s existing visible+unlocked dev filter, run `fab-test pbir` (not the test harness) and record the raw finding count and shape for both rules
- Given the two rules independently flag the same visual, should confirm whether fab-test's human-readable summary or any single-number "error count" presents this as one visible-and-unlocked issue or as two unrelated-looking errors — this determines whether workstream 2 is needed
- Given PBIR Inspector's actual output shape in this run, should confirm whether `invoke_pbir_inspector.py`'s parsing takes the same branch `tests/test_pbir_filter_pane_rules_live.py::_flagged` does, or whether a shape mismatch could cause a genuine duplicate finding for one visual under one rule

**Done 2026-10-31.** Ran `fab-test pbir fabric-artifacts/ThinReport.Report` directly (not the test harness). `envelope.json` and the raw `native.json` both show exactly one `Result`/finding per filter-pane rule, report-level (`ItemPath: \definition\report.json`), each with one `Actual` array naming every offending visual for that rule -- never one result per visual, and never two results for the same rule. `df89a190bca70b12b743` (one filter, neither hidden nor locked) appears once in `VISIBLE`'s `Actual` and once in `UNLOCKED`'s `Actual`: two distinct findings for two distinct properties of the same filter, not a duplicate. No result-shape mismatch exists in the production path -- `_flagged`'s tolerance for a "one Result per visual" shape in the test helper is defensive code for a shape this ruleset never actually produces, not evidence of a bug; left as-is (removing it is unrelated cleanup, not this epic's job). **Decision 1 and 2 resolved: by design, not a bug.**

---

## Fix or document the cross-rule count (pending decision 1)

**Requirements**:
- Given the decision is "by design", should add a short note to the rule descriptions (and/or the filter-pane rule section of the fab-test skill docs) stating that a visible-and-unlocked filter trips both rules on purpose, so users aren't surprised by "2 errors for 1 filter"
- Given the decision is "combine them", should be split into its own epic scoped to rule-authoring (out of scope here)

**Done 2026-10-31.** Added a paragraph to `src/fab_test/skill/references/configuration.md`'s "Writing a PBIR Inspector rule" section (synced to the packaged copy, `tests/test_skill_resource.py` passing) explaining that the two rules are independent on purpose and a visible-and-unlocked filter correctly produces two findings for one visual. Rule descriptions in the JSON were left alone -- the skill doc is where a user reading rule output goes looking, and is also where the earlier filter-pane epic put its "writing a rule" guidance.

---

## Hidden-visual fixture and rule fix

**Requirements**:
- Given a visual that is itself hidden (per decision 3's confirmed field) with a visible, unlocked visual-level filter, should NOT be flagged by either `NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL` or `NO_VISUAL_LEVEL_FILTERS_UNLOCKED_IN_FILTER_PANEL`
- Given a visual that is hidden but has no visual-level filter at all, should continue to never be flagged (unchanged)
- Given a visible visual with a visible/unlocked filter, should continue to be flagged (no regression on the existing behavior this rule was written to catch)
- Given the rule JSON changes required, should keep `"part": "Report"`, the existing mapping shape, and rule ids/names/`logType`/enabled state unchanged, per the precedent in `tasks/archive/2026-10-09-pbir-filter-pane-rules.md`

**Done 2026-10-31.** Both rules' `filter` step now wraps the existing `some(...)` check in `"and": [{"!": [{"var": "isHidden"}]}, {"some": [...]}]`, same style and same field `REMOVE_CUSTOM_VISUALS_NOT_USED`'s sibling rule `REDUCE_VISIBLE_VISUALS_ON_PAGE` already reads directly off a `{"part": "Visuals"}` entry with no mapping needed. `part: Report`, the `filterPaneVisible` mapping, `[]` expected, ids, names, `logType: error` and `disabled: false` all unchanged. Verified live: a copy of `ThinReport` with `df89a190bca70b12b743`'s `visual.json` given `"isHidden": true` drops that visual from both rules' `Actual` lists; `2524...`/`4230...`/`ae85...` (still visible) are unaffected, and the unmodified `ThinReport` itself is unaffected (still 4 findings, same visuals named).

---

## Tests

**Requirements**:
- Given a new fixture variant of `ThinReport` (built in `tmp_path`, following the existing live-test pattern, not a second checked-in report) with one visual's hidden-visibility field set and an otherwise-noncompliant filter, should add a live test case to `tests/test_pbir_filter_pane_rules_live.py` asserting that visual is never named by either rule
- Given the structural tests in `tests/test_pbir_visual_filter_rules.py`, should extend them to pin whatever new mapping/logic the hidden-visual check adds, the same way they pin `part: Report` and the `[]` expected value today
- Given PBIR Inspector cannot be resolved where the suite runs, should skip with the reason rather than pass vacuously (matching existing convention in the same test file)
- Given the double-count reproduction in workstream 1 found a genuine shape-mismatch bug (not just by-design dual rules), should add a regression test asserting the production parsing path and the test's `_flagged` helper agree on result shape

**Done 2026-10-31.** Added `test_given_a_hidden_visual_with_a_noncompliant_filter_should_not_be_flagged` to `tests/test_pbir_filter_pane_rules_live.py` (hides `df89...` in a `tmp_path` copy, asserts both rules' flagged sets drop exactly that visual). Added `test_visual_filter_rules_exclude_a_visual_that_is_itself_hidden` (parametrized over both rule ids) to `tests/test_pbir_visual_filter_rules.py`, pinning `"isHidden"` in the rule logic and confirming it's not in the mapping (read directly off the visual, like `REDUCE_VISIBLE_VISUALS_ON_PAGE`). Both new tests use the same `inspector` skip fixture as their neighbors. Last requirement dropped: workstream 1 found no shape-mismatch bug, so there is nothing to regression-test. `pytest tests/test_pbir_visual_filter_rules.py tests/test_pbir_filter_pane_rules_live.py`: 10 passed.

---

## Documentation

**Requirements**:
- Given a rule behavior change (hidden-visual exemption), should add a CHANGELOG entry (bug fix, with before/after) and bump the prerelease version per the beta series
- Given the cross-rule count decision, should update the fab-test skill's filter-pane rule guidance to match whichever outcome was chosen

**Done 2026-10-31.** CHANGELOG entry added under 2026-10-31 (behavior change: hidden visuals are now exempt), naming the before/after and that the cross-rule count was investigated and closed as by-design. No version bump: `1.9.0b11` is still unreleased on this branch (no `📦 Version` entry since 2026-10-10's bump to it), matching the precedent in `tasks/archive/2026-10-09-pbir-filter-pane-rules.md`. Skill guidance update covered under "Fix or document the cross-rule count" above.

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
- Given the installed console script, should run `fab-test pbir` on `ThinReport` and its hidden-visual fixture variant and see the same visuals named as the tests assert

**Passed 2026-10-31.** `ruff check .` clean over the whole repo. `tests/test_complexity_budget.py`, `tests/test_module_budget.py` and `tests/test_skill_resource.py` (packaged skill-copy parity) all pass. Full suite minus playwright-marked (`pytest -n auto -m "not playwright" --cov`): 2992 passed, 2 skipped, 0 failed, 87% coverage (floor 80%). Live through the installed console script against a manually built hidden-visual copy of `ThinReport` (`isHidden: true` on `df89...`): both filter-pane rules drop that visual and keep naming the others, matching the automated tests.
