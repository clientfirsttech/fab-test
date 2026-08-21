# Complexity and Coverage Epic

**Status**: 🚧 IN-PROGRESS (3/8)
**Goal**: Make the coverage floor real, then pay down the seven functions that have grown past every threshold.

## Overview

[vision.md](../vision.md) declares an 80% line-coverage floor and then admits, in its own words, that it "is currently guidance rather than enforcement". Measured today the figure is **75%**, so the constraint has been quietly unmet rather than merely unwired. At the same time the non-gating complexity report has grown from 36 findings to **45**, and the growth is concentrated in the code most recently changed: `fab_test.py` is now 2,405 lines and its `main` carries 10 return statements.

Coverage comes first, deliberately. Refactoring 2,400 lines without measurement is how a branch quietly disappears, and the point of splitting a 122-statement function is to make its parts individually testable — which is only observable if coverage is being watched. Doing it the other way round means refactoring blind and then measuring what survived.

**The wrappers all failed the same way.** `run_bpa` (122 statements), `run_pql_test` (106), and `run_inspector` (103) each grew the same five phases into one body: validate inputs, resolve the tool, narrate at the current verbosity, execute under a `Timer`, then parse output and write the envelope. That repetition is the opportunity — the split is identical every time, so it is a pattern to extract rather than three separate rewrites.

**Scope decision (2026-08-21, user)**: this epic covers the three functions grown during the Human-Readable Reports and Artifact Targeting work — `main`, `_run_analyzer`, `_print_all_summary` — plus the two worst wrappers, `run_bpa` (30) and `run_pql_test` (23). `run_inspector`, `validate_environments_yaml`, and the long tail are deliberately left: they are stable, rarely touched, and exercised only with real tools installed, so the risk-to-benefit is worse.

---

## 1. Wire Coverage Measurement ✅

**Done (2026-08-21)**: `pytest-cov` in the `dev` extras, `[tool.coverage.run]` scoped to `src/fabric_ci_cd_dataops`, and `[tool.coverage.report]` with `show_missing`. `pytest.ini` deliberately untouched, guarded by a test.

Turn the floor from an aspiration into a number that appears on every run.

`pytest-cov` is already installed but absent from the `dev` extras and from any config, so nothing measures anything today.

**Requirements**:
- Given `pyproject.toml`, then `pytest-cov` is in the `dev` optional-dependency group so a fresh clone can measure without guessing.
- Given `[tool.coverage.run]`, then it is scoped to `src/fabric_ci_cd_dataops` with tests excluded from the denominator, per vision.md.
- Given `pytest.ini`, then it gains **no** coverage flag — a `pytest -m bpa` run legitimately covers a fraction of `src/`, and failing it would defeat the token-saving constraint that makes granular runs worth having.
- Given a granular marker run, then coverage is neither measured nor enforced.
- Given the full suite run locally, then the coverage figure is reported without gating.

**Files**: `pyproject.toml`
**Tests**: `pytest -m fab_test` then the full suite with `--cov`

---

## 2. Decide the Coverage Denominator ✅

**Done (2026-08-21)**: four modules omitted by explicit path — `eventhouse_logger.py`, both `smoke_test_*` harnesses, and `validate_fabric_service_client.py`. Each needs a live service to execute, so a unit test could only assert its argument parser accepts flags, inflating the figure rather than improving it. **Measured 75% → 81.45%**, clearing the floor without lowering it.

`tests/test_coverage_config.py` guards the two ways this rots: an omit entry that stops matching any file (silently protecting nothing) and an entry broad enough to swallow library code added later. Every entry must be a single `.py` path, must still exist, must be explained inline, and no core CLI module may appear.

75% against 80% is a real gap, and how it closes is a decision rather than a detail.

The shortfall is not in library code — the modules written most recently measure 93–100%. It is concentrated in scripts that need live services to exercise at all: `smoke_test_orchestrator.py` (30%), `smoke_test_pql_test.py` (26%), `eventhouse_logger.py` (11%), `validate_fabric_service_client.py` (0%). Excluding those four puts the total at roughly **81%**.

**Requirements**:
- Given the decision, then the reasoning is recorded here and in `vision.md`, naming what is excluded and why.
- Given an excluded module, then the exclusion is by explicit path in `[tool.coverage.run] omit`, never a blanket pattern that could silently swallow library code added later.
- Given the floor, then it is not lowered below 80% — vision.md calls it a ratchet, and moving it down to meet the current number would make the constraint meaningless.
- Given an excluded module, then a comment states what would have to be true to bring it back in.

**Files**: `pyproject.toml`, `vision.md`
**Tests**: full suite with `--cov`, confirming the reported total clears 80%

---

## 3. Enforce the Floor in CI ✅

**Done (2026-08-21)**: `pytest -q --cov --cov-fail-under=80` in `build.yml`, with a comment recording why the threshold cannot move to `pytest.ini`. Verified with the exact CI invocation locally: exit 0 at 81.45%.

