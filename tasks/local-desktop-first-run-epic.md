# Local Desktop First Run Epic

**Status**: 🚧 IN-PROGRESS
**Goal**: A Power BI developer with a `.pbip` open in Desktop gets real analyzer results in one command, with no workspace, service principal, or CI.

## Overview
The fastest way to adopt `fab-test` should be the way most Power BI work already happens: a `.pbip` open in Power BI Desktop on a laptop. Today the on-ramp assumes the opposite — artifacts must live under `.fabric/artifacts`, report validation needs a deployed report plus service-principal credentials for Playwright, and `pql-test` requires the user to already know that Desktop must be open and connected over local XMLA. That is a deployed-environment on-ramp bolted onto a local-first tool, and it costs a first-time user an afternoon before they see a single finding. This epic makes the local Desktop path the default entry point while producing the exact same envelopes, exit codes, and result layout as CI, so moving to a pipeline later changes nothing about the contract.

Depends on the run manifest and `doctor` from the CLI Agent Ergonomics epic. Tasks are ordered so each builds on the previous.

---

## 1. Discover `.pbip` Projects ✅

Find Power BI projects wherever they live instead of requiring the `.fabric/artifacts` layout.

**Requirements**:
- Given a repository with `*.pbip` files outside `.fabric/artifacts`, then discovery returns each project with its paired `.SemanticModel` and `.Report` folders.
- Given a `.pbip` whose paired folder is missing, then the project is reported as incomplete rather than silently skipped.
- Given a directory with no projects, then discovery returns an empty list without raising.

**Files**: new `_pbip_discovery.py`
**Tests**: `pytest tests/test_pbip_discovery.py`

---

## 2. Wire Discovery Into Artifact Resolution ✅

Make the CLI use the new discovery without breaking the existing layout.

**Requirements**:
- Given both `.fabric/artifacts` and loose `.pbip` projects exist, then both are discovered and each result reports its source path.
- Given `--artifact-dir DIR`, then discovery is restricted to that directory exactly as today.
- Given `--dry-run`, then discovered projects are listed with the analyzers that apply to each.
- Given nothing is discovered, then the message names the directories searched rather than only reporting zero artifacts.

**Files**: `fab_test_registry.py` (`discover_artifacts`), `fab_test.py`
**Tests**: `pytest -m fab_test tests/test_fab_test.py -k discover`

---

## 3. Detect Running Desktop Instances ✅

Find Power BI Desktop and its local XMLA endpoint so the user does not have to.

**Scope decision (2026-08-19)**: implemented via `msmdsrv.port.txt` (confirmed, stable mechanism) with no Desktop Bridge CLI integration — single-instance only for now. Correlating a specific port to a specific open file when several Desktop windows are open needs a reliable per-window signal the raw port file doesn't provide; the Bridge CLI (`@microsoft/powerbi-desktop-bridge-cli`, preview) likely provides it via `status`, but its exact output schema couldn't be verified without a live Desktop session, so it's deferred rather than guessed. This also means task 6 (bridge detection) and task 7 (render capture, which needs the bridge's `screenshot`/`screenshot-all`) need to be revisited once the schema is confirmed or a live session is available to verify against.

**Requirements**:
- Given Power BI Desktop is running, then detection returns each instance with its local XMLA port; the open file path is resolved when exactly one instance is running.
- Given more than one instance is running, then every port is still reported but no open file path is guessed.
- Given no instance is running, then detection returns an empty list without raising.
- Given detection runs on a non-Windows platform, then it returns empty rather than failing.

**Files**: new `_desktop.py`
**Tests**: `pytest tests/test_desktop_detection.py`

---

## 4. Match an Instance to an Artifact ✅

Never guess which model is under test.

**Requirements**:
- Given one instance whose open file matches the artifact, then that instance is selected.
- Given multiple matching instances, then the run stops and reports the candidates rather than picking one.
- Given no instance matches, then the message names the file to open and exits `127`.

**Files**: `_desktop.py`, `fab_test_registry.py`
**Tests**: `pytest tests/test_desktop_detection.py -k match`

---

## 5. Bind DAX Tests to the Detected Instance ✅

Make the local `pql-test` path self-configuring instead of tribal knowledge in a docs line.

**Requirements**:
- Given a bound Desktop instance, then `pql-test` is invoked against its local XMLA endpoint with no workspace ID required.
- Given `--workspace-id` is supplied, then the remote XMLA path is used and Desktop detection is skipped entirely.
- Given a bound instance, then the resolved instance and model name appear in the result envelope.

**Files**: `fab_test_registry.py` (`build_pql_test_command`), `invoke_pql_test.py`
**Tests**: `pytest -m pql_test`

---

## 6. Detect the Desktop Bridge CLI ⏸️ DEFERRED

Report render-check availability as a first-class readiness fact.

