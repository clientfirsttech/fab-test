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
