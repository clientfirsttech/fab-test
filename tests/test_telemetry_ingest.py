"""Contract tests for the Eventhouse ingest itself (Eventhouse Shipping §5).

Scope
-----
Before this epic `publish_to_eventhouse` printed a banner ending in
`✅ TELEMETRY LOGGING SIMULATION COMPLETED` and returned True, so every
caller was told it worked. These tests pin the shape of a real ingest
against a stand-in client: batching, flushing, and what the return value
means.

A live cluster is out of scope here and is covered by the integration
marker — see `test_eventhouse_live.py`.

    pytest -m telemetry tests/test_telemetry_ingest.py
    pytest -m telemetry tests/test_telemetry_ingest.py -k batch
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fab_test.scripts._telemetry import EventhouseConfig
from fab_test.scripts.eventhouse_logger import EventhouseSink

_URI = "https://trd-abc123.z9.kusto.fabric.microsoft.com"


def _config() -> EventhouseConfig:
    """A complete destination, built fresh per test."""
    return EventhouseConfig(
        uri=_URI,
        database="fabric_ops",
        uri_origin="fab-test.yml:telemetry.eventhouse.uri",
        database_origin="fab-test.yml:telemetry.eventhouse.database",
    )


class _FakeIngestClient:
    """Records what would be ingested, and how often a client was built."""

    def __init__(self, fail_with: Exception | None = None):
        self.batches: list[tuple[str, list[dict]]] = []
        self.fail_with = fail_with

    def ingest(self, table: str, rows: list[dict]) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.batches.append((table, rows))


def _sink(client: _FakeIngestClient) -> EventhouseSink:
    """A sink wired to a stand-in client rather than a cluster."""
    sink = EventhouseSink(_config())
    # The destination check is stubbed out: this file is about batching and
    # what a flush reports, and whether the table exists has its own tests in
    # `test_telemetry_bootstrap.py`.
    sink._ensure_destination = lambda table: None
    sink._ingest = client.ingest
    return sink


def _payload(artifact: str) -> dict:
    return {"analyzer": "bpa", "artifact_name": artifact, "status": "passed"}


# --------------------------------------------------------------------------
# One client per run, not one per artifact
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_records_are_batched_and_sent_once_per_table():
    """Given several artifacts, should ingest one batch rather than one call each.

    `_send_telemetry` is called from `_run_one_artifact`, so a naive port
    pays connection setup once per artifact.
    """
    client = _FakeIngestClient()
    sink = _sink(client)

    for artifact in ("Sales", "Finance", "Ops"):
        sink.add("fabric_static_analysis", _payload(artifact))
    sink.flush()

    assert len(client.batches) == 1, "three artifacts must not mean three ingests"
    table, rows = client.batches[0]
    assert table == "fabric_static_analysis"
    assert [row["artifact_name"] for row in rows] == ["Sales", "Finance", "Ops"]


@pytest.mark.telemetry
def test_records_for_different_tables_are_sent_separately():
    """Given static and dynamic records, should ingest each table's rows to that table."""
    client = _FakeIngestClient()
    sink = _sink(client)

    sink.add("fabric_static_analysis", _payload("Sales"))
    sink.add("fabric_dynamic_analysis", _payload("Sales"))
    sink.flush()

    assert {table for table, _ in client.batches} == {
        "fabric_static_analysis",
        "fabric_dynamic_analysis",
    }


@pytest.mark.telemetry
def test_nothing_added_means_nothing_sent():
    """Given no records, should not build a client or call ingest at all."""
    client = _FakeIngestClient()
    sink = _sink(client)

    result = sink.flush()

    assert client.batches == []
    assert result.sent == 0
    assert result.ok is True, "an empty flush is a success, not a failure"


@pytest.mark.telemetry
def test_flushing_twice_does_not_resend():
    """Given a second flush, should send nothing more — a batch is drained, not replayed."""
    client = _FakeIngestClient()
    sink = _sink(client)

    sink.add("fabric_static_analysis", _payload("Sales"))
    sink.flush()
    sink.flush()

    assert len(client.batches) == 1


# --------------------------------------------------------------------------
# What the result means
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_successful_flush_reports_what_it_sent():
    """Given a successful ingest, should report the count actually accepted."""
    client = _FakeIngestClient()
    sink = _sink(client)

    sink.add("fabric_static_analysis", _payload("Sales"))
    sink.add("fabric_static_analysis", _payload("Finance"))
    result = sink.flush()

    assert result.ok is True
    assert result.sent == 2
    assert result.error is None


