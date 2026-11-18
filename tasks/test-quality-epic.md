# Test Quality Epic

**Status**: 📋 PLANNED 2026-11-15, decisions awaiting the user's review.
**Goal**: a test that can't fail, or passes on a wrong answer, is caught before merge: by a gate where a machine can tell, and by a pytest-specific skill where only review can.

**Decisions** (proposed 2026-11-15; review before starting):

1. **A new project skill, `fab-test-pytest`, not edits to `aidd-tdd` or `aidd-python`.** Those are vendored from the upstream AIDD framework; `aidd-tdd` is written for JavaScript (Riteway, Vitest, `vi.fn`) and says nothing about `parametrize`, `tmp_path`, `capsys` or markers. Editing them would fork upstream. The new skill is what `aidd-tdd` and `aidd-review` defer to for Python tests in this repo.
2. **Mechanical gates are ratchets, as for complexity**: they record today's count and fail only when it grows, so they land without a cleanup first.
3. **Mutation testing runs on changed modules only**, not the whole suite, and starts as a report rather than a gate until its runtime and noise are measured (task 1).
4. **Live tests in CI fail instead of skipping** when their tool is missing, behind one env var CI sets; on a laptop they still skip.

## Overview

WHY: a second-model review of the PBIR slicer and navigator tests (2026-11-15) found two tests that couldn't fail, calendar boundaries no test pinned, type-blind number comparisons, untested `init` error branches, and assertions that accepted any rejection reason. Each fix was checked by applying the mutation it should catch. None of these is caught by the gates we have: 80% line coverage and the complexity and module-size ratchets measure how much code runs, not whether a test would notice it being wrong. A repo-wide scan of 2,628 tests found the same shapes elsewhere: 101 of 182 `pytest.raises` without `match=`, 18 tests with no assertion, `is not None` as a test's only check, and about 810 mock or monkeypatch sites.

---

## Measure Mutation Testing

Run `mutmut` (or `cosmic-ray`) over the modules changed on `feature/pbir-slicer-default-state` and record runtime and survivors.

**Requirements**:
- Given the slicer and navigator modules, should report runtime, mutants and survivors, and say whether each survivor is a missing test or an equivalent mutant.
- Given the result, should decide between a CI gate, a PR report, or a local `aidd-review` step.

---

## Assertion Ratchet

A test like `test_complexity_budget.py` counting weak assertion shapes per file.

**Requirements**:
- Given a `pytest.raises` without `match=`, a test with no `assert` or `raises`, or a test whose only assertion is `is not None` or `"<literal>" in`, should count it against its file's recorded budget.
- Given a file over its budget, should fail naming the new occurrences.
- Given a file under its budget, should tell you to lower the recorded number.

---

## Mock Ratchet

Count `patch(`, `monkeypatch.setattr` and `MagicMock` per test file against a recorded budget, so mocking stops growing.

---

## Branch Coverage On Changed Lines

`--cov-branch` plus `diff-cover` on the PR diff, so an error branch that never runs is visible even when line coverage is 80%.

**Requirements**:
- Given a PR, should report uncovered branches on changed lines; whether it fails the build is decided after a week of reports.

---

## Skips Fail In CI

**Requirements**:
- Given `FAB_TEST_REQUIRE_TOOLS=1`, should fail rather than skip a live test whose tool (PBIR Inspector, Tabular Editor) is missing, so `CONTRACT.*` rules can't go unverified in CI while the run stays green.
- Given a structural check that skips because a file is absent (`test_module_layering.py`), should fail instead; absence is the bug it guards.
- Given the CI run, should print skips (`pytest -rs`) and fail on any not on an allow-list.

---

## fab-test-pytest Skill

A short skill for writing and reviewing pytest tests here, used by `aidd-tdd` and `aidd-review` for Python.

**Requirements**:
- Given a new test, should name the one-line change in the source that would make it fail, and check it where cheap.
- Given a "does not contain X" assertion, should put X in the input or add a positive control.
- Given a boundary (`<=`, `<`, a range), should test a sample on each side.
- Given a rejection, should assert the reason (`match=`, or the message), not only that it failed.
- Given Python equality that hides type (`3 == 3.0`, `True == 1`), should compare `(type(v), v)`.
- Given a test that edits a fixture, should assert the edit took before acting on it.
- Given a compiled artifact (JSON Logic, SQL, YAML), should have one fast test that evaluates or snapshots it, not only a live run.
- Given a "does not raise" test, should have a paired test that it rejects bad input.
- Given a test name, should match what it asserts (`test_given_X_should_Y`).
- Given a mock, should prefer a real fixture under `tmp_path`; mocking is the exception, as `aidd-tdd` already says.

---

## Apply It To The Suite

Use the ratchets' first counts to fix the worst files outside PBIR, starting with the 18 tests with no assertion and the `is not None`-only tests.

---

## Quality Gates

Whole-repo ruff, every ratchet, the coverage floor, and the CI-env run.
