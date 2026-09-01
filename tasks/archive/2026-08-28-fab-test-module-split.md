# Fab-Test Module Split Epic

**Status**: ✅ COMPLETED — 6 of 6 tasks done
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

## Pin the invariant before touching anything  ✅

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

Baseline (2026-08-28): `fab_test.py` at 2,956 lines; `pytest -q` = **1439
passed, 3 skipped**; full-suite coverage over `src/fabric_ci_cd_dataops` =
**85%** (floor 80%). `fab-test --help` and `fab-test bpa --dry-run` captured
verbatim as the diff target for every later task. Blast Radius surfaces this
file owns (artifact discovery, table widths, envelope writing) are called
from `_run_analyzer`, `list`, `explain`, `doctor`, `doctor --local`, `all`,
and `local` -- each re-verified after every extraction below rather than only
the subcommand each task's own tests touch first.

## Extract the argument parser  ✅

`build_parser` (roughly lines 1400-1952 today) is over 550 lines by itself --
larger than most of the modules this epic will produce.

**Requirements**:
- Given `build_parser` and its common-flags helper move to
  `fab_test_parser.py`, should leave `fab_test.py` importing it rather than
  defining it
- Given the parser module moves, should carry `_FabTestParser` and
  `_PrintCompletionAction` with it -- they exist only to serve it
- Given the split is done, should keep `fab-test --help` byte-identical

Done: `build_parser`, every `_add_*_subparser` builder, `_FabTestParser`,
`_PrintCompletionAction`, the completion-script generator, `_guid_type`, and
the canonical/alias name helpers all moved to the new `fab_test_parser.py`
(911 lines). `fab_test.py` now imports `build_parser`, `_canonical_name`,
`_aliases_for`, and `_SUBCOMMAND_ALIASES` rather than defining them -- the
only names it still references. A second new module, `_fab_test_context.py`,
holds the path/config constants (`REPO_ROOT`, `ARTIFACT_ROOT`, `RESULTS_ROOT`,
`_PYPROJECT_CONFIG`, `_DEFAULT_SUBPROCESS_TIMEOUT`) that the parser,
execution, and admin sections all read, avoiding a circular import back into
`fab_test.py` -- not one of the five modules this epic named, but a shared
seam every later extraction needs too. `fab-test --help` and
`fab-test bpa --dry-run` verified byte-identical against the baseline.
`fab_test.py`: 2,956 → 2,054 lines. Fixed three whitebox tests that
monkeypatched `fab_test._PYPROJECT_CONFIG` directly (an internal, not a
public re-export) to instead patch `fab_test_parser._PYPROJECT_CONFIG`, the
binding `_add_common_flags` actually closes over. `tests/test_module_budget.py`
updated: `fab_test.py`'s exemption ceiling tightened to 2,054; a new dated
exemption added for `fab_test_parser.py` at 911 (born over hard by the move
itself -- one function per subcommand, not a candidate for a further split
per its own reasoning). 1439 passed, 3 skipped, coverage 85% (held).

## Extract telemetry  ✅

`_git_context`, `_detect_origin`, `_machine_context`, `_build_telemetry_payload`,
`_validate_telemetry_payload`, `_send_telemetry`, and the telemetry
readiness/decision helpers form one seam already proven by
`test_fab_test_telemetry_context.py` and `test_fab_test_telemetry_payload.py`.

**Requirements**:
- Given telemetry moves to `fab_test_telemetry.py`, should keep the same
  public names `fab_test.py` re-exports or imports, so no test import changes
- Given the split is done, should keep `--telemetry --dry-run`'s preview
  output unchanged

Done: `_telemetry_table`, `_telemetry_destination`, `_telemetry_readiness`,
`_open_telemetry`, `_close_telemetry`, `_telemetry_decision`,
`_telemetry_enabled`, the `_git_context`/`_git_command_output` re-exports,
`_detect_origin`, `_current_os_platform`, `_machine_context`,
`_relativize_paths`, `_relative_to_root`, `_looks_absolute`,
`_build_telemetry_payload`, `_validate_telemetry_payload`, and
`_send_telemetry` all moved to the new `fab_test_telemetry.py` (381 lines,
under the 400-line soft budget -- no exemption needed). `fab_test.py` keeps
importing every name a test still reaches directly (`_build_telemetry_payload`,
`_git_context`, `_machine_context`, `_relativize_paths`, `_telemetry_enabled`,
`_validate_telemetry_payload`, plus the ones its own remaining code calls),
so no test's *import* changed. What the requirement's "no test import
changes" line could not promise, and did need fixing: a handful of tests
that **monkeypatched** an internal (`fab_test_module._git_context`,
`._current_os_platform`, `._telemetry_enabled`, `._build_telemetry_payload`,
`.REPO_ROOT`, `.publish_analyzer_telemetry`) rather than importing it --
patching a re-exported alias in `fab_test.py` cannot reach a closure that
now lives in `fab_test_telemetry.py` and calls its own module-level name, so
those patches were retargeted to `fab_test_telemetry.<name>`. Confirmed this
was genuinely necessary, not guessed: every `fab_test_module.subprocess`
patch in the same files needed no change, because `import subprocess` shares
one module object across every importer, unlike a `from x import y` binding.
`fab-test --help` and `bpa --dry-run` reconfirmed unchanged (the only diff
is the version-bump line, unrelated to this task). `fab_test.py`: 2,054 →
1,712 lines; exemption ceiling tightened accordingly. 78 telemetry-file
tests passed; full `fab_test`-marker suite 924 passed.

