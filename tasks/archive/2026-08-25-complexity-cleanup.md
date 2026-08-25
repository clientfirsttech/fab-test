# Complexity Cleanup Epic

**Status**: ✅ COMPLETED (2026-08-25)
**Goal**: Shrink the complexity ratchet in `tests/test_complexity_budget.py` below its current ceiling of 29, the way Complexity and Coverage (45 → 31) and Review Cleanup (31 → 29) already did twice.

## Overview

WHY: The ratchet only stops the report from growing — vision.md's own account of
why it exists is that an *unwatched* count drifted from 36 to 45 across two
epics before anyone looked, and it currently sits at exactly 29/29 with zero
slack, one new offender away from failing `test_the_complexity_report_does_not_grow`.
Every prior pass at this list found the same shape: functions that interleave
several concerns (subprocess call + parsing + envelope writing, or several
independent validators) in one body, and wrapper functions whose argument
lists grew one flag at a time. This epic works the remaining 29 findings down
the same way, in the same file groupings the report already implies.

---

## Shared `write_results` helper across the three wrappers

`invoke_pbir_inspector.py`, `invoke_pql_test.py`, and `invoke_tabular_editor_bpa.py`
each carry their own `write_results` at 10, 12, and 11 arguments (PLR0913 × 3).

**Requirements**:
- Given the three wrappers pass largely the same result fields to their own `write_results`, should extract a shared result-context object the way `run_tool` already consolidated their duplicated failure classification
- Given each wrapper has its own console-script caller (`bpa`, `pbir`, `pql-test`), should verify all three produce byte-identical envelopes for a known artifact before and after

## `_analyzer_envelope.py` envelope builders

`severity_rank` (9 returns, PLR0911) and `build_envelope` (9 args, PLR0913).

**Requirements**:
- Given `severity_rank` is a flat severity-to-rank lookup, should replace the return-per-branch shape with a table lookup
- Given `build_envelope` is called by every analyzer wrapper, should group its related arguments (timing, identity) into one small parameter object shared by all callers rather than duplicated per call site

## `resolve_executable` in `_analyzer_tool_bootstrap.py`

The single largest offender in that module (C901 17, PLR0912 15, PLR0915 58).

**Requirements**:
- Given it resolves a tool executable through several ordered fallback sources (config, env var, PATH, packaged default), should split each source into its own helper and keep `resolve_executable` as the ordered dispatch over them
- Given every analyzer wrapper calls this at startup, should verify `fab-test doctor`, `explain`, and one real analyzer run afterward, per vision.md's Blast Radius principle

## `run_inspector` in `invoke_pbir_inspector.py`

The largest single function in the whole report (C901 24, PLR0912 23, PLR0915 107).

**Requirements**:
- Given it interleaves subprocess invocation, output parsing, and envelope writing in one function, should split those three concerns into their own functions
- Given `run_inspector` is `fab-test pbir`'s only entry point, should verify its pytest contract test and, if a PBIR Inspector binary is available, a real run still produce the same envelope

## `validate_environments_yaml`

Third-largest in the report (C901 22, PLR0912 23, PLR0915 57).

**Requirements**:
- Given it validates workspace names, the promotion chain, and schema shape all in one function, should split those into separate validators that each return their own list of errors
- Given `fab-test doctor` and `config --validate` both resolve `environments.yml` through this function, should verify each still reports the same errors for a known-bad file after the split

## `_run_one_artifact` in `fab_test.py`

Sits in the CLI's shared per-artifact dispatch path (C901 20, PLR0912 17).

**Requirements**:
- Given this function is the shared path every `fab-test <analyzer>` and `fab-test all` invocation goes through, should enumerate its callers first, per vision.md's Blast Radius table, before splitting it
- Given this file has previously produced regressions caught only by the real CLI (five defects logged in vision.md), should verify through the installed console script for at least one analyzer and for `fab-test all`, not only the unit suite

## `build_parser` in `fab_test.py`

96 statements (PLR0915) from wiring every subcommand's flags in one function.

**Requirements**:
- Given each subcommand's argparse wiring is independent of the others, should split `build_parser` into one helper per subcommand group, called from a slim top-level `build_parser`
- Given `--help` output is a documented contract, should verify it is byte-identical before and after the split

## `generate_embed_token` in `playwright_validation/power_bi_api.py`

9 arguments (PLR0913).

**Requirements**:
- Given several arguments are always passed together (workspace, report, and dataset identity), should group them into one small parameter object
- Given this is Playwright's only path to a working embed token, should verify against its existing contract test after the change

## The single-branch-over-threshold group

`run_analyzer.py`'s `run_analyzer`, `validate_environments_schema.py`'s
`validate`, and `eventhouse_logger.py`'s `validate_payload_schema` (PLR0912 ×3)
are each one branch past the limit rather than a deeper design problem.

**Requirements**:
- Given each is a single function just past the branch limit, should extract its smallest natural sub-check into its own function per file, re-measuring after each rather than batching all three into one change
- Given `eventhouse_logger.py`'s validators are the ones Eventhouse Shipping deliberately kept off the coverage-omit list, should confirm their existing tests still pass unchanged

## `run_pqlint` in `invoke_pqlint.py` — confirm priority first

Over both PLR0912 and PLR0915, but `pql-lint` is currently hidden from
`--help`, `list`, and `doctor` in the advertised CLI surface.

**Requirements**:
- Given the feature's own visibility is unsettled, should confirm pql-lint's status (stays hidden, gets restored, or gets removed) before investing in its internal structure
- Given it is refactored, should follow the same split-by-concern approach as the other wrappers rather than a bespoke pattern

---

## What changed

All ten tasks landed. `run_pqlint`'s status was confirmed with the user before
touching it: `pql-lint` stays hidden from `--help`/`list`/`doctor` but keeps
running when invoked directly, so its internals were still worth cleaning up
rather than left to rot behind the hidden flag.

Report went from 29 findings to 6 — every one addressed except the six in
`deploy.py`/`check_promotion_safety.py`, confirmed still out of scope pending
the dead-code audit in plan.md's "Audit what the pipeline deletion stranded"
task. `COMPLEXITY_CEILING` in `tests/test_complexity_budget.py` now reads 6.

Shape of the fix, repeated across every task: pull the interleaved concerns
(subprocess call, output parsing, envelope writing, argument bundles) into
named single-purpose functions, verify byte-identical behavior (error
messages, `--help` output, envelope schema), then move on. Two module-budget
exemptions moved as a direct, expected consequence: `fab_test.py`'s line count
grew from 2875 to 2956 lines across the `_run_one_artifact` and `build_parser`
splits — more named functions and docstrings, each one far simpler than the
function it replaced.

**1413 passed** throughout, coverage held. `_run_one_artifact`'s split was
verified through the installed console script (`fab-test bpa` in both text
and `--format json` mode against a real downloaded Tabular Editor), and
`build_parser`'s split was verified with a byte-for-byte `--help` diff, both
top-level and per-subcommand, before and after.

---

## Out of scope

- `deploy.py`'s `_artifact_item_type` (PLR0911) and `main` (C901/PLR0912/PLR0915),
  and `check_promotion_safety.py`'s `check_requirements` (PLR0912/PLR0915) — 6 of
  the 29 findings — sit in modules plan.md's "Audit what the pipeline deletion
  stranded" standalone task has already flagged as possibly dead code with no
  production caller. Refactoring code that audit may delete is wasted work;
  resolve that audit first.
- Lowering `max-complexity` below 15 — the Complexity and Coverage epic already
  found it tighter than every surviving function at that setting, so tightening
  it further would add noise rather than signal.
