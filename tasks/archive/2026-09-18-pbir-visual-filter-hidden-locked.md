# PBIR Visual Filter Hidden And Locked Epic

**Status**: ✅ COMPLETED (2026-09-18)
**Goal**: Require visual-level filter-pane filters to be hidden and locked in view mode without restricting page- or report-level filters.

## Overview

WHY report consumers need page- and report-level filters to remain available while visual-level filters stay protected as development settings, the core PBIR rules distinguish filter scope and independently enforce the hidden and locked view-mode states.

---

## Confirm PBIR Filter Contract

Established `filterConfig.filters[].isLockedInViewMode` from the updated ThinReport fixture.

**Requirements**:
- Given a PBIR visual with a locked and an unlocked filter, should identify the exact Inspector data path that distinguishes their view-mode lock state.
- Given no evidence for an Inspector field path, should stop before changing the production ruleset rather than infer a field name.

---

## Add Independent Visual Filter Rules

Added error-level hidden and locked rules that evaluate only visual-level filters when the filter pane is enabled.

**Requirements**:
- Given the filter pane is enabled and a visual-level filter is visible in view mode, should fail the hidden-state rule with the offending visual name.
- Given the filter pane is enabled and a visual-level filter is unlocked in view mode, should fail the locked-state rule with the offending visual name.
- Given a visual-level filter violates both states, should report failures from both independent rules.
- Given the filter pane is disabled, should skip both visual-filter rules.

---

## Cover Filter Scope And State Permutations

Added focused rule-contract fixtures that prevent false positives across filter scope and configuration state.

**Requirements**:
- Given a visual-level filter is hidden and locked in view mode, should pass both rules.
- Given a visual-level filter is visible but locked, should fail only the hidden-state rule.
- Given a visual-level filter is hidden but unlocked, should fail only the locked-state rule.
- Given a visual has no filters, should pass both rules.
- Given visible or unlocked page-level or report-level filters, should not trigger either visual-level rule.
- Given a report mixes compliant and noncompliant visual filters, should return only the names of offending visuals.

---

## Validate The Shipped Ruleset

Exercised the packaged rules through focused tests and the installed `fab-test pbir` command.

**Requirements**:
- Given the focused PBIR rule tests run, should verify every filter-pane, scope, and hidden/locked permutation without requiring a cloud connection.
- Given the installed CLI evaluates a representative PBIR artifact, should surface each new error rule through the existing result envelope and nonzero exit behavior.