## Extract per-artifact execution  ✅

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

Done: `_resolve_timeout`, `_apply_environment_default`, `_artifact_exit_code`,
`_RunContext`, `_announce_artifact_run`, `_reemit_lines`,
`_run_artifact_process`, `_emit_process_output`, `_load_artifact_envelope`,
`_finalize_artifact_run`, `_run_one_artifact`, `_manifest_target`,
`_resolve_workspace_target`, `_target_of`, `_discover_for`,
`_report_no_artifacts`, `_report_dry_run`, `_preflight`, `_analyzer_sub_env`,
and `_run_analyzer` all moved to the new `fab_test_execution.py` (685 lines --
over the 400-line soft budget, under the 800 hard one, no exemption needed).
Also moved along with them, since each is used only inside this seam:
`_is_ci`, `_clean_annotation`, `_stderr_detail`, `_verbosity_env`, and the
`_resolve_report` alias. `fab_test.py` re-exports every name a test imports
directly, plus the ones its own remaining code (admin, local bundle,
dispatch) still calls -- `_target_of`, `_manifest_target`,
`_resolve_workspace_target`, and `_run_analyzer` are genuinely called from
both sides, so both modules import them independently from their real
source (`fab_test_registry`/`._target`) rather than one importing the other.

The same monkeypatch pitfall from the telemetry task recurred at larger
scale here, because `_run_analyzer` is the one function nearly every
execution test drives end-to-end: 30+ patches across
`test_fab_test_execution.py`, `test_fab_test_output_contract.py`,
`test_run_manifest.py`, and `test_report_column.py` targeted
`fab_test_module.{_is_ci, _send_telemetry, emit_workflow_annotations,
emit_pr_review_comments, _preflight_error, _print_summary, _preflight,
_run_one_artifact}` -- every one a name whose *call site* moved into
`fab_test_execution.py`, so the patch needed to move with it. Each was
checked individually against where the call actually happens before
retargeting, rather than moved on the assumption that "it's an execution
name" -- a few execution-adjacent patches (`_run_analyzer` itself in
`test_local_command.py`, `_resolve_workspace_target` in
`test_summary_rows.py`, `_apply_environment_default` in
`test_fab_test_config.py`) call sites are still in `fab_test.py`'s own
code (the local bundle and dispatch chain, not yet extracted) and correctly
needed no change. `fab_test.py`: 1,712 → 1,087 lines; exemption ceiling
tightened accordingly. 187 tests passed across every touched file; full
`fab_test`-marker suite 923 passed (1 pre-existing exemption-ceiling test
updated as part of this task, not a regression); `fab-test --help` and
`bpa --dry-run` reconfirmed unchanged.

## Extract the `local` bundle  ✅

`_local_readiness`, `_build_local_plan`, `_narrate_local_plan`, and
`_run_local` are the no-cloud analyzer bundle from Local Desktop First Run,
already a distinct surface from the cloud-facing subcommands.

**Requirements**:
- Given the local bundle moves to `fab_test_local.py`, should keep
  `fab-test local --dry-run`'s plan output unchanged
- Given the split is done, should keep `doctor --local`'s readiness report
  unchanged

Done: `_LOCAL_ANALYZERS`, `_pql_lint_path`, `_local_readiness`,
`_project_matches_glob`, `_build_local_plan`, `_narrate_local_plan`, and
`_run_local` all moved to the new `fab_test_local.py` (188 lines, well under
the 400-line soft budget). Done *before* admin subcommands, reordering the
epic's own stated sequence: `_doctor_local` (admin) calls `_local_readiness`
and `_LOCAL_ANALYZERS` (local bundle), and extracting admin first would have
made `fab_test_admin.py` import back from `fab_test.py` while `fab_test.py`
also imports `_dispatch_admin_command`'s handlers from `fab_test_admin.py` --
a circular import. Moving the local bundle first let admin import
`_local_readiness`/`_LOCAL_ANALYZERS` from `.fab_test_local` cleanly, one
direction only. `fab_test.py`: 1,087 → 926 lines, verified via
`fab-test local --dry-run` and `doctor --local` byte-unchanged. Fixed
monkeypatches in
`test_local_command.py` and `test_run_manifest.py` that targeted
`fab_test_module.{_local_readiness, _run_analyzer}` -- both callers moved to
`fab_test_local.py`, so both needed retargeting; `test_doctor.py`'s
`_local_readiness` patch (for `_doctor_local`, not yet moved at this point)
correctly needed no change yet.

