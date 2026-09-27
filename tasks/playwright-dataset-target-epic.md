# Playwright Dataset Target Epic

**Status**: 🔄 IN-PROGRESS
**Goal**: Let `fab-test playwright --dataset-id` target the reports built on one dataset instead of every local report

## Overview

A developer who changed one semantic model wants to render the reports built on it, and nothing else. Today `fab-test playwright --dataset-id X --dataset-workspace-id Y` with no `--artifact` silently falls into batch discovery: every local `*.Report`/`.rdl` under `--artifact-dir` runs against the configured environment, each one force-rebound to dataset X. That wastes the run and reports failures for reports that were never bound to X. Naming a dataset without naming a report should mean "the reports on this dataset".

---

## Dataset-targeted Playwright run

Resolve the dependent reports of the named dataset live and run Playwright on only those.

**Requirements**:
- Given `--dataset-id` and no `--artifact`, target, or `--impact-manifest`, should run Playwright once against the dataset's dependent reports rather than every locally discovered report
- Given `--dataset-id` and `--dataset-workspace-id`, should look the dataset's dependent reports up in the dataset's workspace
- Given `--dataset-id` and no dataset workspace, should look the dependent reports up in the report workspace (`--workspace-id` / `FABRIC_WORKSPACE_ID`)
- Given `--dataset-id` with no dataset workspace and no report workspace, should refuse before any network call, naming both flags
- Given a dataset with no dependent reports in scope, should exit 0 with a notice that nothing was found
- Given a dependent report rendered in dataset mode, should embed it against the named dataset and dataset workspace
- Given `--dataset-id` together with `--artifact`, should keep today's behavior: override that one report's dataset binding

## Dataset workspace given without a dataset to scope it

Live-verifying the dataset-targeted run above (`--dataset-workspace-id c4698d28... --dataset-id 5bf5a7e1...`,
which correctly resolved and ran only the dependent report) surfaced a sibling bug: `--dataset-workspace-id`
*alone*, with no `--dataset-id` and no `--artifact`, forces every locally discovered report onto that
workspace's dataset instead of refusing -- `_dataset_override_for_command` applies an explicit
`--dataset-workspace-id` unconditionally, to every artifact discovery finds, whether or not that artifact
has anything to do with the named workspace. A caller who names a dataset's workspace but not the dataset
itself, and names no report either, gets a full batch run silently mistargeted at a workspace their service
principal commonly has no access to, instead of a fast, clear refusal.

**Requirements**:
- Given `--dataset-workspace-id` alone -- no `--dataset-id`, `--artifact`, target, or `--impact-manifest` --
  should refuse before any artifact runs, naming both flags
- Given `--dataset-workspace-id` with `--dataset-id` (dataset-targeted mode) or `--artifact` (single-report
  override) or `--impact-manifest`, should keep today's behavior unchanged

## Every dataset in a workspace, and --artifact scoped by workspace instead of refused

Live use surfaced two more gaps in the same shape as the two tasks above, both reported directly against a
real workspace: `--dataset-workspace-id` alone refuses rather than doing anything useful, and `--artifact
NAME` with `--dataset-workspace-id` but no `--workspace-id`/`--env` falls into local discovery and reports
"no *.Report artifacts found" -- because nothing before this task ever read `--dataset-workspace-id` as a
workspace to resolve `--artifact` against; it is applied only as the *dataset's* workspace override
(`_dataset_override_for_command`), never as the report's own workspace. This task supersedes the refusal
requirement above: `--dataset-workspace-id` alone stops being an error and becomes real behavior.

**Requirements**:
- Given `--dataset-workspace-id` alone -- no `--dataset-id`, `--artifact`, target, or `--impact-manifest` --
  should list every semantic model in that workspace via the service principal and run Playwright once per
  model against its own dependent reports (the same dependent-report resolution `--dataset-id` mode already
  uses), rather than refusing
- Given `--dataset-workspace-id` and `--artifact NAME` where `NAME` resolves to a `Report`/`PaginatedReport`
  item in that workspace, should refine to that one report -- the workspace named by `--dataset-workspace-id`
  now also resolves a bare `--artifact`, closing the "no *.Report artifacts found" gap for a caller who has
  no other way to name the report's workspace
- Given `--dataset-workspace-id` and `--artifact NAME` where `NAME` instead resolves to a `SemanticModel` in
  that workspace, should run the dependent reports of that one named dataset (the single-dataset case of the
  bullet above, named by display name instead of `--dataset-id`)
- Given `--env` in place of (or alongside) `--dataset-workspace-id`, should resolve the workspace from
  `environments.yml` the same way every other workspace-consuming flag already does, so `--env` alone is
  enough to drive both the "every dataset" and the "--artifact scoped by workspace" cases above
- Given a workspace with no semantic models at all, should exit 0 with a notice that nothing was found,
  matching the existing empty-dependents behavior for a single named dataset
- Given the reports discovered this way, should cover RDL/paginated reports exactly as `--dataset-id` mode
  already does -- a semantic model's dependents are not only interactive `Report` items

**Done 2026-09-26.** `dataset_workspace_only_requested`/`resolve_dataset_workspace_targets` and
`dataset_workspace_artifact_requested`/`resolve_dataset_workspace_artifact` in
`_playwright_dataset_target.py`, wired into `_discover_for`'s `_playwright_service_resolved_target`
and its local-discovery-miss fallback. `--env` fills in via `_resolve_target_workspace`, scoped to these
two modes only -- the literal `--dataset-workspace-id` flag still gates the trigger, so a plain batch
run with nothing local is never reinterpreted as "every dataset in this workspace." Each report's own
dataset ID is carried per-stem (`REPORT_DATASETS_ATTR`), since one "every dataset" run can span several
datasets where the single-dataset mode only ever needed one shared ID. 23 tests in
`tests/test_playwright_dataset_target.py`. Live-verified against a real workspace: `--dataset-workspace-id`
alone found 2 semantic models and ran both dependents; `--artifact "Not Working Visuals"` (not a dataset)
refined to that one report -- the exact scenario originally reported; `--artifact "SampleModel-PQLAssert"`
(also a dataset name) ran that one dataset's dependent instead. One observation, not a regression: the
live workspace's "Not Working Visuals" report was not returned as any dataset's dependent by
`get_dependent_reports`, so "every dataset" mode didn't include it even though `--artifact` resolves it
fine directly -- pre-existing behavior of the already-shipped dependents lookup, not something this task
changed.