**Requirements**:
- Given the CI workflow, then it runs the full suite with `--cov-fail-under=80`.
- Given a change that drops coverage below the floor, then CI fails and names the figure.
- Given the invocation, then the threshold lives in the CI command and not in `pytest.ini`.
- Given a local run, then nothing new fails — enforcement is CI-side only.

**Files**: `.github/workflows/build.yml`
**Tests**: full suite with `--cov-fail-under=80` locally, to confirm it passes before CI sees it

---

## 4. Split `main` in `fab_test.py`

Complexity 17, **10 return statements**, 19 branches, 53 statements. Each early return is a distinct failure mode — config error, target parse error, workspace conflict, unsupported scope, workspace resolution — added one at a time until the function became a list of guards with a dispatch buried at the end.

**Requirements**:
- Given `main`, then argument resolution and validation are extracted so it reads as: resolve, validate, dispatch.
- Given every current exit code and message, then all are unchanged — this is a refactor, and the CLI contract is covered by existing tests.
- Given the result, then `main` is under the complexity threshold and has no more than 6 returns.
- Given the extracted validation, then it is unit-testable without invoking the CLI.

**Files**: `fab_test.py`
**Tests**: `pytest -m fab_test` then the full suite

---

## 5. Split `_run_analyzer` and `_print_all_summary`

`_run_analyzer`: complexity 22, 23 branches, 71 statements — discovery, dry-run reporting, two preflights, execution, and summary in one body. `_print_all_summary`: complexity 18, 69 statements — row building, table rendering, the path listing, the index, and colour.

**Requirements**:
- Given `_run_analyzer`, then discovery, preflight, and execution are separable and the dry-run path does not thread through the execution path.
- Given `_print_all_summary`, then row building is separated from rendering, so the rows can be asserted without capturing stdout.
- Given both, then they fall under the complexity threshold.
- Given the terminal output, then it is byte-identical before and after — verified against a real `fab-test all` run, not only unit tests.

**Files**: `fab_test.py`, `fab_test_summary.py`
**Tests**: `pytest -m fab_test`, then a real `fab-test all --report` compared against saved output

---

## 6. Extract the Wrapper Pattern from `run_bpa` and `run_pql_test`

The two worst: 30 and 23 complexity, 122 and 106 statements. Both follow the same five phases, so the extraction is one shared shape applied twice rather than two rewrites.

**Requirements**:
- Given the five phases — validate inputs, resolve the tool, narrate, execute under `Timer`, parse and write the envelope — then the shared scaffolding lives in one place and each wrapper supplies only what differs.
- Given both functions, then each falls under the complexity threshold and under 50 statements.
- Given the envelope each produces, then it is unchanged key-for-key, including the optional keys and `test_summary`.
- Given an analyzer failure path — missing tool, non-zero exit, unparseable output, timeout — then each still produces the same status and message as before.
- Given `run_inspector`, then it is left alone; the pattern is proven on two before a third adopts it.

**Files**: `invoke_tabular_editor_bpa.py`, `invoke_pql_test.py`, possibly a shared helper
**Tests**: `pytest -m bpa` then `pytest -m pql_test`, then a real run of each against the sample model

---

## 7. Lower the Complexity Budget

A threshold nothing can exceed is worth more than a report nobody reads.

**Requirements**:
- Given the finished refactor, then `max-complexity` is lowered to the highest value the surviving code actually needs, so the next regression is visible.
- Given the complexity report in `build.yml`, then it states the current finding count so a rise is noticeable.
- Given a deliberate exception, then it carries a reason in the commit message, per the existing convention.

**Files**: `pyproject.toml`, `.github/workflows/build.yml`
**Tests**: `ruff check src --select C901,PLR0911,PLR0912,PLR0913,PLR0915`

---

## 8. Document for All Three Callers

**Requirements**:
- Given a contributor, then the coverage floor, what it measures, and what it excludes are documented where they will look.
- Given `vision.md`, then its "Not yet wired" note is removed, because it will be.
- Given the pipeline, then the coverage invocation appears in the workflow it actually runs in.
- Given the agent skill, then nothing describing CLI behavior changed — and that is stated, so a reader knows this epic was structural.

**Files**: `vision.md`, `README.md`, `docs/QUICK-VALIDATION.md`, `.github/workflows/build.yml`
**Tests**: full suite with coverage

---

## Deferred — `run_inspector`, `validate_environments_yaml`, and the Tail

`run_inspector` (24) shares the wrapper shape and should adopt the task 6 pattern once it is proven, but it needs the PBIR Inspector binary to exercise its failure paths. `validate_environments_yaml` (22) is stable and rarely touched. The remaining `PLR0913`/`PLR0912` findings are individually small. Cut for risk-to-benefit, not because they are acceptable.

## Note — A Refactor Must Not Change Behavior

Every task here is structural. The suite is the safety net, which is exactly why coverage is wired first: at 75% today, roughly one line in four is unwatched while the code moves underneath it.
