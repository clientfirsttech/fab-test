# Fab-Test Module Split Epic

**Status**: 📋 PLANNED
**Goal**: No file under `src/` over its 800-line hard budget; `fab_test.py` split into behavior-named modules the way its tests already were.

## Overview

WHY: `src/fabric_ci_cd_dataops/scripts/fab_test.py` is 2,867 lines against
the 800-line hard budget in [aidd-module-budgets](../.github/skills/aidd-module-budgets/SKILL.md),
and carries a named, dated exemption in `tests/test_module_budget.py`
instead of a raised budget. It is the CLI's single entry point --
argument parsing, telemetry, artifact execution, admin subcommands
(`doctor`, `init`, `config`, `auth`, `list`, `explain`, `clean-tools`,
completions), and the `local` bundle all live in one module -- so a change
to any one of them risks the others, and Blast Radius already lists five
defects that reached this file from a shared-code change with only one
caller verified. The Test Module Split epic split its tests into 13
behavior-named modules first, specifically so this split would be
reviewable against a test suite a reader can hold in their head; this epic
is the source-side half of that payback.

---

## Pin the invariant before touching anything

Record the current behavior so every later task has a one-command check.

**Requirements**:
- Given the baseline is captured, should record the full `pytest -q`
  count and pass/fail status, and the coverage percentage over
  `src/fabric_ci_cd_dataops`
- Given the CLI is the product, should record `fab-test --help` and one
  `--dry-run` invocation's output as the "must still look like this" baseline
- Given Blast Radius already names this file's shared surfaces (artifact
  discovery, table widths, envelope writing), should list every subcommand
  that calls into each one before any code moves

## Extract the argument parser

`build_parser` (roughly lines 1400-1952 today) is over 550 lines by itself --
larger than most of the modules this epic will produce.

**Requirements**:
- Given `build_parser` and its common-flags helper move to
  `fab_test_parser.py`, should leave `fab_test.py` importing it rather than
  defining it
- Given the parser module moves, should carry `_FabTestParser` and
  `_PrintCompletionAction` with it -- they exist only to serve it
- Given the split is done, should keep `fab-test --help` byte-identical

## Extract telemetry

`_git_context`, `_detect_origin`, `_machine_context`, `_build_telemetry_payload`,
`_validate_telemetry_payload`, `_send_telemetry`, and the telemetry
readiness/decision helpers form one seam already proven by
`test_fab_test_telemetry_context.py` and `test_fab_test_telemetry_payload.py`.

**Requirements**:
- Given telemetry moves to `fab_test_telemetry.py`, should keep the same
  public names `fab_test.py` re-exports or imports, so no test import changes
- Given the split is done, should keep `--telemetry --dry-run`'s preview
  output unchanged

## Extract per-artifact execution

`_run_one_artifact`, `_run_analyzer`, `_preflight`, `_discover_for`,
`_report_no_artifacts`, `_report_dry_run`, and `_RunContext` are the
subprocess-running core `test_fab_test_execution.py` and
`test_fab_test_exit_codes.py` already exercise as one seam.

**Requirements**:
- Given execution moves to `fab_test_execution.py`, should keep `--jobs`
  parallelism, timeout resolution, and per-artifact progress narration
  behaviorally unchanged
- Given `_run_analyzer` is a Blast Radius entry point (artifact discovery,
  envelope writing), should re-verify every caller enumerated in vision.md
  after the move, not only the one this epic touches first

## Extract admin subcommands

`_doctor`, `_doctor_local`, `_init`, `_config_show`, `_config_validate`,
`_list_analyzers`, `_explain_analyzer`, `_auth`/`_auth_status`/`_auth_login`,
and `_clean_tools` are reporting/config commands, not analyzer runs.

**Requirements**:
- Given admin subcommands move to `fab_test_admin.py`, should keep each
  dispatched the same way from `main()`
- Given `doctor` and `list` both call artifact discovery, should verify both
  after the move per the Blast Radius table in vision.md, not just one

## Extract the `local` bundle

`_local_readiness`, `_build_local_plan`, `_narrate_local_plan`, and
`_run_local` are the no-cloud analyzer bundle from Local Desktop First Run,
already a distinct surface from the cloud-facing subcommands.

**Requirements**:
- Given the local bundle moves to `fab_test_local.py`, should keep
  `fab-test local --dry-run`'s plan output unchanged
- Given the split is done, should keep `doctor --local`'s readiness report
  unchanged

## Ratchet the result

**Requirements**:
- Given every extraction is done, should remove `fab_test.py`'s exemption
  from `tests/test_module_budget.py` once it is back under the 800-line
  hard budget, or lower the exemption's recorded ceiling if it still isn't
- Given `fab_test.py` still exists as the CLI entry point, should keep
  `main()`, `_dispatch_run`, and `_dispatch_admin_command` there as the
  thin dispatcher tying the extracted modules together
- Given the whole suite ran before this epic started, should collect and
  pass the same count afterward, with coverage over
  `src/fabric_ci_cd_dataops` no lower than the recorded baseline

---

## Out of scope

- Changing any CLI-visible behavior, flag, exit code, or output shape
- Renaming subcommands or flags
- Splitting `fab_test_summary.py` (812 lines) or `fab_test_registry.py`
  (811 lines) -- both carry their own exemption in
  `tests/test_module_budget.py` and are a few lines over hard, not
  candidates for this epic
