#!/usr/bin/env python3
"""
Eventhouse Telemetry Logger

Publishes CI/CD telemetry to Fabric Eventhouse tables.
Based on Eventhouse branch template from:
https://github.com/kerski/pbi-teams-more-analytic-support

Per Constraint C9:
- Telemetry must be feature-flagged via ENABLE_EVENTHOUSE_LOGGING
- Telemetry is optional and never mandatory
- Eventhouse schema is the system of record for metrics tracking

Target Tables:
- fabric_static_analysis
- fabric_dynamic_analysis
- fabric_deployments
- fabric_testbed_runs

Usage:
    python scripts/eventhouse_logger.py \\
        --table <table_name> \\
        --payload <telemetry.json> \\
        [--terse]

Exit codes:
    0  Logging completed (or gracefully skipped)
    1  Validation error
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._cli_utils import terse_print
from ._telemetry import TelemetryDependencyError

VALID_TABLES = [
    "fabric_static_analysis",
    "fabric_dynamic_analysis",
    "fabric_deployments",
    "fabric_testbed_runs"
]

TELEMETRY_EXTRA_HINT = "pip install 'cft-fab-test[telemetry]'"

# The ingestion mapping each telemetry table must define. The tables carry a
# single `Data: dynamic` column and downstream Eventhouse functions do the
# transforming, so the wire stays schema-independent: a new payload field is
# a new key inside `Data`, never a table alteration and never a broken
# ingest. The KQL to create a table and this mapping is in the Telemetry
# section of .github/skills/fab-test/SKILL.md; fab-test never creates them.
#
# Referencing it is not optional. Without a mapping the service maps by
# column name, matches nothing, and stores empty rows while reporting
# success -- which is the failure this whole module was rewritten to end.
PAYLOAD_MAPPING = "fab_test_payload"

# path "$" puts the whole JSON object into the one column.
_MAPPING_BODY = '[{"column":"Data","path":"$","datatype":"dynamic"}]'


class DestinationError(Exception):
    """The telemetry table or its mapping is missing and could not be created.

    Carries its own message through `describe_ingest_failure` unchanged: it
    already names the table, the database, and the KQL, and appending an
    ingest-permission hint to a table-creation failure would send the reader
    to the wrong grant.
    """


def create_statements(table: str) -> str:
    """Return the KQL that creates ``table`` and its ingestion mapping.

    One definition, used both to build the destination and to tell a reader
    how to build it by hand, so the documented statements cannot drift from
    the ones that actually run.
    """
    return (
        f"  .create-merge table {table} (Data: dynamic)\n"
        f"  .create-or-alter table {table} ingestion json mapping '{PAYLOAD_MAPPING}' "
        f"'{_MAPPING_BODY}'"
    )


def _unreachable_message(database: str, exc: Exception) -> str:
    """Explain why the destination could not be inspected.

    A missing database and an unreachable cluster look similar in a stack
    trace and need opposite responses, so they are separated here rather
    than left to the reader.
    """
    detail = f"{exc}"
    if "not found" in detail.lower() and database.lower() in detail.lower():
        return (
            f"telemetry database {database} was not found. fab-test creates tables, "
            f"never databases -- create the KQL database in Fabric first, then rerun."
        )
    return f"telemetry destination could not be inspected on database {database}: {detail}"


@dataclass(frozen=True)
class IngestDependencies:
    """The Kusto symbols ingest needs, loaded on demand."""

    connection_string_builder: Any
    ingest_client: Any
    ingestion_properties: Any
    data_format: Any


# What Kusto says when the credential is valid and the grant is not. A
# service principal without the Database Ingestor role fails the same way a
# bad secret does, and sending a reader to rotate a working secret wastes
# the one clue they had.
_AUTHORIZATION_MARKERS = ("forbidden", "unauthorized", "not authorized", "403")

_INGESTOR_ROLE_HINT = (
    "The credential authenticated but is not permitted to ingest. Grant it the "
    "Database Ingestor role on the KQL database (Fabric: the Eventhouse item -> "
    "Manage permissions), then retry."
)


def describe_ingest_failure(exc: Exception) -> str:
    """Return a reportable reason for an ingest failure.

    Redacted before it is returned: Kusto errors can quote the connection
    string that produced them, and the secrets constraint puts telemetry on
    the same footing as stdout and the run manifest.
    """
    from ._credentials import redact_secrets

    message = redact_secrets(f"{exc}")
    if isinstance(exc, DestinationError):
        # Already names the table, the database, and the KQL. Appending an
        # ingest-permission hint would point at the wrong grant: creating a
        # table needs more than Database Ingestor, not the same thing.
        return message
    if any(marker in message.lower() for marker in _AUTHORIZATION_MARKERS):
        return f"{message} -- {_INGESTOR_ROLE_HINT}"
    return message


def build_ingest_credential(env_file: Path | str | None = None) -> Any:
    """Return an Azure credential for Kusto ingest. See `_credentials.build_azure_credential`."""
    from ._credentials import build_azure_credential

    return build_azure_credential(env_file)


def load_ingest_dependencies() -> IngestDependencies:
    """Import the Kusto ingest client, or say how to install it.

    Imported here rather than at module scope so a run that never configures
    a destination never pays for the SDK -- the same deferral `_credentials`
    and `_target` already use.
    """
    try:
        # DataFormat is exported by azure.kusto.data, not azure.kusto.ingest --
        # importing it from the latter raises ImportError even with both
        # packages installed, which reads as a missing extra and is not one.
        from azure.kusto.data import DataFormat, KustoConnectionStringBuilder
        from azure.kusto.ingest import IngestionProperties, QueuedIngestClient
    except ImportError as exc:
        raise TelemetryDependencyError(
            "telemetry is configured but the Kusto ingest client is not installed. "
            f"Install it with: {TELEMETRY_EXTRA_HINT}"
        ) from exc
    return IngestDependencies(
        connection_string_builder=KustoConnectionStringBuilder,
        ingest_client=QueuedIngestClient,
        ingestion_properties=IngestionProperties,
        data_format=DataFormat,
    )


def publish_analyzer_telemetry(
    table_name: str,
    payload: dict[str, Any],
    terse: bool = False,
    force: bool = False,
) -> bool:
    """Publish analyzer telemetry, optionally bypassing the feature flag.

    This helper is consumed by ``fab_test.py`` and is intentionally non-blocking:
    telemetry failures return ``False`` rather than raising. When ``force`` is
    True, the payload is published even if ``ENABLE_EVENTHOUSE_LOGGING`` is off.
    """
    if not force and not validate_feature_flag(terse):
        return False

    if not validate_table_name(table_name, terse):
        return False

    if not validate_payload_schema(payload, table_name, terse):
        return False

    return publish_to_eventhouse(table_name, payload, terse)


def validate_feature_flag(terse: bool = False) -> bool:
    """Check if Eventhouse logging is enabled via feature flag."""
    enabled = os.getenv("ENABLE_EVENTHOUSE_LOGGING", "false").lower() == "true"

    if not enabled:
        terse_print(
            terse, "SKIP", "eventhouse_logger",
            "ENABLE_EVENTHOUSE_LOGGING=false; telemetry is optional per Constraint C9",
        )
        if not terse:
            print("ℹ️  Eventhouse logging is disabled (ENABLE_EVENTHOUSE_LOGGING=false)")
            print("   Per Constraint C9, telemetry is optional and never mandatory.")
        return False

    return True


def validate_table_name(table_name: str, terse: bool = False) -> bool:
    """Validate table name is one of the allowed Eventhouse tables."""
    if table_name not in VALID_TABLES:
        terse_print(
            terse, "ERROR", "eventhouse_table",
            f"invalid table '{table_name}'; valid: {', '.join(VALID_TABLES)}",
        )
        if not terse:
            print(f"Error: Invalid table name '{table_name}'", file=sys.stderr)
            print(f"Valid tables: {', '.join(VALID_TABLES)}", file=sys.stderr)
        return False

    return True


def load_payload(payload_path: Path, terse: bool = False) -> dict:
    """Load and validate telemetry payload from JSON file."""
    if not payload_path.exists():
        terse_print(terse, "ERROR", "eventhouse_payload", f"payload file not found: {payload_path}")
        if not terse:
            print(f"Error: Payload file not found: {payload_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(payload_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        terse_print(terse, "ERROR", "eventhouse_payload", f"invalid JSON: {e}")
        if not terse:
            print(f"Error: Invalid JSON in payload file: {e}", file=sys.stderr)
        sys.exit(1)


# Table-specific fields required in addition to the common schema.
_TABLE_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "fabric_static_analysis": ("results",),
    "fabric_dynamic_analysis": ("results", "environment"),
    "fabric_deployments": ("environment",),
    "fabric_testbed_runs": ("results",),
}


def _missing_table_fields(payload: dict, table_name: str) -> list[str]:
    """Return the table-specific required fields missing from ``payload``."""
    return [field for field in _TABLE_REQUIRED_FIELDS.get(table_name, ()) if field not in payload]


def _table_field_error(missing: list[str], table_name: str) -> str:
    """Build the "'x' and 'y' field(s) required for TABLE" message."""
    quoted = " and ".join(f"'{field}'" for field in missing)
    noun = "field" if len(missing) == 1 else "fields"
    return f"{quoted} {noun} required for {table_name}"


def validate_payload_schema(payload: dict, table_name: str, terse: bool = False) -> bool:
    """
    Validate payload matches expected schema for target table.

    Schema reference: Eventhouse branch template
    Source: https://github.com/kerski/pbi-teams-more-analytic-support

    Common fields across all tables:
    - timestamp
    - artifact_name
    - artifact_type
    - commit_sha
    - workflow_run_id
    - repository
    - actor
    """
    required_fields = [
        "timestamp",
        "artifact_name",
        "artifact_type",
        "commit_sha",
        "workflow_run_id",
        "repository",
        "actor"
    ]

    missing_fields = [field for field in required_fields if field not in payload]

    if missing_fields:
        terse_print(terse, "ERROR", "eventhouse_schema", f"missing required fields: {', '.join(missing_fields)}")
        if not terse:
            print(f"Error: Missing required fields in payload: {', '.join(missing_fields)}", file=sys.stderr)
        return False

    # Table-specific validation
    missing_table_fields = _missing_table_fields(payload, table_name)
    if missing_table_fields:
        message = _table_field_error(missing_table_fields, table_name)
        terse_print(terse, "ERROR", "eventhouse_schema", message)
        if not terse:
            print(f"Error: {message}", file=sys.stderr)
        return False

    return True


@dataclass(frozen=True)
class FlushResult:
    """What a flush actually did.

    ``ok`` is False for a flush that did not deliver, which is the whole
    point of this task: the placeholder returned True for a send that never
    happened, so every caller -- including the handler that would have
    warned -- was told it worked.
    """

    ok: bool
    sent: int
    error: str | None = None


class EventhouseSink:
    """Collects telemetry for one run and ingests it in as few calls as possible.

    A run-scoped batch rather than a send per artifact: `_send_telemetry` is
    called from `_run_one_artifact`, so ingesting inline would pay
    connection setup once per artifact and open a queued-ingest client N
    times for one logical run.

    Nothing is imported, authenticated, or connected until `flush` has
    something to deliver.
    """

    def __init__(self, config, env_file: Path | str | None = None):
        self.config = config
        self.env_file = env_file
        self._batches: dict[str, list[dict]] = {}
        # Tables whose destination this run has already confirmed, so a
        # second flush does not re-check what it just built.
        self._ensured: set[str] = set()

    def add(self, table: str, payload: dict) -> None:
        """Queue one record for ``table``."""
        self._batches.setdefault(table, []).append(payload)

    @property
    def pending(self) -> int:
        """How many records are waiting to be delivered."""
        return sum(len(rows) for rows in self._batches.values())

    def flush(self) -> FlushResult:
        """Deliver everything queued, and report what happened.

        Never raises. Telemetry is non-blocking by contract, and a raise
        here would let a diagnostic feature fail a build.
        """
        batches, self._batches = self._batches, {}
        queued = sum(len(rows) for rows in batches.values())
        if not queued:
            return FlushResult(ok=True, sent=0)
        if not self.config.configured:
            return FlushResult(
                ok=False,
                sent=0,
                error=(
                    "telemetry has records to send but no Eventhouse destination is "
                    "configured; set `telemetry.eventhouse` in fab-test.yml"
                ),
            )
        try:
            # Ensured before anything is sent, and never after. Queued ingest
            # accepts a batch aimed at a table that does not exist -- the
            # request is valid and the failure happens later, in a pipeline
            # nobody is watching -- so a send that cannot land would
            # otherwise be reported as delivered.
            for table in batches:
                self._ensure_destination(table)
            for table, rows in batches.items():
                self._ingest(table, rows)
        except Exception as exc:  # noqa: BLE001 - boundary: telemetry never fails a run
            return FlushResult(ok=False, sent=0, error=describe_ingest_failure(exc))
        return FlushResult(ok=True, sent=queued)

    def _ensure_destination(self, table: str) -> None:
        """Create ``table`` and its ingestion mapping if either is missing.

        Checked once per table per flush: this is a management round trip
        against the query endpoint, and paying it per record would repeat
        the mistake batching was introduced to fix.

        `fab-test` creates tables, never databases or Eventhouses. A missing
        database is reported rather than built, and that boundary is visible
        in the message.
        """
        if table in self._ensured:
            return
        cluster = self._cluster()
        try:
            existing = cluster.show_tables(self.config.database)
        except Exception as exc:
            raise DestinationError(_unreachable_message(self.config.database, exc)) from exc

        if table not in existing:
            self._create(cluster.create_table, table, "table")
        elif PAYLOAD_MAPPING in cluster.show_mappings(self.config.database, table):
            # Both halves present: nothing to build.
            self._ensured.add(table)
            return

        # A table this run just created has no mapping either, and a
        # pre-existing one without a mapping ingests *successfully* into
        # empty rows -- the quietest failure of the three.
        self._create(cluster.create_mapping, table, "ingestion mapping")
        self._ensured.add(table)

    def _create(self, action, table: str, what: str) -> None:
        """Run one creation step, or explain why the destination is unusable."""
        try:
            if what == "table":
                action(self.config.database, table)
            else:
                action(self.config.database, table, PAYLOAD_MAPPING)
        except Exception as exc:
            raise DestinationError(
                f"telemetry {what} is missing and could not be created: "
                f"{table} in database {self.config.database} ({exc}). "
                f"Either grant the credential permission to create tables, or run:\n"
                f"{create_statements(table)}"
            ) from exc

    def _ingest(self, table: str, rows: list[dict]) -> None:
        """Ingest one table's rows. The seam tests replace with a stand-in."""
        deps = self._dependencies()
        client = self._client(deps)
        properties = deps.ingestion_properties(
            database=self.config.database,
            table=table,
            data_format=deps.data_format.JSON,
            # Without this the service maps by column name, and a table whose
            # only column is `Data` would silently keep nothing. The mapping
            # puts the whole payload object in that one column, which is what
            # makes the wire schema-independent: a new payload field is a new
            # key inside `Data`, not a table alteration.
            ingestion_mapping_reference=PAYLOAD_MAPPING,
        )
        client.ingest_from_stream(_json_lines(rows), ingestion_properties=properties)

    def _cluster(self) -> Any:
        """Return the cluster's management endpoint. A seam for tests.

        Built against the *query* URI, not the ingest one: management
        commands are refused by the ingest endpoint.
        """
        return _ClusterAdmin(_query_uri(self.config.uri), self._credential())

    def _dependencies(self) -> IngestDependencies:
        """Load the Kusto symbols. A seam, so a test need not install the SDK."""
        return load_ingest_dependencies()

    def _credential(self) -> Any:
        """Resolve the ingest credential. A seam, so a test need not authenticate."""
        return build_ingest_credential(self.env_file)

    def _client(self, deps: IngestDependencies):
        """Build the queued-ingest client, once per flush that needs one."""
        # The ingest endpoint is the cluster URI with an `ingest-` prefix on
        # the host; Kusto rejects a queued ingest aimed at the query endpoint.
        kcsb = deps.connection_string_builder.with_azure_token_credential(
            _ingest_uri(self.config.uri), self._credential()
        )
        return deps.ingest_client(kcsb)


