# PBIR Screenshot Correlation Epic

**Status**: ✅ COMPLETED (2026-09-08)
**Goal**: Make PBIR Inspector's per-object screenshots actually render in `TestRun.html` on every run, not just the first — a stale `PBIInspectorPNG` folder from a prior run silently breaks the Report Completeness epic's inlining fix on every run after that.

## Overview

The [PBIR Report Completeness epic](2026-08-23-pbir-report-completeness.md) added `fix_screenshot_images` to inline `PBIInspectorPNG\<Id>.png` references as base64 data URIs, keyed by `this.Id`. It runs on every report (`window.__pbirScreenshots` and the inlined favicon are present in every checked-in `TestRun.html` under `fab-test-results/pbir/`), but the images were still broken.

**Diagnosed live**: `this.Id` (the finding/rule-result's own GUID) is regenerated fresh every run, but FabInspCLI does not regenerate `PBIInspectorPNG` against an already-populated output directory.
- Run 1 against an empty `native.json` folder: finding `Id`s and `PBIInspectorPNG/*.png` filenames matched exactly (22/22).
- Run 2, same artifact, output folder left in place: fresh finding `Id`s, but the same stale 22 PNGs from run 1 — overlap dropped to 0/22, reproducing the reported broken images exactly.
- Deleting only the `PBIInspectorPNG` folder before invoking the inspector binary (leaving old `TestRun_*.json` exports alone) was confirmed sufficient: FabInspCLI regenerates it fresh and every `Id` matches again.

`fix_screenshot_images`'s correlation key (`this.Id`) was never wrong. The fix is narrower than either originally-planned task: no correlation-key change, no per-file staleness filtering — just clear the one folder that goes stale before FabInspCLI runs.

---

## Task: Clear stale PBIInspectorPNG before each PBIR Inspector invocation

New `_clear_stale_screenshot_folder(native_out)` in `invoke_pbir_inspector.py`, called from `run_inspector` right after `native_out`'s directories are created and only when `emit_html` is true (the only case `PBIInspectorPNG` matters). Never raises — a folder that can't be removed is a lost convenience, not a reason to fail the run before the inspector has even started, matching `fix_favicon_link`/`fix_screenshot_images`'s existing contract.

**Requirements**:
- Given a `native_out` directory whose `PBIInspectorPNG` folder already exists from a prior run, should the wrapper remove it before invoking the inspector binary, so FabInspCLI always writes a fresh set that matches the run's own finding `Id`s — ✅ `_clear_stale_screenshot_folder`, called unconditionally on removal (guarded by `emit_html` at the call site)
- Given a first-ever run against a fresh `native_out` with no `PBIInspectorPNG` folder yet, should behavior be unchanged from today — ✅ `shutil.rmtree` under `contextlib.suppress(OSError)` on a non-existent path is a no-op
- Given the inspector binary fails to run at all (timeout, missing binary, unexpected exception), should the stale-folder removal not be the cause of a new failure mode — ✅ clearing happens before `_run_inspector_process` is called, ahead of any subprocess outcome

TDD: 4 new tests in `tests/test_invoke_pbir_inspector.py` (`TestClearStaleScreenshotFolder`) written first and confirmed red (`AttributeError: ... has no attribute '_clear_stale_screenshot_folder'`), green after the two-line implementation plus its call site. `pytest -m pbir`: 64 passed, 2 skipped. `ruff check src/`: clean. Full suite: **1731 passed, 3 skipped, coverage 89%** (floor 80%, held).

Live-verified through the real installed CLI, the exact scenario that broke: `fab-test pbir ThinReport --report` run twice in a row now holds 22/22 screenshot correlation on the second run, where it previously dropped to 0/22.

1/1 task.
