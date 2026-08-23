# Test Module Split Epic

**Status**: 📋 PLANNED
**Goal**: No test module over 900 lines; every module named after the behavior it covers, with a ratchet that stops the next one growing.

## Overview

WHY: `tests/test_fab_test.py` is 4,383 lines and 229 collected tests. Anyone —
human or agent — who needs to change one behavior loads all of it, and every
review of a +100-line diff against it reads as clean because the diff is small
and the file is not. It grew one epic section at a time, with banners named
after epic sections (`(CLI Agent Ergonomics §3)`) rather than behaviors, because
nothing in this repo measured a file: the ruff budgets in `pyproject.toml` are
all function-level. [aidd-module-budgets](../.github/skills/aidd-module-budgets/SKILL.md)
now sets file-level budgets; this epic pays back the file that motivated it.

**This is a move, not a rewrite.** No test body is edited, added, or deleted.
The collected count is 229 before and 229 after. Anything that wants a test
changed is out of scope and gets its own task.

---

## Task 1 — Pin the invariant before touching anything

Record what must not change, so every later task has a check that costs one
command.

```bash
python -m pytest tests/test_fab_test.py --collect-only -q | tail -1   # 229 tests collected
python -m pytest tests/test_fab_test.py -q                            # all pass
```

**Requirements**:
- Given the baseline is captured, should record 229 collected tests and the full
  list of test ids in the epic or a scratch file
- Given the baseline run, should be green before any file is moved
- Given `@pytest.mark.fab_test` appears on 213 tests today, should record that count

## Task 2 — Move shared fixtures to `tests/conftest.py` first

Do this before the split, so each new module can be moved without dragging a
private copy of a helper with it.

Two near-duplicate project builders exist in the file today and are needed by
two different destination modules:

| Helper | Line | Used by |
|--------|------|---------|
| `_pbip_project_dir` | 421 | command builders |
| `_write_pbip_project` | 721 | discovery |

**Requirements**:
- Given the two builders differ only in options, should become one fixture in
  `tests/conftest.py` with the union of the options, or stay two if collapsing
  them changes any assertion
- Given a helper is used by exactly one destination module, should move with
  that module and not enter `conftest.py`
- Given the fixtures have moved, should keep the collected count at 229
- Given the split is done, should have no `tests/helpers.py` — a module every
  test file imports rebuilds the monolith through the import graph

## Task 3 — Split into 13 behavior modules

One commit per module. After each, run the moved module and the shrinking
original; the sum of their collected counts stays 229 the whole way.

| New module | Sections moved (old lines) | ~Lines | Tests |
|-----------|---------------------------|-------:|------:|
| `test_fab_test_help.py` | top-level help, `help` subcommand, unknown analyzer, version, subcommand help (78–414) | 380 | 23 |
| `test_fab_test_command_builders.py` | Desktop binding, rule overlays (415–632) | 260 | 11 |
| `test_fab_test_discovery.py` | dry-run discovery, `.pbip` discovery, metadata analyzer list (633–829, 1177–1273) | 340 | 21 |
| `test_fab_test_summary.py` | formatter helpers, aggregate summary, CI flags/JSON (830–1176, 1274–1434) | 550 | 22 |
| `test_fab_test_exit_codes.py` | error/warning threshold, platform preflight, input validation (1435–1712) | 320 | 19 |
| `test_fab_test_telemetry_context.py` | git context, origin, machine context (1782–2104) | 370 | 18 |
| `test_fab_test_telemetry_payload.py` | gating, payload schema, dry-run, regressions (1713–1781, 2105–2423) | 430 | 17 |
| `test_fab_test_tool_bootstrap.py` | zip archives, checksum verification (2424–2875) | 490 | 11 |
| `test_fab_test_execution.py` | subprocess timeout, parallel runs, per-artifact progress, warning regressions (2876–2946, 2947–3069, 4038–4376) | 580 | 20 |
| `test_fab_test_config.py` | pyproject config, clean-tools, shell completions (3070–3379) | 350 | 22 |
| `test_fab_test_subcommand_names.py` | aliases, canonicalization (3380–3536) | 200 | 9 |
| `test_fab_test_output_contract.py` | narration helper, JSON capture, output-mode propagation, stdout purity (3537–3609, 3760–4037) | 400 | 11 |
| `test_fab_test_empty_discovery.py` | empty discovery diagnostics (3610–3759) | 190 | 9 |

Largest is 580 lines — over the 500 soft budget, under the 900 hard one, and
splitting `test_fab_test_execution.py` further would separate tests that share
`_stub_subprocess_run`. Note that in the commit message.

**Requirements**:
- Given a module is moved, should carry only the imports it uses — the original
  imports from four source modules, and `_pbip_project_dir`-style helpers, do
  not all belong everywhere
- Given a module is moved, should keep every `@pytest.mark.fab_test` intact
- Given a banner names an epic section (`§2`, `§3`, `§5`, `§7`, `§13`), should
  be renamed after the behavior it covers; the epic reference moves to the
  module docstring if it is worth keeping at all
- Given each new module, should open with a docstring saying what surface it
  covers, in the shape of the current file's header
- Given all 13 modules exist, should collect 229 tests in total
- Given the split is complete, should leave no `tests/test_fab_test.py`
- Given the suite runs after the split, should pass with no change under `src/`
- Given `pytest -m fab_test` runs, should collect the same tests it does today

## Task 4 — Ratchet the file sizes so this cannot recur

Follow `tests/test_complexity_budget.py`, which already solved this shape for
complexity: a non-gating report in `build.yml`, and a ratcheted total in the
test suite because a report nobody reads is how 36 findings became 45.

Add `tests/test_module_budget.py`:

**Requirements**:
- Given any file under `src/` or `tests/` exceeds the hard budget (source 800,
  test 900), should fail with the file name and its line count
- Given the largest file today is `src/.../fab_test.py` at 2,848 lines, should
  carry it as a named, dated exemption with the follow-up epic referenced —
  not a raised budget
- Given a file exceeds its soft budget (source 400, test 500), should report it
  without failing, in the `build.yml` step summary alongside the complexity report
- Given a cleanup drops a file well under its exemption, should flag the slack
  so the exemption gets tightened, matching
  `test_the_ceiling_is_not_left_slack_after_a_cleanup`
- Given the ratchet is added, should list every current exemption in one place
  with a one-line reason each

## Task 5 — Document and file the follow-up

**Requirements**:
- Given the split changed where tests live, should update any doc or skill that
  names `tests/test_fab_test.py` by path — run the `document` command so README,
  QUICK-VALIDATION, and the fab-test skill cannot drift apart
- Given `src/fabric_ci_cd_dataops/scripts/fab_test.py` is 2,848 lines against an
  800-line hard budget, should have a follow-up epic filed before this one is
  archived; splitting the tests first is what makes that split reviewable
- Given this epic is complete, should archive to
  `tasks/archive/YYYY-MM-DD-test-module-split.md`

---

## Out of scope

- Changing any test's assertions, name, or coverage
- Splitting the source module (Task 5 files it separately)
- `src/.../fab_test_summary.py` (812) and `fab_test_registry.py` (793), both
  over the soft budget and under the hard one — the ratchet will report them