class _ClusterAdmin:
    """The cluster's management endpoint: inspect and create telemetry tables.

    Thin on purpose. Everything it does is a `.show` or a `.create`, and the
    decisions about *when* belong to `EventhouseSink`, which is what makes
    them testable without a cluster.
    """

    def __init__(self, query_uri: str, credential: Any):
        from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

        self._client = KustoClient(
            KustoConnectionStringBuilder.with_azure_token_credential(query_uri, credential)
        )

    def show_tables(self, database: str) -> list[str]:
        """Return the table names in ``database``."""
        response = self._client.execute_mgmt(database, ".show tables")
        return [row["TableName"] for row in response.primary_results[0]]

    def show_mappings(self, database: str, table: str) -> list[str]:
        """Return the JSON ingestion mapping names defined on ``table``."""
        response = self._client.execute_mgmt(
            database, f".show table {table} ingestion json mappings"
        )
        return [row["Name"] for row in response.primary_results[0]]

    def create_table(self, database: str, table: str) -> None:
        """Create ``table`` with the single dynamic column, if absent."""
        self._client.execute_mgmt(database, f".create-merge table {table} (Data: dynamic)")

    def create_mapping(self, database: str, table: str, mapping: str) -> None:
        """Create or replace ``table``'s payload ingestion mapping."""
        self._client.execute_mgmt(
            database,
            f".create-or-alter table {table} ingestion json mapping "
            f"'{mapping}' '{_MAPPING_BODY}'",
        )


