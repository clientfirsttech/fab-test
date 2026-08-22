"""Contract tests for the [telemetry] optional extra (Eventhouse Shipping §3).

Scope
-----
An egress-capable Kusto client does not belong in every install of a tool
whose main job is reading files on a laptop. It ships as an extra, is
imported only when telemetry actually runs, and says how to install itself
when it is missing.

    pytest -m telemetry tests/test_telemetry_extra.py
"""

from __future__ import annotations

import builtins
import sys
import tomllib
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.eventhouse_logger import (
    TELEMETRY_EXTRA_HINT,
    TelemetryDependencyError,
    load_ingest_dependencies,
)

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

_KUSTO_MODULES = ("azure.kusto.data", "azure.kusto.ingest")


def _project() -> dict:
    """The parsed pyproject, read fresh so no test mutates another's view."""
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# What the wheel declares
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_the_base_install_carries_no_kusto_sdk():
    """Given a plain install, should pull in no ingest client.

    The base wheel stays a file-reading tool. Shipping an egress-capable
    client to every user is a decision, not a default.
    """
    dependencies = " ".join(_project()["project"]["dependencies"])

    assert "kusto" not in dependencies


@pytest.mark.telemetry
def test_the_telemetry_extra_declares_both_kusto_packages():
    """Given the [telemetry] extra, should declare the data and ingest packages.

    Asserted by name for the same reason `test_packaged_metadata.py` asserts
    wheel contents: `package-data` entries were declared for months against
    directories that did not exist, and nothing failed.
    """
    extras = _project()["project"]["optional-dependencies"]

    assert "telemetry" in extras, "pip install fab-test[telemetry] must resolve"
    declared = " ".join(extras["telemetry"])
    assert "azure-kusto-data" in declared
    assert "azure-kusto-ingest" in declared


@pytest.mark.telemetry
def test_the_install_hint_matches_the_declared_extra_name():
    """Given the hint shown to a user, should name an extra that actually exists.

    A remediation message naming a non-existent extra is worse than none: it
    sends the reader to a command that fails for a different reason.
    """
    extras = _project()["project"]["optional-dependencies"]

    assert "fab-test[telemetry]" in TELEMETRY_EXTRA_HINT
    assert "telemetry" in extras


# --------------------------------------------------------------------------
# Import cost is paid by the runs that use it
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_importing_the_logger_does_not_import_the_kusto_sdk():
    """Given telemetry is not running, should not import the ingest client.

    Import cost belongs to the runs that use it, the way `_credentials` and
    `_target` are already deferred.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fabric_ci_cd_dataops/scripts/eventhouse_logger.py"
    ).read_text(encoding="utf-8")

    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and "kusto" in stripped:
            assert line.startswith(" "), (
                f"the Kusto SDK must be imported inside a function, not at module level: {stripped}"
            )


# --------------------------------------------------------------------------
# A missing extra says how to install itself
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_missing_extra_names_the_install_command(monkeypatch):
    """Given the extra is not installed, should raise with the pip command, not ImportError."""
    real_import = builtins.__import__

    def _refuse_kusto(name, *args, **kwargs):
        if name.startswith("azure.kusto"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _refuse_kusto)
    for module in list(sys.modules):
        if module.startswith("azure.kusto"):
            monkeypatch.delitem(sys.modules, module, raising=False)

    with pytest.raises(TelemetryDependencyError) as exc:
        load_ingest_dependencies()

    assert "pip install" in str(exc.value)
    assert "fab-test[telemetry]" in str(exc.value)
    assert "Traceback" not in str(exc.value)


@pytest.mark.telemetry
def test_the_dependency_error_is_not_a_bare_import_error():
    """Given the failure type, should be catchable without catching every ImportError.

    §6 turns this into a warning rather than a crash; a bare ImportError
    would force that handler to swallow unrelated import bugs too.
    """
    assert issubclass(TelemetryDependencyError, Exception)
    assert not issubclass(TelemetryDependencyError, ImportError)
