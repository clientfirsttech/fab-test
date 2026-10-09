# PBIR Filter Pane Rules Epic

**Status**: ✅ COMPLETED 2026-10-09 (1.9.0b10; shipped in `5a533f5`)
**Goal**: Make `NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL` and `NO_VISUAL_LEVEL_FILTERS_UNLOCKED_IN_FILTER_PANEL` flag exactly the visuals whose visual-level filters are visible or unlocked, and nothing when the report's filter pane is disabled.

## Overview

Both rules are wrong in every report today, in opposite directions depending on the expected value: as shipped they flag every visual (false positives), and the override another project wrote -- expected `true` instead of `[]` -- passes every visual (false negatives), so it silences the rules rather than fixing them. Measured 2026-10-09 with PBIR Inspector 3.4.0 against `ThinReport` (3 visuals with an unhidden visual filter, 3 with an unlocked one) and a copy with `outspacePane` set to `"false"`, using probe rules:

1. **Type mismatch.** The test is `if(...)` and returns a boolean; the expected value is `[]`, which a boolean never equals, so every visual fails -- including one with no filters at all.
2. **The data mapping hides the visual.** Declaring `{"outspacePaneVisible": "/objects/..."}` makes PBIR Inspector evaluate the logic against the mapped variables only, so `filterConfig.filters` is null and `!some(null)` is `true` for every visual. (Probe: the same `some` test returns the correct per-visual answer with an empty mapping, and `False` everywhere once the mapping is added.)
3. **The pane setting is unreachable from a visual.** `outspacePane` lives in `report.json`; with `"part": "Visuals"` the JSON pointer is resolved against each `visual.json` and is `None` whether the pane is on or off, so the "filter pane disabled" exemption has never applied.

A report-level rule fixes all three, using the same nested-`{"part": "Visuals"}` shape `REMOVE_CUSTOM_VISUALS_NOT_USED` already relies on: map the pane setting from `report.json`, and when it is not `"false"`, return the names of visuals with a non-hidden (or non-locked) visual filter, expecting `[]`. Probed: it returns exactly the 3 expected visuals per rule with the pane on, and `[]` (pass) with the pane off. The other 17 rules were checked for the same two defects (expected-value type, mapping hiding unmapped fields) and have neither.

---

## Behavioral rule tests

Replace text-shape assertions with tests that run PBIR Inspector on fixtures and assert which visuals each rule names. The existing `tests/test_pbir_visual_filter_rules.py` only checks the rule JSON contains certain strings, which is how an always-failing expected value shipped.

**Requirements**:
- Given `ThinReport` with the filter pane in its default (visible) state, should report exactly the visuals with a visual-level filter that is not hidden (`VISIBLE` rule) or not locked (`UNLOCKED` rule)
- Given the same report with `outspacePane.visible` set to `"false"`, should pass both rules with no visual named
- Given a visual with no visual-level filters, or whose filters are all hidden and locked, should never be named
- Given page- or report-level filters that are visible or unlocked, should not be flagged (they are consumer controls)
- Given the pane-off variant, should be produced at test time from `ThinReport` in `tmp_path` rather than as a second checked-in report
- Given PBIR Inspector cannot be resolved where the suite runs, should skip with the reason rather than pass vacuously

**Done 2026-10-09.** `tests/test_pbir_filter_pane_rules_live.py` (`integration`, `pbir`) copies `ThinReport` into `tmp_path` -- as-is, with the pane off, and with an unhidden/unlocked page- and report-level filter added -- runs `fab-test pbir`, and reads the visuals each rule names from either result shape. All three failed against the shipped rules (all 5 visuals flagged in every case) before the rewrite.

---

## Rewrite both rules at report level

**Requirements**:
- Given each rule, should use `"part": "Report"`, map only the pane setting (`/objects/outspacePane/0/properties/visible/expr/Literal/Value`), and inside `if(pane != "false")` map the filtered nested `{"part": "Visuals"}` to visual names, expecting `[]`
- Given the filter pane disabled, should return `[]` (pass) without inspecting any visual
- Given `outspacePane` absent from `report.json` (Power BI's default: visible), should evaluate the visuals
- Given a failing report, should name each offending visual in the finding's actual value, so the finding says which visuals to fix
- Given the existing rule ids, `logType: error`, and enabled state, should keep them unchanged so overlays and suppressions that reference the ids keep working

**Done 2026-10-09.** Both rules are `"part": "Report"` with mapping `{"filterPaneVisible": "/objects/outspacePane/..."}` and expected `[]`; ids, names, `error` and enabled state unchanged, descriptions extended with why the rule is report-level. The three live tests pass; the structural tests in `tests/test_pbir_visual_filter_rules.py` now pin `part: Report`, the mapping, and `[]`. Live through the CLI with the shipped rules: `ThinReport` gets one finding per rule naming exactly the three offending visuals; the pane-off copy gets none.

---

## Overlay guidance

**Requirements**:
- Given a project that copied the `true`-expected override, should document in CHANGELOG that the override disables both rules in effect and should be removed once on this release
- Given the rule-overlay docs, should note that a rule's expected value must match the type its test returns, and that a non-empty data mapping replaces the data the logic sees -- the two traps found here

**Done 2026-10-09.** CHANGELOG says the `true`-expected override switches both rules off and should be removed. The skill's `references/configuration.md` (Rule Overlays) gains "Writing a PBIR Inspector rule": the expected-value type, the mapping that replaces the data, pointers resolving against the rule's `part`, and how to check a rule against a fixture; packaged copy synced.

---

## Document and release

**Requirements**:
- Given a rule behavior change, should add a CHANGELOG entry (bug fix, with the before/after) and bump the prerelease version per the beta series
- Given the fab-test skill or README describe these rules, should update the description; keep authored and packaged skill copies identical

**Done 2026-10-09.** CHANGELOG carries the fix with before/after. No version bump: `1.9.0b10` is still unpublished (PyPI's latest is `1.9.0b9`), so it ships there. README and the skill don't describe individual PBIR rules beyond the overlay guidance above.

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
- Given the installed console script, should run `fab-test pbir` on `ThinReport` and its pane-off copy and see the same visuals named as the tests assert

**Passed 2026-10-09** on the state committed as `5a533f5`: `ruff check .` clean; complexity and module-budget ratchets pass; full suite 2665 passed, 2 skipped, coverage 89.36%, under `GITHUB_ACTIONS=true CI=true`. Live through the installed CLI with the shipped rules: `ThinReport` gets one finding per rule naming exactly the three offending visuals, and its pane-off copy gets none.
