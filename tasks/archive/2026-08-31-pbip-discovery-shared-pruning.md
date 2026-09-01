# .pbip Discovery Shared Pruning Epic

**Status**: ✅ COMPLETED
**Goal**: `discover_pbip_projects` prunes the same directories `scan` does, instead of walking everything and filtering only nested checkouts.

## Overview

[`_pbip_discovery.py`](../src/fab_test/scripts/_pbip_discovery.py) calls `root.rglob("*.pbip")` and filters the results afterward, so it descends into `.venv`, `node_modules`, `.git`, and every nested checkout before throwing most of that walk away — **9.7s against `C:\Users\jkers\Git` versus 0.08s** for the suffix scan over the same tree. [`_scan.py`](../src/fab_test/scripts/_scan.py)'s own docstring already explains why it chose `os.walk` over `rglob`: *"`rglob` has no way to say 'do not descend'"* — and this sibling module pays that cost anyway. Worse than slow: a `.pbip` file sitting inside `.venv`/`node_modules` (a vendored sample, a cached wheel) is currently returned as a discovered project, which `scan`'s `EXCLUDED_DIR_NAMES` would never allow for a folder-suffix artifact.

Cut from the Empty Discovery Diagnostics epic on 2026-08-22 as off-centre for that epic; revisited here per plan.md's Standalone Tasks.

---

## Route `.pbip` discovery through the shared pruning walker

**Requirements**:
- Given a `.pbip` file inside a directory named in `_scan.EXCLUDED_DIR_NAMES` (`.venv`, `node_modules`, `.git`, etc.), should not be discovered by `discover_pbip_projects` — today it is.
- Given a `.pbip` file inside a separate nested git checkout under root (a worktree, a vendored clone), should still not be discovered, matching existing behavior (`test_discover_skips_projects_inside_a_nested_git_checkout`).
- Given a `.pbip` file in a normal, non-excluded, non-checkout directory at any depth, should still be discovered, matching existing behavior for every other passing test in `test_pbip_discovery.py`.
- Given the walk itself, should reuse `_scan.py`'s `EXCLUDED_DIR_NAMES` and nested-checkout guard rather than a second, divergent implementation — so the two modules cannot answer "what gets pruned" differently again.
