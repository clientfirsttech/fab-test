# RDL Rule Coverage Epic

**Status**: 📋 PLANNED
**Goal**: Every `fab-test rdl` rule is proven by a real `.rdl` fixture named for it, and the Tier B rules from [plan/rdl-rule-set.md](../plan/rdl-rule-set.md) get checks.

## Overview

The RDL Static Analysis epic shipped 28 Tier A checks, but only DS-02 and QRY-01 have a fixture proving the check fires on a real Report Builder file; the other 26 are covered by synthetic XML in unit tests alone. Naming a fixture for its rule makes the gap visible, and `tests/test_rdl_fixture_rules.py` already enforces it: each `.fabric/artifacts/rdl/<RULE-ID>.rdl` must trip the rule it is named for, and a fixture whose rule has no check yet is a strict xfail that flips when the check lands. This epic closes the gaps that test and the rule set expose.

---

## Rule status

**Status**: ✅ DONE (2026-09-30)

Only verified rules are active. Each catalog rule has `"status": "active" | "planned"`; a planned rule neither runs nor appears in a run's results, while the docs list it as planned. Active today: STR-01, DS-02, DS-05, DS-07, QRY-01, QRY-02, QRY-04, ACC-03 (each has a real fixture). The other 20 Tier A rules are planned until theirs lands.

**Requirements**:
- Given a rule with no status, should be treated as active, so custom catalogs keep working
- Given a planned rule, should not run, and should have no `test_results` row or count in the run message
- Given an active rule, should have a check and a real fixture that trips it, enforced by `tests/test_rdl_rule_status.py`
- Given the rule reference, should list active and planned rules in separate tables

---

## Promote planned rules

For each family (parameters, layout/subreports, accessibility, query/data source): build the real `.rdl` in Report Builder, name it for the rule, confirm the rule fires, then set the rule `"status": "active"`.

---

## Isolating fixtures

`QRY-01.rdl` and `DS-03.rdl` also trip DS-01, DS-02, DS-05 and DS-07.

**Requirements**:
- Given a fixture named for one rule, should trip that rule and, where practical, no unrelated ones
- Given the fixture test, should assert the named rule fires; asserting no others is optional per fixture

---

## Tier A fixtures

Add a real `.rdl` per rule, in `.fabric/artifacts/rdl/`, for the 20 planned Tier A rules: DS-01, QRY-03, QRY-05, QRY-06, QRY-07, PRM-01, PRM-03, PRM-04, PRM-05, LAY-01..LAY-06, SUB-01 (fires via LAY-03), SUB-02, ACC-01, ACC-02, ACC-08. Then set each to `"status": "active"`. Known risks to check against the real file when promoting: LAY-05 flags every table (the default `Details` group counts as a group), QRY-03 treats any quoted second argument as a dataset scope and misses nested parentheses, SUB-01 shares LAY-03's switches.

**Requirements**:
- Given each fixture, should be authored or round-tripped in Report Builder rather than hand-written XML, so it reflects a real file
- Given `SUB-01.rdl`, should fire as the single `LAY-03/SUB-01` finding, not two

---

## Tier B checks

Implement the rules marked B that need richer analysis than a presence check: STR-03, DS-03, DS-04, DS-06, PRM-02, PRM-06, ACC-04, ACC-05, ACC-06.

**Requirements**:
- Given `DS-03.rdl`, should fire DS-03 and turn the strict xfail in `tests/test_rdl_fixture_rules.py` into a pass
- Given each new rule, should be added to `rdl-rules.json` with `source_urls`, a fixture, and an entry in the check table, test-first
- Given ACC-04, should confirm the saved element name for structure types in a real Report Builder file before checking it

---

## Tier C triage

STR-02, LAY-07, SUB-03..SUB-06 and ACC-07 need a template, the network, other reports in the workspace, or manual review.

**Requirements**:
- Given each rule, should be recorded as deliberately out of scope for static analysis or given its own task, with the reason