## Extract admin subcommands  ✅

`_doctor`, `_doctor_local`, `_init`, `_config_show`, `_config_validate`,
`_list_analyzers`, `_explain_analyzer`, `_auth`/`_auth_status`/`_auth_login`,
and `_clean_tools` are reporting/config commands, not analyzer runs.

**Requirements**:
- Given admin subcommands move to `fab_test_admin.py`, should keep each
  dispatched the same way from `main()`
- Given `doctor` and `list` both call artifact discovery, should verify both
  after the move per the Blast Radius table in vision.md, not just one

Done: `_print_help`, `_all_analyzers`, `_clean_tools`, `_is_secret_key`,
`_config_validate`, `_ruleset_rows`, `_config_show`, `_init` (with its three
template strings), `_doctor_local`, `_doctor`, `_list_analyzers`,
`_explain_analyzer`, `_verify_ambient_credential`,
`_check_workspace_reachable`, `_auth_status`, `_auth_login`, and `_auth` all
moved to the new `fab_test_admin.py` (648 lines -- over the 400 soft budget,
under the 800 hard one, no exemption needed). `_ADMIN_COMMAND_HANDLERS` and
`_dispatch_admin_command` stayed in `fab_test.py` exactly as the epic's
Ratchet task specifies, now importing the seven handlers from
`fab_test_admin.py`. `fab_test.py`: 926 → **320 lines** -- the module this
whole epic was about is now an order of magnitude under its own 800-line
hard budget.

Two blast-radius fixes discovered only by running the real CLI (`doctor`,
`list`, `config --show`, `explain`, `auth status`) and by the test suite,
not by inspection: `fab_test.py` had silently stopped importing `subprocess`
and `shutil` once admin was the last consumer of both, which broke every
test that patched `fab_test_module.subprocess`/`.shutil` across
`test_auth.py`, `test_list_explain.py`, and (from the execution task)
`test_fab_test_execution.py`, `test_fab_test_exit_codes.py`,
`test_fab_test_output_contract.py`, `test_fab_test_telemetry_context.py`,
`test_fab_test_telemetry_payload.py`, `test_run_manifest.py`,
`test_local_command.py` -- the "shared module object" reasoning from the
telemetry task only holds when *some* still-live import keeps the attribute
on the module; once fab_test.py's own import disappeared, `fab_test_module.
subprocess` raised `AttributeError` outright, and each patch needed
retargeting to whichever module (`fab_test_execution`, `fab_test_admin`, or
`_git_context` for the git-based tests) actually calls it now. Also missed
by the first import rewrite: `_load_fab_test_all_analyzers` and
`RESULTS_ROOT`, imported directly by `test_fab_test_discovery.py`,
`test_scan.py`, and `test_target_discovery.py` but not re-exported --
restored with `# noqa: F401`.

## Ratchet the result  ✅

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

Done: `fab_test.py`'s `EXEMPTIONS` entry removed entirely from
`tests/test_module_budget.py` (320 lines, comfortably within the 800-line
hard budget -- `test_every_exemption_still_needs_one` flagged it as dead
weight the moment the file dropped under budget). `main()`, `_dispatch_run`,
and `_dispatch_admin_command` all still live in `fab_test.py`. Final numbers
against the 2026-08-28 baseline (2,956 lines, 1439 passed/3 skipped, 85%
coverage): **fab_test.py is 320 lines** (a 89% reduction), five new modules
(`_fab_test_context.py` 37, `fab_test_parser.py` 911, `fab_test_telemetry.py`
381, `fab_test_execution.py` 685, `fab_test_local.py` 188,
`fab_test_admin.py` 648), full suite **1439 passed, 3 skipped, coverage 86%**
(up one point, floor 80%), `fab-test --help` and `bpa --dry-run` verified
byte-identical throughout (save the version-bump line, unrelated to this
epic) via the installed console script, not just the test suite.

---

## Out of scope

- Changing any CLI-visible behavior, flag, exit code, or output shape
- Renaming subcommands or flags
- Splitting `fab_test_summary.py` (812 lines) or `fab_test_registry.py`
  (811 lines) -- both carry their own exemption in
  `tests/test_module_budget.py` and are a few lines over hard, not
  candidates for this epic
