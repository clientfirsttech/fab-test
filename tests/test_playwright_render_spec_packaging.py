"""Contract tests: the Playwright render spec ships where a consumer can run it.

Scope
-----
`invoke_playwright.py` pointed pytest at `<repo_root>/tests/test_playwright_visual.py`
-- a path that only exists in a checkout of this repository. A `pip install
fab-test` consumer has no `tests/` directory, so every real Playwright run
failed outright with "ERROR: usage: python -m pytest" the moment it was run
from outside this repository (verified 2026-09-26 from `.venv-test`, an
installed wheel, in a scratch folder with no checkout at all). The render
spec now ships inside the installed package instead (Playwright CI Guide
epic, Render Spec Packaging task).

    pytest -m playwright tests/test_playwright_render_spec_packaging.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts.invoke_playwright import _spec_path

pytestmark = pytest.mark.playwright


def test_spec_path_resolves_inside_the_installed_package() -> None:
    """The spec pytest is pointed at lives under the package, not a repo
    checkout's tests/ directory -- so it exists after `pip install fab-test`."""
    spec = _spec_path()

    assert spec.exists()
    assert "playwright_validation" in spec.parts
    assert "tests" not in spec.parts


def test_spec_path_is_not_repo_root_relative(tmp_path) -> None:
    """A consumer's cwd (no `tests/` at all) must not change where the spec
    resolves to -- it is derived from the installed module, not `_repo_root()`."""
    import os

    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        spec = _spec_path()
    finally:
        os.chdir(original_cwd)

    assert spec.exists()


@pytest.mark.integration
def test_the_packaged_spec_collects_with_no_live_credentials() -> None:
    """`pytest --collect-only` against the resolved spec must succeed with
    zero test cases (PLAYWRIGHT_TEST_CASES unset) rather than an import or
    collection error -- proving the file pytest is pointed at is a real,
    importable pytest module wherever fab-test is installed."""
    spec = _spec_path()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(spec), "-m", "playwright", "--collect-only", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "error" not in result.stdout.lower(), result.stdout
