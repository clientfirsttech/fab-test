# Lakehouse Telemetry Sink Epic

**Status**: ✅ COMPLETED (2026-09-10, 5/5 tasks)
**Goal**: Let fab-test ship telemetry to a Fabric Lakehouse (via the OneLake ADLS Gen2 SDK) as a second, independently-configurable destination alongside Eventhouse.

## Overview

Eventhouse telemetry already works end to end, but querying it means learning KQL — the team wants the same run data queryable from a Lakehouse (SQL endpoint, Direct Lake, Power BI) instead. OneLake exposes the same ADLS Gen2 endpoint `azure-storage-file-datalake` + `azure-identity` already speak for other Azure storage, so this reuses fab-test's existing credential resolution (`resolve_service_principal`/`DefaultAzureCredential`) rather than adding `azcopy` as a new bootstrapped binary with its own SAS/`azcopy login` auth flow. Eventhouse is untouched; Lakehouse is additive and optional — a user enables either, both, or neither.

---

## Lakehouse Config Resolution

Extend `_telemetry.py` with a `LakehouseConfig`/`resolve_lakehouse_config` mirroring `EventhouseConfig`/`resolve_eventhouse_config`, and generalize `TelemetryDecision` so enablement reflects either destination.

**Requirements**:
- Given only `telemetry.lakehouse` is configured (workspace + lakehouse name, via `LAKEHOUSE_WORKSPACE`/`LAKEHOUSE_NAME` env vars or `fab-test.yml`), should `--telemetry` enable and resolve it, with no Eventhouse address required.
- Given both Eventhouse and Lakehouse are configured, should the decision carry both resolved destinations independently.
- Given neither is configured, should `enabled` be `False` with no refusal — unconfigured is not an error.
- Given `--telemetry` is passed explicitly with neither destination configured, should refuse and name both ways to configure each destination.

---

## Config Schema & Init Scaffold

Allow a `telemetry.lakehouse` block in the config schema validator and `fab-test init`'s scaffold, matching the existing commented `telemetry.eventhouse` example.

**Requirements**:
- Given a `telemetry.lakehouse` block with `workspace`/`lakehouse` keys, should `validate_config` accept it.
- Given a typo inside the block, should the error name the full nested key path, matching the existing Eventhouse behavior.
- Given `fab-test init`, should the generated `fab-test.yml` include a commented `telemetry.lakehouse` example alongside the existing `telemetry.eventhouse` one.

---

## Lakehouse Sink

New `lakehouse_logger.py`: `LakehouseSink` (mirrors `EventhouseSink.add`/`.pending`/`.flush`) using `azure-storage-file-datalake`'s `DataLakeServiceClient` against OneLake, writing one JSONL file per table per run under `{lakehouse}.Lakehouse/Files/fab-test-telemetry/{table}/{run_id}.jsonl`. New optional extra `fab-test[telemetry-lakehouse]` in `pyproject.toml`.

**Requirements**:
- Given records queued for one or more tables, should `flush` write one JSONL file per table, batched rather than per-record.
- Given no service principal and no ambient `az login`, should fail non-blocking with a reportable error, same as Eventhouse today.
- Given the target Lakehouse's `Files/fab-test-telemetry/` path doesn't exist yet, should create it rather than erroring.
- Given the SDK is not installed, should raise the same `TelemetryDependencyError` shape Eventhouse uses, naming the install extra.

---

## Multi-Sink Wiring

`fab_test_telemetry.py`'s `_open_telemetry`/`_send_telemetry`/`_close_telemetry` fan out to whichever sinks are configured; `doctor` reports one readiness row per configured destination.

**Requirements**:
- Given both sinks are configured and one fails to deliver, should the other still deliver and the run report one warning per failed sink.
- Given only Lakehouse is configured, should `doctor` show a `telemetry-lakehouse` row and no `telemetry-eventhouse` row.
- Given `--telemetry --dry-run`, should the preview name both destinations when both are configured.

---

## Documentation

Update README, the fab-test skill's telemetry reference (SudoLang contract), QUICK-VALIDATION, and `docs/RELEASE.md`'s extras note, via the `document` skill.

**Requirements**:
- Given the new Lakehouse sink, should every documented telemetry example show both destinations as independent, optional configuration.