@pytest.mark.telemetry
def test_a_failed_flush_is_not_reported_as_success():
    """Given an ingest that raises, should report failure rather than True.

    The placeholder returned True for a send that never happened. That is
    the specific defect this task removes, so it gets its own test.
    """
    client = _FakeIngestClient(fail_with=RuntimeError("cluster unreachable"))
    sink = _sink(client)

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert result.ok is False
    assert result.sent == 0
    assert "cluster unreachable" in result.error


@pytest.mark.telemetry
def test_a_failed_flush_names_the_ingestor_role_when_it_was_an_authorization_problem():
    """Given a 403, should carry the grant hint through to the caller."""
    client = _FakeIngestClient(fail_with=RuntimeError("Forbidden (403): not authorized"))
    sink = _sink(client)

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert "Database Ingestor" in result.error


@pytest.mark.telemetry
def test_a_flush_never_raises_into_the_analyzer_run():
    """Given any ingest failure, should return a result rather than propagate.

    Telemetry is non-blocking by contract; a raise here would make a
    diagnostic feature able to fail a build.
    """
    client = _FakeIngestClient(fail_with=RuntimeError("boom"))
    sink = _sink(client)
    sink.add("fabric_static_analysis", _payload("Sales"))

    result = sink.flush()  # must not raise

    assert result.ok is False


# --------------------------------------------------------------------------
# The simulation is gone
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Schema independence
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_ingest_references_the_payload_mapping():
    """Given an ingest, should name the mapping that puts the payload in one column.

    The tables have a single `Data: dynamic` column and downstream Eventhouse
    functions do the transforming, so a new payload field never breaks
    ingest. That only works if the ingestion mapping is referenced: without
    it Kusto maps by column name and every field but `Data` is dropped on the
    floor, silently.
    """
    from fab_test.scripts.eventhouse_logger import (
        PAYLOAD_MAPPING,
        IngestDependencies,
    )

    captured = {}

    class _Properties:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class _Client:
        def __init__(self, _kcsb):
            pass

        def ingest_from_stream(self, _stream, ingestion_properties):
            pass

    class _Builder:
        @staticmethod
        def with_azure_token_credential(uri, _credential):
            captured["uri"] = uri
            return object()

    class _Format:
        JSON = "json"

    sink = EventhouseSink(_config())
    sink._ensure_destination = lambda table: None
    sink._dependencies = lambda: IngestDependencies(
        connection_string_builder=_Builder,
        ingest_client=_Client,
        ingestion_properties=_Properties,
        data_format=_Format,
    )
    sink._credential = object  # a credential stand-in; nothing authenticates here

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert result.ok is True
    assert captured["ingestion_mapping_reference"] == PAYLOAD_MAPPING
    assert captured["table"] == "fabric_static_analysis"
    assert captured["database"] == "fabric_ops"


@pytest.mark.telemetry
def test_the_ingest_endpoint_carries_the_ingest_prefix():
    """Given a query URI, should aim the client at the ingest endpoint.

    Queued ingest against the query endpoint is refused by the cluster.
    """
    from fab_test.scripts.eventhouse_logger import _ingest_uri

    assert _ingest_uri("https://trd-abc.z2.kusto.fabric.microsoft.com").startswith(
        "https://ingest-trd-abc"
    )


@pytest.mark.telemetry
def test_an_ingest_uri_is_not_prefixed_twice():
    """Given a URI that already names the ingest endpoint, should leave it alone.

    Fabric shows people the `ingest-` URI, so it is what they paste into
    `fab-test.yml`. Prefixing it again produces a host that does not exist.
    """
    from fab_test.scripts.eventhouse_logger import _ingest_uri

    already = "https://ingest-trd-abc.z2.kusto.fabric.microsoft.com"
    assert _ingest_uri(already) == already


@pytest.mark.telemetry
def test_the_placeholder_banner_is_gone():
    """Given the module source, should contain no simulation output.

    It printed roughly sixty lines per artifact and said the opposite of the
    truth: `SIMULATION COMPLETED` for a run that sent nothing.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "src/fab_test/scripts/eventhouse_logger.py"
    ).read_text(encoding="utf-8")

    for banished in ("SIMULATION", "Placeholder Implementation", "to be implemented"):
        assert banished not in source, f"the placeholder still says {banished!r}"


@pytest.mark.telemetry
def test_publishing_without_a_destination_reports_failure_not_success():
    """Given no configured destination, should report failure rather than a silent True."""
    sink = EventhouseSink(
        EventhouseConfig(uri="", database="", uri_origin="default", database_origin="default")
    )

    sink.add("fabric_static_analysis", _payload("Sales"))
    result = sink.flush()

    assert result.ok is False
    assert "telemetry.eventhouse" in result.error, "say which key would fix it"
