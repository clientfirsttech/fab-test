"""Contract tests for the Lakehouse sink (Lakehouse Telemetry Sink §3).

Scope
-----
`LakehouseSink` mirrors `EventhouseSink`: a run-scoped batch, nothing
imported/authenticated until `flush` has something to send, and a flush
that never raises into the analyzer run. No OneLake account, no network —
these tests pin the shape against a stand-in ADLS Gen2 client.

    pytest -m telemetry tests/test_lakehouse_telemetry_ingest.py
    pytest -m telemetry tests/test_lakehouse_telemetry_ingest.py -k extra
"""

from __future__ import annotations

import builtins
import sys
import tomllib
from pathlib import Path

import pytest

from fab_test.scripts._telemetry import LakehouseConfig, TelemetryDependencyError
from fab_test.scripts.lakehouse_logger import LakehouseSink

_WORKSPACE = "analytics-ws"
_LAKEHOUSE = "TelemetryLakehouse"
_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _config() -> LakehouseConfig:
    """A complete destination, built fresh per test."""
    return LakehouseConfig(
        workspace=_WORKSPACE,
        lakehouse=_LAKEHOUSE,
        workspace_origin="fab-test.yml:telemetry.lakehouse.workspace",
        lakehouse_origin="fab-test.yml:telemetry.lakehouse.lakehouse",
    )


class _FakeWriter:
    """Records what would be written, and how often, in place of `_write`."""

    def __init__(self, fail_with: Exception | None = None):
        self.batches: list[tuple[str, list[dict]]] = []
        self.fail_with = fail_with

    def write(self, table: str, rows: list[dict]) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.batches.append((table, rows))


def _sink(writer: _FakeWriter) -> LakehouseSink:
    """A sink wired to a stand-in writer rather than a real OneLake account."""
    sink = LakehouseSink(_config())
    sink._write = writer.write
    return sink


def _payload(artifact: str) -> dict:
    return {"analyzer": "bpa", "artifact_name": artifact, "status": "passed"}


# --------------------------------------------------------------------------
# One write per table per run, not one per artifact
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_records_are_batched_and_written_once_per_table():
    """Given several artifacts, should write one file rather than one per artifact."""
    writer = _FakeWriter()
    sink = _sink(writer)

    for artifact in ("Sales", "Finance", "Ops"):
        sink.add("fabric_static_analysis", _payload(artifact))
    sink.flush()

    assert len(writer.batches) == 1, "three artifacts must not mean three writes"
    table, rows = writer.batches[0]
    assert table == "fabric_static_analysis"
    assert [row["artifact_name"] for row in rows] == ["Sales", "Finance", "Ops"]


@pytest.mark.telemetry
def test_records_for_different_tables_are_written_separately():
    """Given static and dynamic records, should write each table's rows separately."""
    writer = _FakeWriter()
    sink = _sink(writer)

    sink.add("fabric_static_analysis", _payload("Sales"))
    sink.add("fabric_dynamic_analysis", _payload("Sales"))
    sink.flush()

    assert {table for table, _ in writer.batches} == {
        "fabric_static_analysis",
        "fabric_dynamic_analysis",
    }


@pytest.mark.telemetry
def test_nothing_added_means_nothing_written():
    """Given no records, should not build a client or write at all."""
    writer = _FakeWriter()
    sink = _sink(writer)

    result = sink.flush()

    assert writer.batches == []
    assert result.sent == 0
    assert result.ok is True, "an empty flush is a success, not a failure"


@pytest.mark.telemetry
def test_flushing_twice_does_not_rewrite():
    """Given a second flush, should write nothing more — a batch is drained, not replayed."""
    writer = _FakeWriter()
    sink = _sink(writer)

    sink.add("fabric_static_analysis", _payload("Sales"))
    sink.flush()
    sink.flush()

    assert len(writer.batches) == 1


# --------------------------------------------------------------------------
# What the result means
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_successful_flush_reports_what_it_sent():
    """Given a successful write, should report the count actually written."""
    writer = _FakeWriter()
    sink = _sink(writer)

    sink.add("fabric_static_analysis", _payload("Sales"))
    sink.add("fabric_static_analysis", _payload("Finance"))
    result = sink.flush()

    assert result.ok is True
    assert result.sent == 2
    assert result.error is None


@pytest.mark.telemetry
def test_a_failed_flush_is_not_reported_as_success():
    """Given a write that raises, should report failure rather than True."""
    writer = _FakeWriter(fail_with=RuntimeError("account unreachable"))
    sink = _sink(writer)

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert result.ok is False
    assert result.sent == 0
    assert "account unreachable" in result.error


