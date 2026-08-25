# Complexity Cleanup Coverage Gaps Epic

**Status**: 📋 PLANNED
**Goal**: Add direct tests for the validation and error-handling branches the Complexity Cleanup epic isolated into named functions but did not itself add tests for.

## Overview

WHY: Complexity Cleanup was a behavior-preserving refactor — split first, verify
byte-identical behavior, never add new test cases for logic that already existed.
That was the right call for a 10-task epic already carrying its own risk, but it
means every branch that was untested before the split is *still* untested now,
just isolated into a smaller, more obviously-named function where the gap reads
clearer: `_validate_env_block`'s deployment_window check, `_missing_table_fields`'
per-table branches, `_run_pqlint_process`'s three exception handlers. Coverage
held at 85% project-wide throughout the epic (floor is 80%), so nothing here was
ever a gate failure — these are real, pre-existing gaps the refactor exposed
rather than gaps it introduced, and they're worth closing while the functions
are fresh and named for exactly what to test.

---

## `run_pqlint`'s subprocess failure paths

`invoke_pqlint.py`'s `_run_pqlint_process` has the same three-exception shape
(`TimeoutExpired`, `FileNotFoundError`, generic) that `invoke_pbir_inspector.py`,
`invoke_pql_test.py`, and `invoke_tabular_editor_bpa.py` each already have a
`test_run_timeout`/`test_run_missing_binary` pair for — `invoke_pqlint.py` has
none of the three.

**Requirements**:
- Given pqlint's subprocess call times out, should write a `"timeout"` envelope and exit 1, mirroring `test_run_timeout` in `tests/test_invoke_pbir_inspector.py`
- Given the pqlint executable is not found, should write an `"error"` envelope and exit 1, mirroring `test_run_missing_binary`
- Given the subprocess raises an unexpected exception, should write an `"error"` envelope naming the exception rather than letting it escape

## `validate_environments_schema.py`'s structural checks

`_validate_env_block` (added by Complexity Cleanup as an extraction, logic
unchanged) has four branches with no direct test: `allowed_branches` present
but not a list, `allowed_branches` present but empty, a boolean field present
but not a bool, and `deployment_window` present but not a mapping.

**Requirements**:
- Given an environment's `allowed_branches` is a string instead of a list, should report "Must be a list"
- Given an environment's `allowed_branches` is an empty list, should report "Must not be empty"
- Given `requires_validation` (or either sibling boolean key) is a string instead of a boolean, should report "Must be a boolean"
- Given `deployment_window` is present but not a mapping, should report "Must be a mapping"; given it is a mapping missing `enabled`, should report the missing key

## `eventhouse_logger.py`'s table-specific field checks

`validate_payload_schema` is tested for `fabric_static_analysis` and
`fabric_dynamic_analysis` only (`tests/test_eventhouse_logger.py`);
`fabric_deployments` and `fabric_testbed_runs` have no test, and every existing
call passes `terse=True`, so the human-readable `Error: ...` print path (verbatim
in `_run_pqlint_process`'s siblings too) has never run under test.

**Requirements**:
- Given a `fabric_deployments` payload missing `environment`, should fail validation naming that field
- Given a `fabric_testbed_runs` payload missing `results`, should fail validation naming that field
- Given `terse=False`, should print the same message `terse_print` recorded, not just return `False`

---

## Out of scope

- Splitting `_analyzer_tool_bootstrap.py` (469 lines) or `invoke_pbir_inspector.py`
  (723 lines) to bring them back under the 400-line module-budget soft budget —
  both grew past it as a direct, expected consequence of Complexity Cleanup's
  splits (more named functions, each simpler). Non-gating today (only the
  800-line hard budget fails a test), and no epic tracks a source split for
  either module the way `tasks/fab-test-module-split-epic.md` already does for
  `fab_test.py`. Worth filing as its own epic if either keeps growing, not as a
  rider on this one.
- Any behavior change to the validators or wrappers above — every finding here
  is a missing test for existing, unchanged logic, not a defect in it.
