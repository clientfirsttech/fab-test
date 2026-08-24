# Results Directory Rename Epic

**Status**: ✅ COMPLETED
**Goal**: Rename the default results directory from `analyzer-results/` to `fab-test-results/`

## Overview

`fab-test`'s default output directory was `analyzer-results/` — a name generic enough
that any repo already using another tool's `analyzer-results/` folder would silently
share it, and one that gave a reader no clue which tool produced it.
`fab-test-results/` fixes both. The only reason to do this now rather than never: the
project has never published a release (`__version__` is `1.0.0.0.dev1`, no git tags
exist), so no external CI depended on the old path — the last cheap moment to make the
change. `.fab-test/results/` was considered and rejected: that directory is checked-in
config (its own scaffolded `.gitignore` excludes only `.env`), and mixing git-ignored
generated output into it would blur inputs with outputs.

Clean break, no compatibility shim: [vision.md](../../vision.md)'s backward-compat
constraint (*"existing commands, env vars, and result paths keep working"*) is amended
to *"result paths released in 1.0.0 and later keep working"*, superseding a prior
in-repo commitment recorded in
`tasks/archive/2026-08-19-cli-agent-ergonomics-epic.md` to never rename result
directories.

## What changed

- The two independent source-of-truth constants — `RESULTS_ROOT` in `fab_test.py` and
  the separate `_RESULTS_ROOT` in `_analyzer_envelope.py` — both now default to
  `fab-test-results`.
- Every literal that bypasses `--output-dir` (`invoke_playwright.py`'s test-cases dir,
  `--html`/`--junitxml` args, and `invoke_playwright_impact.py`'s manifest default)
  renamed in place. The bypass itself — these paths ignore `--output-dir` and
  `output_dir:` in `fab-test.yml` entirely — is a pre-existing defect, not touched here;
  filed as follow-up below.
- Help text, the `_FAB_TEST_YML_TEMPLATE` `fab-test init` scaffolds, and
  `fab-test.schema.json`'s default description all updated.
- `.gitignore`, `MANIFEST.in`, and `check_wheel_contents.py`'s `FORBIDDEN` list updated;
  the wheel guard keeps the old `analyzer-results/` entry permanently alongside the new
  one rather than dropping it, so a stray legacy directory still can't ship.
- 22 test files, ~91 call sites. Added a `results_root` fixture to `tests/conftest.py`
  (none existed) for future use. `test_target_discovery.py` and `test_scan.py`'s
  real-repo prune assertions now import the production `RESULTS_ROOT` constant instead
  of re-literalizing it, so they can't silently drift from it again. Added
  `test_output_dir_packaged_default_is_fab_test_results` — nothing previously pinned the
  packaged default, which is how the old name went unverified by the suite.
- Documentation: README, docs/QUICK-VALIDATION.md, and the fab-test skill (28 of 34 live
  hits) updated directly rather than through the `document` skill invocation, reaching
  the same end state; the remaining four files the skill doesn't cover
  (docs/RELEASE.md, docs/QUICKSTART-LOCAL.md, the pql-test and fab-inspector skills)
  fixed by hand and added to `document`'s own `SKILL.md` as targets so the next
  result-path change can't drift the same way again.
- `tasks/archive/**` and the one archive-summary bullet in `plan.md` referencing the old
  name deliberately left untouched — dated historical record, not live documentation.

**1386 passed, coverage 84.54%** (floor 80%, held); the 6 non-coverage failures in the
full run were confirmed pre-existing against the unmodified baseline (`git stash`),
unrelated to this change. Verified through the real installed CLI, not only the suite:
`config --show`, `--help`/`bpa --help`, `list`, `explain bpa`, a real `bpa` run, `all
--report`, and `fab-test local` all resolved paths under `fab-test-results/` with no
`analyzer-results/` recreated anywhere; `fab-test init` scaffolds the new default in a
scratch directory; `python -m build` + `check_wheel_contents.py` passed.

## Follow-up (separate epic, not this change)

`_analyzer_envelope._RESULTS_ROOT`, `invoke_playwright.py`, and
`invoke_playwright_impact.py` write to a path literal relative to cwd and ignore
`--output-dir` completely — anyone setting `output_dir:` in `fab-test.yml` today gets
results split across two directories. This rename neither caused nor fixed it.

Separately: `_PYPROJECT_CONFIG` loads at import time, so `--config PATH` does not
affect the `--output-dir` default, while `fab-test config --show` re-reads with the
explicit path — the two disagree when `--config` is passed.
