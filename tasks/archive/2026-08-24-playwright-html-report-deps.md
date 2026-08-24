# Playwright HTML Report Dependencies Epic

**Status**: ✅ COMPLETED
**Goal**: `fab-test playwright` runs successfully on a fresh install without a manual pip install.

## Overview

`fab-test playwright --env DEV` failed with `pytest: error: unrecognized arguments:
--html=... --self-contained-html` because `invoke_playwright.py` passes pytest-html's
CLI flags, but `pytest-html` (and `pytest-playwright`, which registers the `playwright`
fixtures the spec itself needs) are not declared anywhere in `pyproject.toml`. A `.venv`
built from `pip install -e .` or `pip install -e ".[dev]"` never receives them, so the
subprocess pytest invocation rejects the flags outright.

---

## Declare pytest-html and pytest-playwright as dependencies

`invoke_playwright.py` hard-codes `--html=...` and `--self-contained-html` in its pytest
invocation, and the playwright spec itself needs `pytest-playwright` for its fixtures.
Both must be installable from `pyproject.toml` alone.

**Requirements**:
- Given a fresh clone with only `pip install -e ".[dev]"` run, should have `pytest-html`
  and `pytest-playwright` available so `fab-test playwright` does not fail with
  "unrecognized arguments"
- Given `pyproject.toml`'s `dev` optional-dependencies, should list `pytest-html` and
  `pytest-playwright` explicitly (contract test, mirroring the existing
  `test_pytest_cov_is_a_dev_dependency` pattern in `tests/test_coverage_config.py`)
