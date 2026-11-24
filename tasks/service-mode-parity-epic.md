# Service Mode Parity Epic

**Status**: 📋 PLANNED 2026-11-23, decisions awaiting the user's review.
**Goal**: a run against the workspace (`--workspace`, `WS.Workspace/NAME`) applies every check the same run applies to the local folder, or refuses saying which check it can't apply. The skills that plan and review commands require this, so the next gap is caught before it ships.

**Decisions** (proposed 2026-11-23):

1. **A silently skipped check is a defect, not a limitation.** When a run mode can't apply a check (a contract, a rules overlay, a paired suite), it says so in the output and the envelope, and fails under CI rather than passing.
2. **Pair a deployed item with its authored file the way a local item pairs**: by logicalId when the export carries `.platform`, else by display name, the way `data-agent` already pairs a deployed agent (`test_service_target_pairs_local_item_by_display_name`).
3. **The skills own the rule; a test enforces it.** `aidd-analyzer-contract` and `aidd-command-grammar` gain the rule and a plan/review step; a parity test (local vs `--workspace` on the same items) is what proves it.

## Overview

WHY: the first live run of `pbir` locally and with `--workspace fab-test-working-area` (Live Integration Per Command epic, 2026-11-23) found `SampleModel-DefaultState` failing its slicer contract locally and passing against the service. `pbir --workspace` never applies a slicer contract: a contract pairs with a report by its `.platform` logicalId, and `_service_export.py` doesn't write one, so nothing pairs and nothing says so. The docstring in `_slicer_contract_run.py` records this as intended (`--contract` is "meant for a single report target"). A person who wrote a contract and runs against the workspace gets a green result for a report that breaks it.

The skills that plan and review commands didn't catch it. `aidd-analyzer-contract`'s Proof section verifies a run "alone, via `all`, and via `local`", never via `--workspace`, and asks for no live test. `aidd-command-grammar` says how an authored file pairs with a local item, not with a deployed one. `aidd-review` doesn't ask whether every mode applies the same checks.

Known instance of the same class to check while here: `rdl`'s settings and rule overlays, `pql_test` contracts (ODCS), and `data-agent` suites under `--workspace`.

---

## What getDefinition Returns

**Requirements**:
- Given a deployed report, should record whether Fabric's `getDefinition` returns a `.platform` part (with `logicalId`) for Report, SemanticModel, PaginatedReport and DataAgent. This decides between decision 2's two pairings.

## Contracts Pair Under --workspace

**Requirements**:
- Given `pbir --workspace` and a contract in `fab-tests/pbir/` for a deployed report, should apply the contract and report its findings exactly as the local run does.
- Given a deployed report no contract pairs with, should run as today.
- Given a contract that names a report the workspace doesn't have, should say so once (the local run's behaviour).
- Given the live analyzer test, should remove `pbir: SampleModel-DefaultState` from `_KNOWN_GAPS` in `tests/test_analyzers_live.py`; the agreement test fails until it does.

## No Silent Skips

**Requirements**:
- Given any analyzer run where an authored file or overlay exists but can't apply in this mode, should name it in the output and the envelope, and exit non-zero under `CI`.

## aidd-analyzer-contract: Mode Parity

**Requirements**:
- Given a plan for an analyzer that supports `--workspace`, should list, for every check and authored file, how it applies in each mode (local, `local/NAME`, `WS.Workspace/NAME`, `--workspace`).
- Given its Proof section, should require the run through the real CLI with `--workspace`, not only alone, `all` and `local`, and a live integration test (`tests/test_analyzers_live.py` or a `*_live.py` file run by a `fabric-demo` workflow) comparing local and service findings.
- Given `/analyzer-contract review`, should flag a check, overlay or pairing that only one mode applies.

## aidd-command-grammar: Pairing A Deployed Target

**Requirements**:
- Given its Files section, should say how an authored file pairs with a deployed item (decision 2), not only with a local folder.
- Given `/command-grammar review` of a run that reads authored files, should ask what happens to each under `--workspace`.

## aidd-review: Mode Question

**Requirements**:
- Given a diff touching an analyzer or its authored files, should ask whether each run mode applies the change, and whether a live test shows it.

## Quality gates

Whole-repo `ruff check .`, the complexity and module-budget ratchets, the full suite with `--cov-fail-under=80` in CI's two halves, the environment-dependent tests with `GITHUB_ACTIONS=true CI=true`, and `tests/test_analyzers_live.py` with `FAB_TEST_LIVE_WORKSPACE` set.