**Deferral reason (2026-08-19)**: this and tasks 7-8 depend on `@microsoft/powerbi-desktop-bridge-cli` (the "Desktop bridge CLI"), a Microsoft preview tool (docs dated July 2026) whose `status`/`screenshot`/`screenshot-all` commands are exactly what these three tasks need. Its `--version`/presence check alone would be low-risk to build, but tasks 7-8 need its actual output schema (how a screenshot's bytes/path are returned), which couldn't be confirmed from the npm README (blocked) or any example output found during research, and there's no live Desktop session in this environment to verify against. Per user direction, all three are deferred as a block rather than guessing the schema. Revisit by either confirming the schema from a real installation, or from Microsoft's own docs if the preview stabilizes.

**Requirements**:
- Given the bridge CLI is on `PATH`, then its version is resolved and reported as available.
- Given it is absent, then report render checks are marked unavailable with an install hint and static PBIR analysis still runs.
- Given detection runs, then no Desktop window is opened as a side effect.

**Files**: `_desktop.py`
**Tests**: `pytest tests/test_desktop_detection.py -k bridge`

---

## 7. Capture Report Renders as Findings ⏸️ DEFERRED

Give report authors value on day one without a service principal.

**Deferral reason**: depends on task 6 — see above.

**Requirements**:
- Given a report open in Desktop, then each page is captured and any page that fails to render becomes an error-level finding.
- Given findings are produced, then the envelope schema, `status` values, and result directory layout match the Playwright analyzer's output.
- Given credentials and a workspace are supplied instead, then the existing service-resolved Playwright path runs unchanged.

**Files**: new `invoke_desktop_report.py`, `_analyzer_envelope.py`
**Tests**: `pytest -m playwright tests/test_desktop_report.py`

---

## 8. Store Screenshots With Results ⏸️ DEFERRED

Make the visual evidence findable from the envelope alone.

**Deferral reason**: depends on task 6 — see above.

**Requirements**:
- Given captured renders, then screenshots are written under the analyzer result directory for that artifact.
- Given an envelope is written, then each screenshot is referenced by relative path.
- Given a repeat run, then prior screenshots for the same artifact are replaced rather than accumulated.

**Files**: `invoke_desktop_report.py`
**Tests**: `pytest -m playwright tests/test_desktop_report.py -k screenshot`

---

## 9. Add `fab-test local` ✅

One bundled command that runs every check possible without cloud access.

**Requirements**:
- Given `fab-test local`, then Power Query lint, Best Practice Analyzer, PBIR Inspector, and Desktop-bound DAX tests run against every discovered project.
- Given an analyzer's prerequisite is absent, then it is reported as skipped with a remediation hint and does not fail the run.
- Given every runnable analyzer passes, then the exit code is `0`; given any produces error-level findings, then it is `1`.
- Given `fab-test local`, then no service-principal credential, workspace ID, or Fabric network call is required.

**Files**: `fab_test.py`, `fab_test_registry.py`
**Tests**: `pytest -m fab_test tests/test_local_command.py`

---

## 10. Add `fab-test local --dry-run` ✅

Let a user see the plan before spending time on it.

**Requirements**:
- Given `--dry-run`, then the output lists which analyzers would run, against which projects, and which would be skipped with the reason.
- Given `--format json`, then the plan is emitted as a single JSON document.
- Given `--dry-run`, then no subprocess is spawned and no Desktop interaction occurs.

**Files**: `fab_test.py`
**Tests**: `pytest -m fab_test tests/test_local_command.py -k dry_run`

---

## 11. Add `fab-test doctor --local` ✅

Tell a new user exactly what is missing before they run anything.

**Requirements**:
- Given `fab-test doctor --local`, then Python version, Desktop running, bridge CLI, Tabular Editor, and PBIR Inspector are each reported.
- Given a prerequisite is missing, then the output includes the exact command or download that resolves it.
- Given all are met, then the output states which `fab-test local` analyzers will run.
- Given `--format json`, then the diagnostics are emitted as a single JSON document.

**Files**: `fab_test.py`, `_desktop.py`
**Tests**: `pytest -m fab_test tests/test_doctor.py -k local`

---

## 12. Keep the Contract Identical Local and in CI

Guarantee that graduating from a laptop to a pipeline requires no rework.

**Requirements**:
- Given the same artifact analyzed locally and in CI, then the envelope schema, `status` values, and result layout are identical.
- Given a local run, then the run manifest records `origin: local`.
- Given a local-only analyzer runs in CI where its prerequisite is absent, then it is skipped with a clear reason rather than failing the pipeline.

**Files**: `_run_manifest.py`, `_analyzer_envelope.py`
**Tests**: `pytest -m fab_test tests/test_run_manifest.py -k origin`

---

## 13. Scaffold the Local Config

Make the first local config something the CLI writes.

**Requirements**:
- Given `fab-test init --local`, then a minimal config targeting the discovered `.pbip` projects is scaffolded.
- Given a config already exists, then it is reported and left untouched with exit `0`.
- Given the scaffolded config, then `fab-test local` runs successfully against it with no further edits.

**Files**: `fab_test.py`
**Tests**: `pytest -m fab_test tests/test_local_command.py -k init`

---

## 14. Document for All Three Callers

Cover the agent, the human, and the pipeline together, per the documentation constraint in [vision.md](../vision.md).

**Requirements**:
- Given `docs/QUICKSTART-LOCAL.md`, then a new user goes from install to first findings in four commands or fewer, and it states plainly which checks need no cloud access.
- Given the README, then the local Desktop workflow appears before the CI and service-principal material.
- Given the `fab-test` skill, then it documents `fab-test local`, Desktop binding, and which analyzers skip without Desktop.
- Given a pipeline author, then a workflow snippet shows the CI equivalent of the local command and which local-only checks are expected to skip there.

**Files**: `docs/QUICKSTART-LOCAL.md`, `README.md`, `.github/skills/fab-test/SKILL.md`
**Tests**: `pytest` (full suite before commit)