@pytest.mark.telemetry
def test_a_failed_flush_names_the_permission_grant_when_it_was_an_authorization_problem():
    """Given a 403, should carry a permission hint through to the caller."""
    writer = _FakeWriter(fail_with=RuntimeError("Forbidden (403): not authorized"))
    sink = _sink(writer)

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert "permitted to write" in result.error


@pytest.mark.telemetry
def test_a_flush_never_raises_into_the_analyzer_run():
    """Given any write failure, should return a result rather than propagate."""
    writer = _FakeWriter(fail_with=RuntimeError("boom"))
    sink = _sink(writer)
    sink.add("fabric_static_analysis", _payload("Sales"))

    result = sink.flush()  # must not raise

    assert result.ok is False


@pytest.mark.telemetry
def test_writing_without_a_destination_reports_failure_not_success():
    """Given no configured destination, should report failure rather than a silent True."""
    sink = LakehouseSink(
        LakehouseConfig(
            workspace="", lakehouse="", workspace_origin="default", lakehouse_origin="default"
        )
    )

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert result.ok is False
    assert "telemetry.lakehouse" in result.error, "say which key would fix it"


# --------------------------------------------------------------------------
# The real write: filesystem, directory, and file client shape
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_write_creates_the_run_directory_and_uploads_one_file_per_table():
    """Given a table's records, should ensure the directory exists and upload one JSONL file.

    Exercises the real `_write` (not the `_write` seam the batching tests
    above use) against a stand-in ADLS Gen2 client shaped like the real SDK,
    so a Lakehouse whose `Files/fab-test-telemetry/<table>/` path doesn't
    exist yet is written to rather than erroring.
    """
    from fab_test.scripts.lakehouse_logger import LakehouseDependencies

    calls: list[tuple] = []

    class _FakeFileClient:
        def __init__(self, path):
            self.path = path

        def upload_data(self, data, overwrite):
            calls.append(("upload", self.path, data, overwrite))

    class _FakeDirectoryClient:
        def __init__(self, path):
            self.path = path

        def create_directory(self):
            calls.append(("create_directory", self.path))

        def get_file_client(self, name):
            return _FakeFileClient(f"{self.path}/{name}")

    class _FakeFileSystemClient:
        def get_directory_client(self, path):
            return _FakeDirectoryClient(path)

    class _FakeServiceClient:
        def __init__(self, account_url, credential):
            calls.append(("service_client", account_url))

        def get_file_system_client(self, workspace):
            calls.append(("filesystem", workspace))
            return _FakeFileSystemClient()

    sink = LakehouseSink(_config(), run_id="run-123")
    sink._dependencies = lambda: LakehouseDependencies(service_client_cls=_FakeServiceClient)
    sink._credential = object

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert result.ok is True
    assert ("filesystem", _WORKSPACE) in calls
    assert (
        "create_directory",
        f"{_LAKEHOUSE}.Lakehouse/Files/fab-test-telemetry/fabric_static_analysis",
    ) in calls
    upload = next(c for c in calls if c[0] == "upload")
    assert upload[1] == (
        f"{_LAKEHOUSE}.Lakehouse/Files/fab-test-telemetry/fabric_static_analysis/run-123.jsonl"
    )
    assert b"Sales" in upload[2]
    assert upload[3] is True, "must overwrite rather than fail on a rerun of the same run id"


