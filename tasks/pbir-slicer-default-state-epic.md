# PBIR Slicer Default State Epic

**Status**: 🔄 IN PROGRESS on `feature/pbir-slicer-default-state` — discovery decisions recorded 2026-11-14; Test Bed, Contract Format and Calendar Resolution done 2026-11-14; Contract To JSON Logic next.
**Goal**: `fab-test pbir` checks the values a report's slicers open with, from a per-report ODCS contract that `fab-test pbir contract init` builds with the developer or their agent.

**Decisions** (recorded 2026-11-14 at discovery review, journey [pbir-slicer-default-state.yaml](../plan/story-map/pbir-slicer-default-state.yaml)):

1. ✅ **Scope** is the values preselected in a slicer (`visual.objects.general[].properties.filter`): the standard `slicer` (field parameters included), date slicers (Between, Relative, Date picker) and the input slicer (`textSlicer`). The bookmark navigator default and bookmark/visibility sync are later stories in the journey.
2. ✅ **Tests are a per-report ODCS v3.1 contract**: `type: custom`, `engine: fab-test` quality rules on the slicer's column, with page, expected values and calendar in `implementation`, validated by a fab-test JSON Schema. pql-test already skips other engines' custom rules, so one file can carry both.
3. ✅ **Building**: `fab-test pbir contract init` finds the slicers and their current selections and asks how to check each. Its questions are data: `--questions --format json` prints them with suggested answers, `--answers FILE` applies them, and it prompts only on a terminal. It creates or appends, supports `--dry-run`, and never overwrites a hand edit without `--force`. `contract` becomes a reserved word in pbir's TARGET position.
4. ✅ **Running**: `fab-test pbir` compiles a report's paired contract into JSON Logic for that report only; `--contract FILE` names one explicitly and `--as-of DATE` fixes the calendar date. The envelope records the date and every resolved value.
5. ✅ **Calendar values** are format strings over named fields (`{fiscal_year_short}`, `{fiscal_semester}`, ...) resolved from the contract's own calendar (fiscal-year start month, named by start or end year). Nothing is evaluated.
6. ✅ A stale calendar-driven default is an `error`.
7. ✅ A contract lives **outside** the item folder (Fabric's Commit to Git deletes non-definition files inside it) and pairs with its report by the `.platform` `logicalId`.
8. ✅ ODCS support for pql-test stays its own epic ([odcs-contract-analyzer-epic.md](odcs-contract-analyzer-epic.md)).
9. ✅ fab-test (MIT) never imports pql-test (AGPL-3.0-only) code; anything it borrows from pql-test goes through the CLI.

## Overview

WHY: a customer agrees what a report opens with, and every edit risks saving a working selection over it; a default that follows the calendar goes stale at rollover with no commit to trigger CI. `rules.pbir.extend` can check one today, but only through JSON Logic written against hex visual IDs and DAX-quoted literals, and it runs against every report in the run. This epic lets a developer — or their agent — capture each slicer's agreed selection once, as fixed or calendar-driven, in a per-report contract that `fab-test pbir` compiles into Fab Inspector rules for that report only.

---

## Test Bed

A PBIR report on SampleModel with one preselected example per slicer kind, validated and rendered in Desktop, for review before any code.

**Requirements**:
- Given SampleModel-PQLAssert, should add a disconnected `Fiscal Calendar` calculated table and a `Chart Measure` field parameter without changing any existing table, measure or relationship.
- Given each slicer kind in scope, should hold one preselected example, plus a calendar-driven semester, a second calendar label format, and an unselected near-miss.
- Given each example, should record whether its selection JSON matches a shape Desktop wrote or was hand-authored and only rendered, so a Desktop save confirms the canonical shape before a rule depends on it.
- Given `powerbi-report-author validate` and a Desktop reload, should pass both with every preselection visible in a screenshot.
- Given the existing suite, should still pass: the new report must not change any pinned artifact list.

---

## Contract Format

The `engine: fab-test` rule shape and its JSON Schema, with the test bed's contract as the worked example.

**Requirements**:
- Given a contract, should validate the ODCS envelope and the `implementation` block, naming the JSON path of each error.
- Given a slicer, should identify it by page display name and bound field, never by visual ID.
- Given an expected value, should accept what the user sees ("Good", 2026, a date) and encode the DAX literal itself.

---

## Calendar Resolution

Format fields from an as-of date and a contract's calendar.

**Requirements**:
- Given a fiscal-year start month and naming, should resolve fiscal year, semester, quarter and month for any as-of date, the fiscal-year boundary included.
- Given an unknown field in a format string, should exit 2 naming it and the valid fields.

---

## Contract To JSON Logic

`fab-test pbir` compiles a report's paired contract into Fab Inspector rules for that report.

**Requirements**:
- Given a report with a paired contract, should add only that report's rules to its resolved ruleset; a report without one runs unchanged.
- Given a slicer whose selection differs, should report a finding naming page, field, expected and actual.
- Given `--as-of`, should resolve against that date and record it and every resolved value in the envelope.
- Given each slicer kind in the test bed, should pass on its contract and fail on a one-value change (a fixture pair per kind, like RDL's `-Pass`).

---

## Contract Init Generator

`fab-test pbir contract init` finds slicers, asks how to check each, and writes or appends the contract.

**Requirements**:
- Given a terminal, should ask per slicer whether to keep the current selection, follow the calendar (proposing calendar settings that reproduce the current value), or skip it.
- Given `--questions --format json`, should print every question with its choices, a suggested answer and whether it needs a human; given `--answers FILE`, should apply them without prompting.
- Given no terminal and no answers, should exit 2 naming `--questions` and `--answers`, never wait for input.
- Given an existing contract, should append new slicers, keep hand-edited rules, and refuse to change an edited rule without `--force`.

---

## Callers

The agent skill, human docs and pipeline YAML, the scheduled run included.

**Requirements**:
- Given the fab-test skill, should teach an agent the questions, ask, answers loop without restating the questions.
- Given the docs, should show a scheduled workflow that catches a rollover with no commit.

---

## Quality Gates

Whole-repo ruff, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them.

**Requirements**:
- Given the vision's Definition of Done, should pass every gate with all three callers documented.
