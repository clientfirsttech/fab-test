# Exclude Tooling Directories From Discovery Epic

**Status**: ✅ COMPLETED (2026-09-01)
**Goal**: Never let a `*.SemanticModel`/`*.Report`-shaped folder under `.github` or `.claude` be discovered as a real project artifact.

## Overview

`fab-test` discovers artifacts by folder suffix alone, at any depth under the working directory — it has no notion of *why* a folder exists there. `.github` and `.claude` hold agent tooling: skill instructions, worked examples, worktrees, scratch config — not this project's own Fabric artifacts. `EXCLUDED_DIR_NAMES` in `_scan.py` already prunes directories that can never hold something worth testing (`.venv`, `node_modules`, build caches); `.github` and `.claude` belong in that same category, so a future skill's example fixture (or a stray worktree/scratch folder) can never leak into a real `fab-test` run's results.

---

## Exclude `.github` and `.claude` From Artifact Discovery

Added both to `_scan.py`'s `EXCLUDED_DIR_NAMES`. TDD: planted `Sales.SemanticModel`/`Sales2.Report` fixtures under `.github`/`.claude` in a scratch directory and confirmed `find_artifact_dirs` returned both (red) before the change, empty (green) after. The existing `EXCLUDED_DIR_NAMES`-parametrized test in `tests/test_scan.py` picked up both names automatically, no new test shape needed. All four `_scan.py` callers (`_pbip_discovery.py`, `fab_test_admin.py`, `fab_test_execution.py`, `fab_test_registry.py`) share the one exclusion list, so no separate fix was needed per caller. Documented in three places: README's "Where fab-test looks", the authored `.github/skills/fab-test/references/targeting-and-discovery.md`, and its packaged mirror `src/fab_test/skill/references/targeting-and-discovery.md` (kept byte-identical, per `tests/test_skill_resource.py`'s sync guard). Live-verified through the installed `fab-test list --artifact-dir` against real fixtures placed under `.github`/`.claude`: every analyzer reported `Matched 0`. **1674 passed, 3 skipped** (full suite); `ruff check` clean.
