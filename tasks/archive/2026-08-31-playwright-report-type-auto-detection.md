# Playwright Report Type Auto-Detection Epic

**Status**: ✅ COMPLETED — 3 of 3 tasks done
**Goal**: `fab-test playwright` determines whether a target is an interactive or paginated report itself, instead of requiring the caller to pre-declare `PLAYWRIGHT_REPORT_TYPE` for every invocation.

## Overview

`PLAYWRIGHT_REPORT_TYPE` is a single value applied to an entire invocation, which breaks down exactly where it matters most: a workspace with both interactive and paginated reports has no single correct value for a batch run with no `--artifact`, and paginated folders aren't even discoverable locally today (playwright's discovery glob is hardcoded to `*.Report`). A caller targeting one report by name with `--artifact` is also forced to already know and declare its type, something Fabric itself can answer. fab-test should resolve the type per artifact, not have the caller state it globally.

---

## Auto-detect report type when resolving via --artifact + --env

`resolve_report` currently requires `report_type` to be declared upfront ("report" or "paginated") rather than discovering it.

**Requirements**:
- Given `--artifact NAME --env ENV` with no `--report-type`/`PLAYWRIGHT_REPORT_TYPE` set, resolution should try Fabric item type `Report` first, then `PaginatedReport`, and resolve against whichever actually matches the name
- Given an explicit `--report-type`/`PLAYWRIGHT_REPORT_TYPE`, resolution should use it directly and skip auto-detection
- Given neither Fabric item type matches the name, resolution should fail with the existing "no match" message, not a confusing type-specific one

---

## Auto-detect report type in local/batch discovery

Local discovery for `playwright` only ever matches `.Report` folders, so a `.PaginatedReport` folder is invisible to it, and a batch run (no `--artifact`) has no way to validate a paginated report at all today.

**Requirements**:
- Given a repository with both `X.Report` and `Y.PaginatedReport` folders, `fab-test playwright` with no `--artifact` should discover and validate both
- Given a discovered `.PaginatedReport` folder, the per-artifact subprocess invocation for it should be told its type explicitly by the outer CLI (derived from the folder's own suffix), not left to guess or depend on ambient env state
- Given a discovered `.Report` folder, the per-artifact subprocess invocation should keep working exactly as before

---

## --report-type as an explicit override

**Requirements**:
- Given `--report-type paginated`/`report` on the CLI, it should override auto-detection entirely, mirroring `--dataset-id`'s override pattern
- Given static `.env`-only mode (no artifact name at all -- IDs supplied directly), `PLAYWRIGHT_REPORT_TYPE`/`--report-type` should stay required, since there is no name to auto-detect from
