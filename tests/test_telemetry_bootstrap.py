"""Contract tests for telemetry table bootstrap (Telemetry Table Bootstrap).

Scope
-----
Queued ingest accepts a batch aimed at a table that does not exist — the
request is valid and the failure happens later, out of sight. So `fab-test`
printed `telemetry delivered` for a record that could never land. These
tests pin both halves of the fix: the destination is ensured before a send,
and a send that cannot land is never reported as one.

No cluster: the management calls are a seam.

    pytest -m telemetry tests/test_telemetry_bootstrap.py
    pytest -m telemetry tests/test_telemetry_bootstrap.py -k missing
"""

from __future__ import annotations

import pytest

from fabric_ci_cd_dataops.scripts._telemetry import EventhouseConfig
from fabric_ci_cd_dataops.scripts.eventhouse_logger import PAYLOAD_MAPPING, EventhouseSink

_URI = "https://trd-abc123.z2.kusto.fabric.microsoft.com"


def _config(database: str = "fabric_ops") -> EventhouseConfig:
    return EventhouseConfig(
        uri=_URI,
        database=database,
        uri_origin="fab-test.yml:telemetry.eventhouse.uri",
        database_origin="fab-test.yml:telemetry.eventhouse.database",
    )


class _FakeCluster:
    """Stands in for the cluster's management endpoint.

    Records every command issued, so a test can assert not just the outcome
    but how much schema work a run did — which is the difference between
    ensuring a table and hammering one.
    """

    def __init__(self, tables=(), mappings=(), fail_create: Exception | None = None):
        self.tables = set(tables)
        self.mappings = {(t, m) for t, m in mappings}
        self.fail_create = fail_create
        self.commands: list[tuple[str, str]] = []

    def show_tables(self, database):
        self.commands.append((database, ".show tables"))
        return sorted(self.tables)

    def show_mappings(self, database, table):
        self.commands.append((database, f".show table {table} ingestion json mappings"))
        return sorted(m for t, m in self.mappings if t == table)

    def create_table(self, database, table):
        self.commands.append((database, f".create-merge table {table}"))
        if self.fail_create is not None:
            raise self.fail_create
        self.tables.add(table)

    def create_mapping(self, database, table, mapping):
        self.commands.append((database, f".create-or-alter table {table} mapping {mapping}"))
        if self.fail_create is not None:
            raise self.fail_create
        self.mappings.add((table, mapping))


def _sink(cluster: _FakeCluster, ingested: list | None = None) -> EventhouseSink:
    """A sink whose cluster management and ingest are both stand-ins."""
    # `ingested if ingested is not None else []`, not `ingested or []`: an
    # empty list is falsy, and the latter would append to a throwaway copy —
    # which is exactly the assertion these tests depend on.
    sent = ingested if ingested is not None else []
    sink = EventhouseSink(_config())
    sink._cluster = lambda: cluster
    sink._ingest = lambda table, rows: sent.append((table, rows))
    return sink


def _payload(artifact="Sales"):
    return {"analyzer": "bpa", "artifact_name": artifact, "status": "passed"}


# --------------------------------------------------------------------------
# A missing table is not a successful send
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_table_that_cannot_be_created_is_not_reported_as_delivered():
    """Given a missing table that creation cannot fix, should report failure.

    Queued ingest would accept this batch and drop it later, out of sight.
    Reporting `ok` for it is the placeholder's lie one layer lower.
    """
    cluster = _FakeCluster(fail_create=PermissionError("Forbidden: may not create tables"))
    ingested: list = []
    sink = _sink(cluster, ingested)

    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert result.ok is False
    assert result.sent == 0
    assert ingested == [], "nothing should be sent to a destination that does not exist"


@pytest.mark.telemetry
def test_the_failure_names_the_table_and_the_database():
    """Given a destination that could not be ensured, should name both.

    "table not found" without a name sends a reader to the wrong cluster.
    """
    cluster = _FakeCluster(fail_create=PermissionError("Forbidden"))
    sink = _sink(cluster)

    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert "fabric_static_analysis" in result.error
    assert "fabric_ops" in result.error


@pytest.mark.telemetry
def test_the_failure_carries_the_kql_to_run_by_hand():
    """Given creation was refused, should hand the reader the statements to run.

    A governed cluster where CI may ingest but not alter schema is a normal
    arrangement, not a misconfiguration. Naming the permission without the
    remedy leaves that reader stuck.
    """
    cluster = _FakeCluster(fail_create=PermissionError("Forbidden"))
    sink = _sink(cluster)

    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert ".create-merge table fabric_static_analysis (Data: dynamic)" in result.error
    assert PAYLOAD_MAPPING in result.error