@pytest.mark.telemetry
def test_write_addresses_a_guid_lakehouse_without_the_friendly_name_suffix():
    """Given the Lakehouse configured by its item GUID, should not append `.Lakehouse`.

    A tenant with OneLake friendly names disabled rejects `<guid>.Lakehouse` --
    live-verified against a real workspace ("FriendlyNameSupportDisabled:
    WorkspaceId and ArtifactId should be either valid Guids or valid Names").
    The `.Lakehouse` item-type suffix only makes sense to disambiguate a
    friendly *name*; a GUID already identifies the item uniquely and must be
    used bare.
    """
    from fab_test.scripts.lakehouse_logger import LakehouseDependencies

    guid = "b2ce5e9c-16cc-48d0-ba52-b6d8b98eb263"
    calls: list[tuple] = []

    class _FakeFileClient:
        def __init__(self, path):
            self.path = path

        def upload_data(self, data, overwrite):
            calls.append(("upload", self.path, data, overwrite))

    class _FakeDirectoryClient:
        def __init__(self, path):
            self.path = path

        def create_directory(self):
            calls.append(("create_directory", self.path))

        def get_file_client(self, name):
            return _FakeFileClient(f"{self.path}/{name}")

    class _FakeFileSystemClient:
        def get_directory_client(self, path):
            return _FakeDirectoryClient(path)

    class _FakeServiceClient:
        def __init__(self, account_url, credential):
            calls.append(("service_client", account_url))

        def get_file_system_client(self, workspace):
            return _FakeFileSystemClient()

    config = LakehouseConfig(
        workspace=_WORKSPACE,
        lakehouse=guid,
        workspace_origin="fab-test.yml:telemetry.lakehouse.workspace",
        lakehouse_origin="fab-test.yml:telemetry.lakehouse.lakehouse",
    )
    sink = LakehouseSink(config, run_id="run-123")
    sink._dependencies = lambda: LakehouseDependencies(service_client_cls=_FakeServiceClient)
    sink._credential = object

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert result.ok is True
    assert (
        "create_directory",
        f"{guid}/Files/fab-test-telemetry/fabric_static_analysis",
    ) in calls
    assert not any(".Lakehouse" in call[1] for call in calls if call[0] == "create_directory")


# --------------------------------------------------------------------------
# The [telemetry-lakehouse] optional extra
# --------------------------------------------------------------------------


def _project() -> dict:
    """The parsed pyproject, read fresh so no test mutates another's view."""
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


@pytest.mark.telemetry
def test_the_base_install_carries_no_onelake_sdk():
    """Given a plain install, should pull in no ADLS Gen2 client."""
    dependencies = " ".join(_project()["project"]["dependencies"])

    assert "file-datalake" not in dependencies


@pytest.mark.telemetry
def test_the_telemetry_lakehouse_extra_declares_the_onelake_package():
    """Given the [telemetry-lakehouse] extra, should declare azure-storage-file-datalake."""
    extras = _project()["project"]["optional-dependencies"]

    assert "telemetry-lakehouse" in extras, "pip install cft-fab-test[telemetry-lakehouse] must resolve"
    assert "azure-storage-file-datalake" in " ".join(extras["telemetry-lakehouse"])


@pytest.mark.telemetry
def test_the_install_hint_matches_the_declared_extra_name():
    """Given the hint shown to a user, should name an extra that actually exists."""
    from fab_test.scripts.lakehouse_logger import TELEMETRY_LAKEHOUSE_EXTRA_HINT

    extras = _project()["project"]["optional-dependencies"]

    assert "cft-fab-test[telemetry-lakehouse]" in TELEMETRY_LAKEHOUSE_EXTRA_HINT
    assert "telemetry-lakehouse" in extras


@pytest.mark.telemetry
def test_importing_the_logger_does_not_import_the_onelake_sdk():
    """Given telemetry is not running, should not import the ADLS Gen2 client at module level."""
    source = (
        Path(__file__).resolve().parents[1] / "src/fab_test/scripts/lakehouse_logger.py"
    ).read_text(encoding="utf-8")

    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) and "azure.storage.filedatalake" in stripped:
            assert line.startswith(" "), (
                f"the OneLake SDK must be imported inside a function, not at module level: "
                f"{stripped}"
            )


@pytest.mark.telemetry
def test_a_missing_extra_names_the_install_command(monkeypatch):
    """Given the extra is not installed, should raise with the pip command, not ImportError."""
    from fab_test.scripts.lakehouse_logger import load_lakehouse_dependencies

    real_import = builtins.__import__

    def _refuse_onelake(name, *args, **kwargs):
        if name.startswith("azure.storage.filedatalake"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _refuse_onelake)
    for module in list(sys.modules):
        if module.startswith("azure.storage.filedatalake"):
            monkeypatch.delitem(sys.modules, module, raising=False)

    with pytest.raises(TelemetryDependencyError) as exc:
        load_lakehouse_dependencies()

    assert "pip install" in str(exc.value)
    assert "cft-fab-test[telemetry-lakehouse]" in str(exc.value)


@pytest.mark.telemetry
def test_the_dependency_error_is_the_shared_type():
    """Given a missing SDK, should raise the same exception type Eventhouse uses.

    One handler in `fab_test_telemetry.py` catches both sinks' missing-extra
    failures; a second, differently-named exception type would need a second
    handler.
    """
    from fab_test.scripts.eventhouse_logger import (
        TelemetryDependencyError as eventhouse_dependency_error,
    )

    assert TelemetryDependencyError is eventhouse_dependency_error
