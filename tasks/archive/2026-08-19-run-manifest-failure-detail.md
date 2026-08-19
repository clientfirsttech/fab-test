# Run Manifest Failure Detail Epic

**Status**: ✅ COMPLETED (2026-08-19)
**Goal**: Make an aborted run's manifest entry self-explanatory without also needing stderr.

## Overview

Surfaced during the CLI Agent Ergonomics review: the epic's own requirement was that "a run aborts on a preflight failure, then the manifest is still written with the failure reason and the exit code," but `RunManifest.record_artifact` only ever stores a generic status enum (`preflight_failed`, `timeout`) — never the actual message. A pipeline or agent that uploads `run.json` as its only artifact currently has no way to learn *what* to fix without also capturing stderr from the same run.

---

## Record Failure Detail in Run Manifest

Add an optional detail field to each manifest artifact entry, populated with the actual failure text on the two abort paths that currently omit it.

**Requirements**:
- Given a preflight check fails for an artifact, should the manifest's artifact entry include the actual remediation message returned by the preflight check, not just the status string
- Given an artifact's subprocess call times out, should the manifest's artifact entry include the timeout duration that was exceeded
- Given an artifact completes normally (passed or failed with envelope), should its manifest entry's detail field be `null` rather than a placeholder string
