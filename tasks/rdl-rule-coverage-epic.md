# RDL Rule Coverage Epic

**Status**: 🔄 IN-PROGRESS
**Goal**: Every `fab-test rdl` rule is proven by a real `.rdl` fixture named for it, and the Tier B rules from [plan/rdl-rule-set.md](../plan/rdl-rule-set.md) get checks.

## Overview

The RDL Static Analysis epic shipped 28 Tier A checks, but only DS-02 and QRY-01 have a fixture proving the check fires on a real Report Builder file; the other 26 are covered by synthetic XML in unit tests alone. Naming a fixture for its rule makes the gap visible, and `tests/test_rdl_fixture_rules.py` already enforces it: each `fabric-artifacts/<RULE-ID>.PaginatedReport/<RULE-ID>.rdl` must trip the rule it is named for, and a fixture whose rule has no check yet is a strict xfail that flips when the check lands. This epic closes the gaps that test and the rule set expose.

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

**Status**: ✅ DONE (2026-10-10) except PRM-04

For each family (parameters, layout/subreports, accessibility, query/data source): build the real `.rdl`, name it for the rule, confirm the rule fires, then set the rule `"status": "active"`. 27 of 28 Tier A rules are active. PRM-04 is blocked: `updateDefinition`/create returns 400 for a MultiValue + Nullable parameter and 201 for the same file with AllowBlank, so the service itself refuses the shape the rule warns about.

---

## Isolating fixtures

**Status**: 🔄 ratchet in place (2026-10-10)

Every fixture added on 2026-10-10 trips only its rule (QRY-07 also trips DS-07: long inline SQL is inline SQL). The seven hand-built fixtures (ACC-03, DS-05, DS-07, QRY-01, QRY-02, QRY-04, STR-01) still trip others; `_KNOWN_EXTRA` in `tests/test_rdl_fixture_rules.py` lists each exactly, so it can only shrink. (The old `DS-03.rdl` was a `SELECT *` file, not a DS-03 fixture, and was removed on 2026-10-01.)

**Requirements**:
- Given a fixture named for one rule, should trip that rule and, where practical, no unrelated ones
- Given the fixture test, should assert the named rule fires; asserting no others is optional per fixture

---

## Tier A fixtures

**Status**: ✅ DONE (2026-10-10) except PRM-04, see Promote planned rules

Each fixture is derived from `DS-02.rdl` (Power Query) plus one edit, with `SampleModel-PQLAssert` in fab-test [Dev] as the semantic-model source and the escape-room Azure SQL source for DS-01/QRY-07; all were deployed to fab-test [Dev] by the service principal and saved from `getDefinition`, byte-identical to what was sent. LAY-05 and QRY-03's false positives were fixed before promotion. Open: SUB-01 has no switch of its own, since disabling LAY-03 in an overlay silences both.

Add a real `.rdl` per rule, as `fabric-artifacts/<RULE-ID>.PaginatedReport/`, for the 20 planned Tier A rules: DS-01, QRY-03, QRY-05, QRY-06, QRY-07, PRM-01, PRM-03, PRM-04, PRM-05, LAY-01..LAY-06, SUB-01 (fires via LAY-03), SUB-02, ACC-01, ACC-02, ACC-08. Then set each to `"status": "active"`. Known risks to check against the real file when promoting: LAY-05 flags every table (the default `Details` group counts as a group), QRY-03 treats any quoted second argument as a dataset scope and misses nested parentheses, SUB-01 shares LAY-03's switches.

**Requirements**:
- Given each fixture, should be one small edit to a real Report Builder file (a Power Query or semantic-model source from this repository), deployed to the workspace and saved from the service's `getDefinition`, so the service has accepted the file that is committed
- Given a rule the service rejects on upload, should stay planned with the rejection recorded here
- Given `SUB-01.rdl`, should fire as the single `LAY-03/SUB-01` finding, not two

---

## Tier B checks

**Status**: 🔄 6 of 9 active (2026-10-10) — STR-03, DS-03, DS-04, DS-06, PRM-02, ACC-06, each with a service-accepted fixture. ACC-04/ACC-05 are blocked on one Report Builder save to confirm the structure-type element name. PRM-06 is folded into QRY-01, which already flags every report-side filter, so a separate rule would repeat its findings.

Implement the rules marked B that need richer analysis than a presence check: STR-03, DS-03, DS-04, DS-06, PRM-02, PRM-06, ACC-04, ACC-05, ACC-06.

**Requirements**:
- Given a real `DS-03.rdl` (a parameter whose valid values come from a dataset), should fire DS-03; a fixture added before its check exists stays a strict xfail in `tests/test_rdl_fixture_rules.py` until the check lands
- Given each new rule, should be added to `rdl-rules.json` with `source_urls`, a fixture, and an entry in the check table, test-first
- Given ACC-04, should confirm the saved element name for structure types in a real Report Builder file before checking it

---

## Tier C triage

STR-02, LAY-07, SUB-03..SUB-06 and ACC-07 need a template, the network, other reports in the workspace, or manual review.

**Status**: ✅ DONE (2026-10-10). Out of scope for static analysis: STR-02 (needs a team template to compare against), LAY-07 (needs the network; `rdl` stays offline), SUB-05 and SUB-06 (deployment and migration practice, not RDL content), ACC-07 (manual review). Own task: SUB-03 (a child `.rdl` in the same repository can be checked, but the engine reads one file at a time) and SUB-04 (service mode only, needs the workspace's item list).

**Requirements**:
- Given each rule, should be recorded as deliberately out of scope for static analysis or given its own task, with the reason

---

## Pass fixtures

**Status**: ✅ DONE (2026-10-10). 33 `-Pass` fixtures, each service-accepted then deleted from Dev; only QRY-07-Pass trips another rule (DS-07). The pre-fix QRY-03 and LAY-05 checks fail 6 of them, so they guard real false positives. PRM-04 has none while it stays planned.

Give every active rule a near-miss fixture, `fabric-artifacts/<RULE-ID>-Pass.PaginatedReport/<RULE-ID>-Pass.rdl`, that must not trip it, so a false positive fails a test against a real file.

**Requirements**:
- Given an active rule, should have a `-Pass` fixture, enforced like its tripping fixture
- Given a `-Pass` fixture, should be the remediated form or a threshold just short of firing, and should trip no rule at all unless a shrink-only allowlist names the unavoidable one
- Given a `-Pass` fixture that trips its rule, should fix the check test-first, not the fixture
- Given each `-Pass` fixture, should be accepted by the service on upload, then removed from the workspace so Dev runs don't grow

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