# --------------------------------------------------------------------------
# Creating what is absent
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_an_absent_table_is_created_with_a_single_data_column():
    """Given no table, should create it and then ingest."""
    cluster = _FakeCluster()
    ingested: list = []
    sink = _sink(cluster, ingested)

    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert result.ok is True
    assert "fabric_static_analysis" in cluster.tables
    assert ingested, "the send should follow the creation"


@pytest.mark.telemetry
def test_an_existing_table_and_mapping_are_left_alone():
    """Given a healthy cluster, should do no schema work at all.

    A run against a working destination should not issue create statements
    it does not need; the check is the point, not the creation.
    """
    cluster = _FakeCluster(
        tables=("fabric_static_analysis",),
        mappings=(("fabric_static_analysis", PAYLOAD_MAPPING),),
    )
    sink = _sink(cluster)

    sink.add("fabric_static_analysis", _payload())
    sink.flush()

    assert not [c for c in cluster.commands if "create" in c[1]]


@pytest.mark.telemetry
def test_the_destination_is_checked_once_per_run_not_once_per_record():
    """Given many records for one table, should check that table once.

    This is a management round trip against the query endpoint. Paying it
    per artifact repeats exactly the mistake batching was introduced to fix.
    """
    cluster = _FakeCluster(
        tables=("fabric_static_analysis",),
        mappings=(("fabric_static_analysis", PAYLOAD_MAPPING),),
    )
    sink = _sink(cluster)

    for artifact in ("Sales", "Finance", "Ops"):
        sink.add("fabric_static_analysis", _payload(artifact))
    sink.flush()

    assert len([c for c in cluster.commands if c[1] == ".show tables"]) == 1


@pytest.mark.telemetry
def test_each_table_is_ensured_independently():
    """Given both tables in one run, should ensure each.

    A repository with no semantic model never touches the dynamic table, so
    ensuring one cannot stand in for the other.
    """
    cluster = _FakeCluster()
    sink = _sink(cluster)

    sink.add("fabric_static_analysis", _payload())
    sink.add("fabric_dynamic_analysis", _payload())
    sink.flush()

    assert cluster.tables == {"fabric_static_analysis", "fabric_dynamic_analysis"}


# --------------------------------------------------------------------------
# The mapping is checked too
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_a_table_without_the_mapping_gets_one():
    """Given a table but no mapping, should create the mapping.

    This is the quiet case: a table with no mapping ingests *successfully*
    and stores empty rows, so nothing downstream ever raises.
    """
    cluster = _FakeCluster(tables=("fabric_static_analysis",))
    sink = _sink(cluster)

    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert result.ok is True
    assert ("fabric_static_analysis", PAYLOAD_MAPPING) in cluster.mappings


@pytest.mark.telemetry
def test_a_mapping_that_cannot_be_created_is_not_reported_as_delivered():
    """Given a mapping that cannot be created, should refuse rather than ingest blind.

    Ingesting without the mapping would succeed and store nothing usable —
    the worst of the failure modes, because it looks like it worked.
    """
    cluster = _FakeCluster(
        tables=("fabric_static_analysis",),
        fail_create=PermissionError("Forbidden"),
    )
    ingested: list = []
    sink = _sink(cluster, ingested)

    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert result.ok is False
    assert ingested == []


# --------------------------------------------------------------------------
# Distinguishing the failures
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_an_unreachable_cluster_is_not_reported_as_a_permission_problem():
    """Given the cluster is down, should say so rather than blame the schema.

    A reader told to check permissions when the cluster is unreachable
    loses the thread entirely.
    """

    class _Unreachable(_FakeCluster):
        def show_tables(self, database):
            raise ConnectionError("Failed to process network request for the endpoint")

    sink = _sink(_Unreachable())
    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert result.ok is False
    assert "network request" in result.error
    assert "Database Ingestor" not in result.error


@pytest.mark.telemetry
def test_a_missing_database_is_distinguished_from_a_missing_table():
    """Given the database does not exist, should say so — fab-test never creates one.

    The boundary of what this tool will build for you should be visible in
    the message, not discovered by reading source.
    """

    class _NoDatabase(_FakeCluster):
        def show_tables(self, database):
            raise RuntimeError(f"Database '{database}' was not found")

    sink = _sink(_NoDatabase())
    sink.add("fabric_static_analysis", _payload())
    result = sink.flush()

    assert result.ok is False
    assert "fabric_ops" in result.error
    assert "database" in result.error.lower()