def _query_uri(uri: str) -> str:
    """Return the query endpoint for a cluster URI.

    The inverse of `_ingest_uri`: a caller may configure either form, and
    management commands are refused by the ingest endpoint.
    """
    scheme, separator, rest = uri.partition("://")
    if not separator:
        return uri
    return f"{scheme}://{rest[len('ingest-'):]}" if rest.startswith("ingest-") else uri


def _ingest_uri(query_uri: str) -> str:
    """Return the ingest endpoint for a cluster's query URI."""
    scheme, _, rest = query_uri.partition("://")
    if not rest:
        return query_uri
    if rest.startswith("ingest-"):
        return query_uri
    return f"{scheme}://ingest-{rest}"


def _json_lines(rows: list[dict]):
    """Return the rows as a newline-delimited JSON stream for ingest."""
    import io

    body = "\n".join(json.dumps(row, default=str) for row in rows)
    return io.BytesIO(body.encode("utf-8"))


def publish_to_eventhouse(table_name: str, payload: dict, terse: bool = False) -> bool:
    """Publish one telemetry payload immediately.

    The single-record path, used by this module's own CLI. `fab-test`
    batches instead -- see `EventhouseSink`.
    """
    from ._config import merged_file_config
    from ._metadata import default_repo_root
    from ._telemetry import resolve_eventhouse_config

    repo_root = default_repo_root()
    file_config, _ = merged_file_config(repo_root, repo_root / "pyproject.toml")
    sink = EventhouseSink(resolve_eventhouse_config(file_config))
    sink.add(table_name, payload)
    result = sink.flush()
    if not result.ok:
        terse_print(terse, "ERROR", "eventhouse_logger", result.error or "ingest failed")
        if not terse:
            print(f"Error: telemetry was not delivered: {result.error}", file=sys.stderr)
        return False
    terse_print(terse, "OK", "eventhouse_logger", f"ingested 1 record into {table_name}")
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Publish CI/CD telemetry to Fabric Eventhouse",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--table",
        required=True,
        choices=VALID_TABLES,
        help="Target Eventhouse table name"
    )

    parser.add_argument(
        "--payload",
        required=True,
        help="Path to telemetry payload JSON file"
    )
    parser.add_argument(
        "--terse",
        action="store_true",
        help=(
            "Emit machine-readable one-line summaries (OK/SKIP prefix). "
            "Suppresses decorative output; retains actionable context for agents."
        ),
    )

    args = parser.parse_args()
    terse = args.terse

    # Check feature flag
    if not validate_feature_flag(terse):
        if not terse:
            print("\n✅ Exiting gracefully - telemetry is optional per Constraint C9")
        sys.exit(0)

    # Validate table name
    if not validate_table_name(args.table, terse):
        sys.exit(1)

    # Load payload
    if not terse:
        print(f"\n📂 Loading payload from: {args.payload}")
    payload_path = Path(args.payload)
    payload = load_payload(payload_path, terse)

    # Validate payload schema
    if not terse:
        print(f"\n🔍 Validating payload schema for table: {args.table}")
    if not validate_payload_schema(payload, args.table, terse):
        sys.exit(1)

    if not terse:
        print("✅ Payload schema is valid")

    # Publish to Eventhouse
    if not terse:
        print("\n🚀 Publishing telemetry to Eventhouse...")
    success = publish_to_eventhouse(args.table, payload, terse)

    if success:
        terse_print(
            terse, "OK", "eventhouse_logger",
            f"telemetry published to {args.table} for {payload.get('artifact_name', 'N/A')}",
        )
        if not terse:
            print("\n✅ Telemetry published successfully")
        sys.exit(0)
    else:
        # Per Constraint C9, telemetry failures should not block workflows
        terse_print(
            terse, "WARN", "eventhouse_logger",
            f"telemetry publishing failed for {args.table}; continuing per Constraint C9",
        )
        if not terse:
            print("\n⚠️  Telemetry publishing failed, but continuing gracefully", file=sys.stderr)
            print("   Per Constraint C9: Telemetry is optional and never mandatory")
        sys.exit(0)  # Exit with success despite failure


if __name__ == "__main__":
    main()
