---
name: aidd-module-budgets
description: File-level size budgets for Python modules and test modules in this project, how to split a module that crossed one, and the seam to split on. Use when adding a test, adding a section to an existing module, reviewing a diff that grows a large file, or when the user asks why a file is so big.
---

# Module budgets

The ruff budgets in `pyproject.toml` are all *function*-level: complexity,
arguments, branches, statements. Nothing in this repo has ever measured a
*file*. That is how `tests/test_fab_test.py` reached 4,383 lines and 215 tests
without a single review objecting: every diff that grew it was small, and the
only thing wrong with it was the total.

A file nobody can hold in their head costs on every read — human or agent. An
agent asked to change one behavior loads the whole module.

## Budgets

| Unit | Soft (justify) | Hard (split before merging) |
|------|---------------|------------------------------|
| Source module | 400 lines | 800 lines |
| Test module | 500 lines | 900 lines |
| Tests per module | 40 | 80 |

Soft means: say in the commit message why this file earns the extra length.
Hard means: the split is part of the task that crossed it, not a follow-up.

A test module tracks its subject. If `fab_test.py` is 2,848 lines, its tests do
not belong in one file *because* the source is one file — the source is over
budget too, and the tests are the cheaper half to split first.

## Where to split a test module

Split on the **behavior seam**, not on the epic that added the tests.

Section banners named after epic sections (`# ... (CLI Agent Ergonomics §3)`)
are the tell that a file grew by accretion. §3 is when the code arrived, not
what it does. Six months later nobody greps for §3.

```sudolang
fn chooseSeam(tests) {
  Prefer: the observable behavior under test
    (exit codes | output contract | discovery | telemetry | tool bootstrap | config)
  Then:   the collaborator being faked
    (subprocess | filesystem | network | clock)
  Never:  the epic or task number that introduced the test
  Never:  "part 2" / "_more" / "_extra" — that is the same file with a new name
}
```

Name the file after the seam: `test_fab_test_exit_codes.py`, not
`test_fab_test_2.py`. A reader should predict the filename from the failure.

## Shared setup after a split

Fixtures used by more than one of the new modules move to `tests/conftest.py`.
Fixtures used by exactly one move with it. Do not create a `tests/helpers.py`
that every module imports — that rebuilds the monolith through the import graph.

## The review lens

When reviewing a diff, check the file the diff lands in, not only the diff:

1. **Did this diff push a file past a budget?** If yes, the split belongs in
   this change. A +120-line diff on a 4,000-line file reads as clean and is not.
2. **Is there a section banner naming an epic?** Rename it after the behavior,
   or move the section out.
3. **Is the new test placed by topic or by append?** Tests appended to the
   bottom because that is where the cursor was are a file-shape smell.

## Check

```bash
# Anything over its hard budget
find src tests -name '*.py' -exec wc -l {} + | sort -rn | head -20
```

Report the number, do not silently raise the budget. Raising one is a decision
with a reason, same rule as the ruff thresholds in [aidd-python](../aidd-python/SKILL.md).
