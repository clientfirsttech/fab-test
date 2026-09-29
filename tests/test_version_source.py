"""Contract tests for the version's single source of truth (TestPyPI Release §1).

Scope
-----
TestPyPI refuses a second upload of a version it already has, so every
rehearsal release needs a fresh one. When the version is written in two
places, the cheap bump hits one of them and the package then reports a
version it was not built as -- `fab-test --version` disagreeing with what
`pip` installed is the confusing failure, because both look authoritative.

These tests pin `__init__.py` as the only place the string is written and
assert the built distribution agrees with it. They read `pyproject.toml`
and the installed metadata rather than building a wheel, so they are fast
and pass on any machine with the package installed.
"""

import importlib.metadata
import tomllib
from pathlib import Path

import pytest
from packaging.version import InvalidVersion, Version

from fab_test import __version__

_ROOT = Path(__file__).resolve().parent.parent
_DISTRIBUTION = "cft-fab-test"
_VERSION_ATTR = "fab_test.__version__"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.mark.fab_test
def test_pyproject_does_not_pin_its_own_version(pyproject):
    """A static version in `[project]` is the second source of truth.

    It is also the one a bump reaches first, leaving `__init__.py` stale
    and the CLI reporting a version nobody published.
    """
    project = pyproject["project"]

    assert "version" not in project, "remove [project].version; declare it dynamic instead"
    assert "version" in project.get("dynamic", []), project.get("dynamic")


@pytest.mark.fab_test
def test_the_build_reads_the_version_from_the_package(pyproject):
    """`__init__.py` is where the version is written, so the build must read it there."""
    dynamic = pyproject["tool"]["setuptools"]["dynamic"]

    assert dynamic["version"] == {"attr": _VERSION_ATTR}, dynamic.get("version")


@pytest.mark.fab_test
def test_the_installed_distribution_agrees_with_the_package():
    """What `pip` installed and what the CLI reports must be the same string.

    A mismatch here means the working tree was bumped without reinstalling,
    which is exactly the state that publishes a wheel whose `--version`
    output is a lie.
    """
    installed = importlib.metadata.version(_DISTRIBUTION)

    assert installed == __version__, (
        f"installed {installed} != package {__version__}; reinstall with `pip install -e .`"
    )


@pytest.mark.fab_test
def test_the_version_is_a_version_an_index_will_accept():
    """A string PEP 440 cannot parse is rejected at upload, after the build."""
    try:
        parsed = Version(__version__)
    except InvalidVersion as exc:  # pragma: no cover - the assert reports it
        pytest.fail(f"{__version__!r} is not a PEP 440 version: {exc}")

    assert str(parsed) == __version__, "version is not in PEP 440 normalized form"
