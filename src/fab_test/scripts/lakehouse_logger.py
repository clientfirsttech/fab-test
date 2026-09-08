"""Lakehouse Telemetry Logger (Lakehouse Telemetry Sink §3).

Publishes analyzer telemetry to a Fabric Lakehouse via OneLake's ADLS Gen2
endpoint, as JSONL files under
``<lakehouse>.Lakehouse/Files/fab-test-telemetry/<table>/<run_id>.jsonl``.
Mirrors `eventhouse_logger.py`'s `EventhouseSink` shape: a run-scoped batch,
nothing imported/authenticated until `flush` has something to send, and a
flush that never raises into the analyzer run -- see the Lakehouse Telemetry
Sink epic.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._telemetry import TelemetryDependencyError

TELEMETRY_LAKEHOUSE_EXTRA_HINT = "pip install 'fab-test[telemetry-lakehouse]'"

ONELAKE_ENDPOINT = "https://onelake.dfs.fabric.microsoft.com"

# What the OneLake data-plane says when the credential is valid and the
# grant is not. Mirrors `eventhouse_logger._AUTHORIZATION_MARKERS`; kept
# local rather than shared since only three literal strings are involved.
_AUTHORIZATION_MARKERS = ("forbidden", "unauthorized", "not authorized", "403")

_LAKEHOUSE_PERMISSION_HINT = (
    "The credential authenticated but is not permitted to write to this Lakehouse. "
    "Grant it a role (e.g. Contributor) on the workspace, or share the Lakehouse item "
    "directly, then retry."
)


@dataclass(frozen=True)
class LakehouseDependencies:
    """The OneLake symbol ingest needs, loaded on demand."""

    service_client_cls: Any


def load_lakehouse_dependencies() -> LakehouseDependencies:
    """Import the OneLake (ADLS Gen2) client, or say how to install it.

    Imported here rather than at module scope so a run that never configures
    a Lakehouse destination never pays for the SDK -- the same deferral
    `eventhouse_logger.load_ingest_dependencies` already uses.
    """
    try:
        from azure.storage.filedatalake import DataLakeServiceClient
    except ImportError as exc:
        raise TelemetryDependencyError(
            "telemetry is configured but the OneLake client is not installed. "
            f"Install it with: {TELEMETRY_LAKEHOUSE_EXTRA_HINT}"
        ) from exc
    return LakehouseDependencies(service_client_cls=DataLakeServiceClient)


def build_lakehouse_credential(env_file: Path | str | None = None) -> Any:
    """Return an Azure credential for OneLake writes. See `_credentials.build_azure_credential`."""
    from ._credentials import build_azure_credential

    return build_azure_credential(env_file)


def describe_lakehouse_failure(exc: Exception) -> str:
    """Return a reportable reason for a Lakehouse write failure.

    Redacted before it is returned, matching `eventhouse_logger`'s failure
    reporting: the secrets constraint puts telemetry on the same footing as
    stdout and the run manifest.
    """
    from ._credentials import redact_secrets

    message = redact_secrets(f"{exc}")
    if any(marker in message.lower() for marker in _AUTHORIZATION_MARKERS):
        return f"{message} -- {_LAKEHOUSE_PERMISSION_HINT}"
    return message


@dataclass(frozen=True)
class FlushResult:
    """What a flush actually did. Mirrors `eventhouse_logger.FlushResult`."""

    ok: bool
    sent: int
    error: str | None = None


class LakehouseSink:
    """Collects telemetry for one run and writes it to OneLake in as few calls as possible.

    A run-scoped batch rather than a write per artifact, mirroring
    `EventhouseSink`. Nothing is imported, authenticated, or connected until
    `flush` has something to deliver.
    """

    def __init__(
        self,
        config,
        env_file: Path | str | None = None,
        run_id: str | None = None,
    ):
        self.config = config
        self.env_file = env_file
        # One id per sink (per run), not per table: every table's file for
        # this run should be findable by the same run id.
        self._run_id = run_id or uuid.uuid4().hex
        self._batches: dict[str, list[dict]] = {}

    def add(self, table: str, payload: dict) -> None:
        """Queue one record for ``table``."""
        self._batches.setdefault(table, []).append(payload)

    @property
    def pending(self) -> int:
        """How many records are waiting to be written."""
        return sum(len(rows) for rows in self._batches.values())

    def flush(self) -> FlushResult:
        """Write everything queued, and report what happened.

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
                    "telemetry has records to send but no Lakehouse destination is "
                    "configured; set `telemetry.lakehouse` in fab-test.yml"
                ),
            )
        try:
            for table, rows in batches.items():
                self._write(table, rows)
        except Exception as exc:  # noqa: BLE001 - boundary: telemetry never fails a run
            return FlushResult(ok=False, sent=0, error=describe_lakehouse_failure(exc))
        return FlushResult(ok=True, sent=queued)

    def _write(self, table: str, rows: list[dict]) -> None:
        """Write one table's rows as a single JSONL file. The seam tests replace with a stand-in.

        The directory is created before the file, rather than relying on
        implicit creation: a Lakehouse's `Files/fab-test-telemetry/<table>/`
        path does not exist before the first run that ships to it.
        """
        deps = self._dependencies()
        client = deps.service_client_cls(ONELAKE_ENDPOINT, credential=self._credential())
        filesystem = client.get_file_system_client(self.config.workspace)
        directory_path = f"{self.config.lakehouse}.Lakehouse/Files/fab-test-telemetry/{table}"
        directory = filesystem.get_directory_client(directory_path)
        directory.create_directory()
        file_client = directory.get_file_client(f"{self._run_id}.jsonl")
        file_client.upload_data(_json_lines_bytes(rows), overwrite=True)

    def _dependencies(self) -> LakehouseDependencies:
        """Load the OneLake symbols. A seam, so a test need not install the SDK."""
        return load_lakehouse_dependencies()

    def _credential(self) -> Any:
        """Resolve the write credential. A seam, so a test need not authenticate."""
        return build_lakehouse_credential(self.env_file)


def _json_lines_bytes(rows: list[dict]) -> bytes:
    """Return the rows as newline-delimited JSON bytes, ready to upload."""
    return "\n".join(json.dumps(row, default=str) for row in rows).encode("utf-8")
