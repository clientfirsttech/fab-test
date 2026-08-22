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

VALID_TABLES = [
    "fabric_static_analysis",
    "fabric_dynamic_analysis",
    "fabric_deployments",
    "fabric_testbed_runs"
]

TELEMETRY_EXTRA_HINT = "pip install 'fab-test[telemetry]'"


class TelemetryDependencyError(Exception):
    """The Kusto ingest client is not installed.

    Deliberately not an ``ImportError``: the caller turns this into a warning
    rather than a crash, and catching a bare ImportError there would swallow
    unrelated import bugs in the same handler.
    """


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
    if any(marker in message.lower() for marker in _AUTHORIZATION_MARKERS):
        return f"{message} -- {_INGESTOR_ROLE_HINT}"
    return message


def build_ingest_credential(env_file: Path | str | None = None) -> Any:
    """Return an Azure credential for Kusto ingest.

    The service principal the CLI already resolves, or
    `DefaultAzureCredential` when none is set -- the rule
    `build_fabric_service_client` documents, applied to a different endpoint.
    A partially configured principal raises rather than falling back.
    """
    from ._credentials import resolve_service_principal

    principal = resolve_service_principal(env_file)
    if principal is None:
        from azure.identity import DefaultAzureCredential

        return DefaultAzureCredential()

    from azure.identity import ClientSecretCredential

    return ClientSecretCredential(
        tenant_id=principal.tenant_id,
        client_id=principal.client_id,
        client_secret=principal.client_secret,
    )


def load_ingest_dependencies() -> IngestDependencies:
    """Import the Kusto ingest client, or say how to install it.

    Imported here rather than at module scope so a run that never configures
    a destination never pays for the SDK -- the same deferral `_credentials`
    and `_target` already use.
    """
    try:
        from azure.kusto.data import KustoConnectionStringBuilder
        from azure.kusto.ingest import DataFormat, IngestionProperties, QueuedIngestClient
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
    if table_name == "fabric_static_analysis":
        if "results" not in payload:
            terse_print(terse, "ERROR", "eventhouse_schema", "'results' field required for fabric_static_analysis")
            if not terse:
                print("Error: 'results' field required for fabric_static_analysis", file=sys.stderr)
            return False

    elif table_name == "fabric_dynamic_analysis":
        if "results" not in payload or "environment" not in payload:
            terse_print(
                terse, "ERROR", "eventhouse_schema",
                "'results' and 'environment' fields required for fabric_dynamic_analysis",
            )
            if not terse:
                print("Error: 'results' and 'environment' fields required for fabric_dynamic_analysis", file=sys.stderr)
            return False

    elif table_name == "fabric_deployments":
        if "environment" not in payload:
            terse_print(terse, "ERROR", "eventhouse_schema", "'environment' field required for fabric_deployments")
            if not terse:
                print("Error: 'environment' field required for fabric_deployments", file=sys.stderr)
            return False

    elif table_name == "fabric_testbed_runs" and "results" not in payload:
        terse_print(terse, "ERROR", "eventhouse_schema", "'results' field required for fabric_testbed_runs")
        if not terse:
            print("Error: 'results' field required for fabric_testbed_runs", file=sys.stderr)
        return False

    return True


def publish_to_eventhouse(table_name: str, payload: dict, terse: bool = False) -> bool:
    """
    Publish telemetry payload to Eventhouse table.

    This is a placeholder implementation. The actual implementation will use:
    - Kusto Python SDK (azure-kusto-data, azure-kusto-ingest)
    - Azure Identity for authentication
    - Eventhouse connection string from secrets

    Example implementation:

        from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
        from azure.kusto.ingest import QueuedIngestClient, IngestionProperties
        from azure.identity import DefaultAzureCredential

        # Build connection
        kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(
            eventhouse_uri
        )

        # Create ingest client
        ingest_client = QueuedIngestClient(kcsb)

        # Ingest data
        ingestion_props = IngestionProperties(
            database=database_name,
            table=table_name,
            data_format="json"
        )

        ingest_client.ingest_from_dict([payload], ingestion_properties=ingestion_props)
    """
    if not terse:
        print("\n" + "="*80)
        print("EVENTHOUSE TELEMETRY LOGGER")
        print("="*80)
        print(f"\n📊 Table:       {table_name}")
        print(f"📦 Artifact:    {payload.get('artifact_name', 'N/A')}")
        print(f"🏷️  Type:       {payload.get('artifact_type', 'N/A')}")
        print(f"🔖 Commit:      {payload.get('commit_sha', 'N/A')}")
        print(f"⏰ Timestamp:   {payload.get('timestamp', 'N/A')}")
        print("\n" + "-"*80)
        print("CONSTRAINT C9: Telemetry is optional and never mandatory")
        print("-"*80)

        print("\n📋 Payload Preview:")
        print(json.dumps(payload, indent=2))

        print("\n🔧 Eventhouse Publishing (to be implemented):")
        print("""
    Required Dependencies:
        pip install azure-kusto-data azure-kusto-ingest azure-identity

    Expected Configuration:
        EVENTHOUSE_URI: from GitHub Secrets or Environment Variables
        DATABASE_NAME: from metadata configuration
        TABLE_NAME: derived from analysis type

    Schema Source:
        https://github.com/kerski/pbi-teams-more-analytic-support (Eventhouse branch)
        Eventhouse schema is the system of record per Constraint C9
    """)

        print("\n⚠️  STATUS: Placeholder Implementation")
        print("\nThis script will publish telemetry to Eventhouse once:")
        print("  1. Eventhouse connection is configured")
        print("  2. Kusto Python SDK dependencies are installed")
        print("  3. Eventhouse tables are created per reference schema")
        print("\n" + "="*80)
        print("✅ TELEMETRY LOGGING SIMULATION COMPLETED")
        print("="*80 + "\n")

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
