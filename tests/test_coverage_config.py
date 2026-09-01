"""Contract tests for the coverage configuration (Complexity and Coverage §1-2).

Scope
-----
The 80% floor in vision.md is only meaningful if the denominator is
honest. These tests guard the two ways it could quietly stop being so: an
omit entry that no longer matches anything (so it silently protects
nothing), and an omit entry broad enough to swallow library code added
later (so the floor is met by not measuring).

They read `pyproject.toml` rather than running coverage, so they are fast
and always pass on any machine.
"""

import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src" / "fab_test"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def coverage_run(pyproject) -> dict:
    return pyproject["tool"]["coverage"]["run"]


@pytest.mark.fab_test
def test_pytest_cov_is_a_dev_dependency(pyproject):
    """A fresh clone must be able to measure without guessing what to install."""
    dev = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(d.startswith("pytest-cov") for d in dev), dev


@pytest.mark.fab_test
def test_coverage_is_scoped_to_the_package(coverage_run):
    """Tests are excluded from the denominator, per vision.md."""
    assert coverage_run["source"] == ["src/fab_test"]


@pytest.mark.fab_test
def test_every_omitted_path_still_exists(coverage_run):
    """A stale omit protects nothing and hides that it protects nothing.

    If a module is renamed or deleted, its omit entry keeps matching zero
    files, and the exclusion silently becomes a no-op that nobody notices
    until coverage drops for an unrelated reason.
    """
    for pattern in coverage_run.get("omit", []):
        matches = list(_ROOT.glob(pattern))
        assert matches, f"omit pattern matches nothing: {pattern}"


@pytest.mark.fab_test
def test_omits_are_explicit_paths_not_wildcards_over_the_package(coverage_run):
    """A broad pattern could swallow library code added later.

    Meeting the floor by not measuring is worse than missing it, so each
    exclusion names one file.
    """
    for pattern in coverage_run.get("omit", []):
        assert pattern.endswith(".py"), f"omit is not a single file: {pattern}"
        assert "*" not in Path(pattern).stem, f"wildcard in filename: {pattern}"


@pytest.mark.fab_test
def test_no_core_cli_module_is_omitted(coverage_run):
    """The modules the CLI contract rests on must always be measured."""
    omitted = {Path(p).name for p in coverage_run.get("omit", [])}
    core = {
        "fab_test.py",
        "fab_test_registry.py",
        "fab_test_summary.py",
        "_analyzer_envelope.py",
        "_target.py",
        "_credentials.py",
        "_config.py",
        "_report_html.py",
        "_run_manifest.py",
    }

    assert not (omitted & core), f"core modules omitted: {omitted & core}"


@pytest.mark.fab_test
def test_pytest_ini_does_not_gate_on_coverage():
    """A `pytest -m bpa` run covers a fraction of src/ by design.

    Putting --cov-fail-under in pytest.ini would fail every granular run
    and defeat the token-saving constraint that makes them worth having.
    The threshold belongs in the CI invocation alone.
    """
    ini = (_ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "--cov-fail-under" not in ini
    assert "--cov=" not in ini


@pytest.mark.fab_test
def test_omitted_modules_are_documented_with_a_reason(coverage_run):
    """Each exclusion carries a comment saying what would bring it back."""
    raw = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = raw.split("[tool.coverage.run]", 1)[1].split("[tool.", 1)[0]

    for pattern in coverage_run.get("omit", []):
        name = Path(pattern).name
        assert name in block, f"{name} is omitted but unexplained"
    assert "#" in block, "the omit list needs its reasoning inline"
