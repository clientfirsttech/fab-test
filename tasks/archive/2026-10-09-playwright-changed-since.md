# Playwright Changed-Since Epic

**Status**: ✅ COMPLETED 2026-10-09 (1.9.0b10; quality gates passed: full suite, 89.22% coverage, ruff, ratchets; paginated follow-up live-verified)
**Goal**: Let `fab-test playwright --workspace WS --changed-since REF` validate only the deployed reports affected by what changed since a Git ref, and retire `playwright-impact` as a separate command

## Overview

Validating every deployed report after a one-model change wastes the run; validating only the affected reports needed two commands today. A pipeline ran `detect_changes.py`, then `fab-test playwright-impact` to turn its `changed-artifacts.json` into a manifest, then `fab-test playwright --impact-manifest`. `playwright-impact` never fit the mode rule either: it printed `mode=local` while always calling the service, took only a workspace GUID, and advertised a `TARGET` and per-artifact flags it ignored. Folding the impact step into `playwright` makes it one command that reads as what it is -- a service run over the deployed reports a change touches -- and leaves the change-detection and impact logic as internal modules.

---

## Changed-since Playwright run

**Requirements**:
- Given `--workspace WS --changed-since REF`, should validate only the deployed reports in WS built on a semantic model changed since REF, or themselves changed since REF
- Given a change made in the working tree and not yet committed, including a new artifact folder, should count it as changed
- Given `--changed-since` without `--workspace`, should refuse with exit 2 naming `--workspace`, before any network call
- Given a ref Git cannot resolve, or a directory that is not a Git repository, should refuse with exit 2 naming the ref
- Given no Fabric artifact changed since REF, should exit 0 saying nothing changed
- Given changes that affect no deployed report, should exit 0 saying no report is affected
- Given a changed report or semantic model that is not deployed in the workspace (a new one, not yet published), should skip it with a note naming it and still test the other affected reports
- Given the run, should print `mode=service workspace=WS` like every other workspace run

## Retire playwright-impact

**Requirements**:
- Given `fab-test playwright-impact`, should no longer be a command
- Given `fab-test playwright --help`, should not list `--impact-manifest`, while a pipeline that still passes it keeps working
- Given the fab-test skill and docs, should describe `--changed-since` and not `playwright-impact`

## Follow-up: Paginated Reports In Impact

**Requirements**:
- Given a changed `.PaginatedReport` or `.rdl`, should validate that deployed paginated report ✅

**Done 2026-10-08** (1.9.0b10). Three gaps, each with a test: `group_changes_by_artifact` now counts a loose `.rdl` as a `PaginatedReport` (artifact-map.json can't, since every suffix it declares is a folder); `_normalize_name` strips `.PaginatedReport` and `.rdl` so the changed name matches the deployed display name; `build_impact_manifest` resolves a `PaginatedReport` as paginated, and `ImpactEntry.report_type` carries that through to `REPORT_TYPES_ATTR` and to `--impact-manifest`'s loader, which previously rebuilt every entry as interactive.

Not covered, recorded for later: a paginated report reached as a *dependent* of a changed semantic model is still typed `report`, because `FabricRestClient.get_dependent_reports` hardcodes `"type": "Report"` instead of reading the Power BI `reportType`. That lookup is shared with `--dataset-id`/`--dataset-workspace-id`, so fixing it belongs with those callers, not here.

## Quality gates

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
