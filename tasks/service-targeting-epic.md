# Service Targeting Epic

**Status**: ✅ IMPLEMENTED (live verification against a real workspace pending; needs tenant credentials) — all 9 decisions recorded 2026-10-03.
**Known gaps**: live verification pending; service-run envelopes still live at `<analyzer>/<item-stem>/` (exports at `<analyzer>/<workspace>/<item>/export/`), so same-named items across workspaces share an envelope dir; `--interactive` tokens are not refreshed on long runs; a bare `--workspace` dry-run needs a token to enumerate.
**Goal**: Let `fab-test bpa`, `pbir`, `a11y`, `rdl`, `pql-test`, and `all` run against deployed models and reports in the Fabric service, with one standardized rule deciding repo scan vs. service testing and one surfaced mode per run.

## Overview

WHY: Users validating deployed content today must clone or export it first — the file-reading analyzers refuse a workspace target outright, while `pql-test`, `playwright`, and the planned `sqldb-test` each answer "repo or service?" their own way. This epic standardizes the answer the way Playwright and the T-TEST epic already did, so a human, a pipeline, and an agent can all tell at a glance whether a run is testing local files, a Desktop instance, or the service. The enabler already exists in-repo: `playwright_validation/service_client.py` implements Fabric's `getDefinition` for reports (PBIR) and semantic models (TMDL) — exactly the materialization the file-reading analyzers need.

**The one rule, stated once, true for every analyzer**:

> The TARGET (or its default) decides the mode. Flags and env vars supply defaults; they never silently change the mode.

Three modes, named identically in the banner, envelope, `--dry-run`, `explain`, `-q` line, and telemetry:

| Mode | Meaning | Denominator |
|------|---------|-------------|
| `repo` | Scan files under `--artifact-dir` | matching folders/files on disk |
| `desktop` | `local/NAME` — the copy open in Power BI Desktop | that one instance |
| `service` | `WS.Workspace/...` target, or `--workspace` with no target | deployed items in the workspace |

### Mode-resolution matrix

| Invocation | Mode | Behavior |
|------------|------|----------|
| `fab-test bpa` (bare) | repo | scan CWD — unchanged, backward compatible |
| `fab-test bpa Sales.SemanticModel` | repo | typed name narrows the scan — unchanged |
| `fab-test bpa ./src/Sales.SemanticModel` | repo | exact path — unchanged |
| `fab-test pql-test local/Sales` | desktop | unchanged; ambient `FABRIC_WORKSPACE_ID` never turns it remote |
| `fab-test bpa "Dev.Workspace/Sales.SemanticModel"` | **service** | new: export the definition via `getDefinition` (TMDL), run BPA on it |
| `fab-test pbir "Dev.Workspace/Sales.Report"` | **service** | new: export PBIR, run PBIR Inspector / a11y |
| `fab-test rdl "Dev.Workspace/Weekly.PaginatedReport"` | **service** | new: export the RDL definition, run the rule engine |
| `fab-test bpa --workspace Dev` (no TARGET) | **service** | pure service mode (decision 1): enumerate every deployed item of the analyzer's type in WS and test each — local folders are ignored; add `--artifact-dir` explicitly to keep the repository as the denominator |
| `fab-test all "Dev.Workspace/Sales.SemanticModel"` | service | each analyzer that can honor it runs; others skip with the existing "cannot honor target" message |
| `fab-test all --workspace Dev` | service | every service-capable analyzer runs against its deployed denominator (decision 4: no separate `fab-test service` subcommand) |
| `--workspace X` + target naming workspace Y | exit 2 | existing rule, kept |
| `local/NAME` + `--workspace` | exit 2 | contradictory modes stated explicitly |
| `workspace:` in `fab-test.yml` | default only | supplies the WS for service mode; never flips a bare invocation to service |

### Auth requirements matrix

One credential path (`build_azure_credential`, `auth status`, `auth login`) — no new auth subsystem.

| Mode | Credential | Resolution order | Failure |
|------|-----------|------------------|---------|
| repo | none | — | — |
| desktop | none (local Desktop bind) | — | exit `127` if no instance has the artifact |
| service — definition export (bpa/pbir/a11y/rdl) | Fabric REST scope `https://api.fabric.microsoft.com/.default`; identity needs read + Fabric API access to the item; workspace must support `getDefinition` | env SP (`FABRIC_TENANT_ID` + `FABRIC_CLIENT_ID`/`FABRIC_SERVICE_PRINCIPAL_ID` + secret) → `--env-file`/`.fab-test/.env`/`./.env` → `DefaultAzureCredential` → `--interactive` (decision 8) | exit `127` naming the exact env vars and `fab-test auth status`; a partial SP is `IncompleteServicePrincipalError`, never a silent fallback |
| service — pql-test | existing XMLA path | same chain | unchanged |
| service — playwright | same chain + the separate `PLAYWRIGHT_SERVICE_*` pair | unchanged | unchanged |

Rules carried forward: tokens/secrets never reach stdout, envelopes, the manifest, or telemetry; `doctor` never acquires a token (reports `unverified` and points at `auth status`); a `getDefinition` 404 on a non-PBIP workspace gets a named remediation ("item is not in enhanced/Git-integration format"), never a raw HTTP error.

**Decisions** (recorded 2026-10-03 at review):

1. ✅ `--workspace` alone always means **pure service mode** — deployed items are the denominator; local folders never mix in unless `--artifact-dir` is passed explicitly.
2. ✅ The "exporting a deployed item belongs to fabric-cicd-deployment" rule is retired for read-only, ephemeral test-input export; vision and the targeting reference are amended accordingly.
3. ✅ Exported definitions are **flag-controlled**: deleted after the run by default, kept under `fab-test-results/` with `--keep-export`. TMDL can carry connection strings, so kept exports go through the same redaction audit as envelopes.
4. ✅ No `fab-test service` subcommand — `fab-test all --workspace Dev` is the composite entry point (simplicity constraint).
5. ✅ Paginated reports in service mode feed **both** `rdl` (exported `.rdl` definition) and `playwright` (live render) under `all --workspace`.
6. ✅ `fab-test all --workspace Dev` **includes** `pql-test` against every model in the workspace.
7. ✅ An untyped service target (`Dev.Workspace/Sales`) resolves by the **analyzer's own type**, symmetric with repo-scan behavior.
8. ✅ `--interactive` browser sign-in is allowed for service mode — in-memory token only, never in CI — behind a **feature flag** (`interactive_auth: on|off` in `fab-test.yml`, default on; env `FAB_TEST_INTERACTIVE_AUTH=0` to disable) so it can be turned off fleet-wide.
9. ✅ Workspace enumeration over **50 artifacts** warns and stops before proceeding; `--all` forces it (PowerShell-CLI style confirm/force semantics). In CI or `--format json`, the warning is an exit-`2` refusal naming `--all`, never an interactive prompt.

---

## Mode Resolver

One shared function that decides the mode, so nine callers cannot each decide differently.

**Requirements**:
- Given (TARGET, `--workspace`, `FABRIC_WORKSPACE_ID`, `workspace:` config), should return `(mode, workspace, source)` where `mode ∈ {repo, desktop, service}` and `source ∈ {target, flag, env, config, default}`, per the matrix above.
- Given a bare invocation with an ambient `FABRIC_WORKSPACE_ID` or a `workspace:` config key, should stay `repo` — only an explicit `--workspace` flag or a workspace-qualified target selects service mode.
- Given `local/NAME` combined with `--workspace`, should exit `2` naming both.
- Given `--workspace X` and a target qualified with workspace Y, should exit `2` naming both (existing rule, now owned here).
- Given the resolver lives in `_target.py` (or a split module if the budget forces it), should be called by every analyzer subcommand, `all`, `list`, `explain`, and `doctor` — the blast-radius table in vision.md gains this surface and its callers.
- Given `--artifact STEM` (deprecated alias), should keep working unchanged in repo mode.

---

## Definition Export Seam

Materialize a deployed item as the on-disk shape the analyzers already read.

**Requirements**:
- Given a workspace item, should export via Fabric `getDefinition` — TMDL format for semantic models, the report's own stored format for reports, the `.rdl` payload for paginated reports — reusing/promoting `playwright_validation/service_client.py` rather than writing a second client.
- Given a deployed report stored as PBIR-Legacy (a single `report.json`), should skip it with a reason naming the format and the fix (convert it to PBIR), and the run should not exit `0` — never analyze it: Fabric refuses to convert a legacy report to PBIR on export (`Report_Report_FailedToExportReport`), and the `pbir` rules silently pass a legacy layout (11 errors on the PBIR copy of a report, 0 on its legacy export). Found on the first live run (2026-10-07).
- Given every report in the run is PBIR-Legacy, should exit `1` naming each one rather than report "no artifacts".
- Given a `getDefinition` operation that reports `Failed`, should exit with Fabric's error code and message in the remediation, never a bare HTTP status.
- Given an export that cannot be written to disk, should exit `1` naming the item and the path, never a traceback; given a path too long for the OS (PBIR's `definition/pages/<id>/visuals/<id>/visual.json` crosses Windows' 260-character limit under a deep `--output-dir`), should name a shorter `--output-dir` and Windows long-path support as the fix. Found on the first PBIR live run (2026-10-08).
- Given a service-mode export that resolves a credential, should name the credential source on stderr (`auth=service-principal (.fab-test/.env)`, `auth=ambient:DefaultAzureCredential`, `auth=interactive`) — never a secret; silent under `-q` and `--format json`.
- Given an export, should land under the run's output dir (`fab-test-results/<analyzer>/<workspace>/<item>/export/`), be cached per run so `all` exports each item once, and be deleted after the run unless `--keep-export` is passed (decision 3).
- Given `--keep-export`, should pass kept files through the same secret-redaction rules as envelopes (TMDL connection strings).
- Given a 404 (item not in enhanced/Git-integration format), a 403, or an unsupported item type, should exit with a named remediation, never a raw HTTP error.
- Given `--dry-run`, should list the items that would be exported without acquiring a token or calling the API.

---

## Wire File-Reading Analyzers To Service Mode

**Requirements**:
- Given `ANALYZER_SCOPES`, should add `"workspace"` to `bpa`, `pbir`, `a11y`, and `rdl`; the exported tree feeds the existing invoke path unchanged — the analyzers never learn about the service (facade, not fork).
- Given `fab-test bpa "Dev.Workspace/Sales.SemanticModel"`, should export, analyze, and report through the same envelope, exit codes, HTML report, and telemetry as a repo run, with `"mode": "service"` added to the envelope (additive).
- Given an untyped target `Dev.Workspace/Sales`, should resolve by the analyzer's type (decision 7); an ambiguous or missing name exits with the candidates or workspace items listed.
- Given `fab-test rdl` and `playwright` under `all --workspace`, should both pick up deployed paginated reports (decision 5).
- Given existing repo and desktop invocations, should behave byte-identically (backward-compat constraint); pinned by tests before any parser change.

---

## Standalone `--workspace` Enumeration

**Requirements**:
- Given `fab-test ANALYZER --workspace WS` with no TARGET, should enumerate every deployed item of the analyzer's type in WS and test each (decision 1), mirroring Playwright's standalone behavior and the T-TEST epic's decision 6.
- Given `fab-test all --workspace WS`, should compose per-analyzer denominators, including `pql-test` against every semantic model (decision 6); an analyzer with nothing to test is skipped, never a batch failure.
- Given more than 50 matched items, should warn with the count and stop; given `--all`, should proceed (decision 9). Given CI or `--format json`, the stop is an exit-`2` refusal naming `--all` — never a prompt.
- Given `--dry-run`, should list the enumerated items per analyzer without exporting or testing.

---

## Interactive Auth Feature Flag

**Requirements**:
- Given `--interactive` on a laptop, should sign in with `InteractiveBrowserCredential` in memory only — no device code, no persistent or encrypted token cache, nothing on disk (same contract as the T-TEST epic's decision 7).
- Given the feature flag off (`interactive_auth: off` in `fab-test.yml` or `FAB_TEST_INTERACTIVE_AUTH=0`), should exit `2` on `--interactive` naming the flag that disabled it (decision 8).
- Given CI (`CI`/`GITHUB_ACTIONS`/`TF_BUILD`), should never prompt regardless of the flag.
- Given a partially configured service principal, should fail with `IncompleteServicePrincipalError`'s remediation rather than fall back to interactive.

---

## Mode Surfacing

Make "what am I testing?" unmissable for all three callers.

**Requirements**:
- Given any run, should print one stderr line first: `mode=<repo|desktop|service> workspace=<name or —> source=<target|flag|env|config|default>`.
- Given the envelope, should carry additive `"mode"` and `"source"` fields; `-q` keeps its `QuietLine` shape, with service-run envelope paths under `fab-test-results/<analyzer>/<workspace>/<item>/`.
- Given `explain` and `--dry-run`, should show the resolved mode and, in service mode, the exact items to export/test.
- Given `fab-test list`, should update the Scopes column for the newly workspace-capable analyzers.
- Given `doctor`, should add a per-analyzer service-readiness reason (credential chain state, flag/env/config that fixes it) without acquiring a token; `doctor --local` unchanged.
- Given telemetry, should add the mode as a dimension; never the workspace connection details.

---

## Verify Live Against A Real Workspace

**Requirements**:
- Given a real workspace, should run each newly service-capable analyzer against a deployed model, report, and paginated report — typed target, untyped target, and standalone `--workspace` — through the installed console script, with a service principal and with `az login`.
- Given the same artifacts on disk, should confirm the service-mode findings match a repo-mode run over the exported definition.
- Given the blast-radius rule, should exercise every caller of the mode resolver and export seam: each analyzer, `all`, `local`, `list`, `explain`, `doctor`, `-q`, `--format json`, `--dry-run`, `--keep-export`, and the >50-item refusal with and without `--all`.

**Live run 2026-10-09** (1.9.0b10, workspace `visual-error-testing` c4698d28…, service principal from `.fab-test/.env`, installed console script):

Verified:
- `bpa`, `pbir`, `a11y`, `rdl`: typed target, untyped target (resolved by the analyzer's own type), and standalone `--workspace` (dry-run lists 6 models / 8 reports / 4 paginated, usage-metrics items excluded).
- Service vs repo parity over the `--keep-export` export: identical for `bpa` (72 tests, 12 failed), `pbir` (11 findings), `a11y` (4 findings), same exit codes.
- `pql-test --workspace`: all 6 deployed models reached over XMLA, each "no tests" (none has PQL.Assert), exit 0.
- Export deleted after the run by default, kept with `--keep-export`; `-q` one line; `--format json` one stdout document; envelope carries `mode`/`source`; `explain` and `list` show the workspace scope; `doctor` (with `FABRIC_WORKSPACE_ID`) reports service mode per analyzer; `auth status` resolves an ambient `DefaultAzureCredential`.

Not verifiable here:
- `az login`: the only user account available is in a different tenant from the workspace (HTTP 401 on every call). Needs a user in the Fabric tenant with workspace access.
- >50-item refusal: no workspace with more than 50 items of one type (largest has 8). Covered by unit tests only.

Defects found (tasks below):
1. `all --workspace`: one item's export failure aborts that whole analyzer (`bpa`, `pbir` analyzed nothing), `a11y` and `playwright` never run and are not mentioned, and the aggregate summary invents rows from the local checkout (`SampleModel-PQLAssert`, `ThinReport`, `ACC-03` twice, `QRY-01`, … with nonexistent envelope paths; "27 artifacts"). `run.json` is correct (10). `all --workspace --dry-run` also omits `a11y` and `playwright`.
2. `pql-test` with a typed or untyped workspace target ignores it: falls into local discovery, prints "no *.SemanticModel artifacts found under <cwd>", exits 0 -- a silent pass on a model never tested. `is_service_run` only treats `pql_test` as service under `all` or `--workspace`; the "typed target keeps its XMLA path" path is never reached because discovery runs first.
3. Export layout `<out>/<analyzer>/<workspace GUID>/<name>/export/<name>.<Type>/definition/...` exceeds Windows' 260-character limit from a 31-character repo root (`Report with Bookmarks - Broken Visuals` model and report). The `bpa` failure reports "No such file or directory" without the long-path remediation the `pbir` one gives.
4. `native.json`/`native.xml` ignores `--output-dir` (`pbir`, `rdl`, `pql-test`): written under `./fab-test-results/` while the envelope honors the flag.
5. HTTP 401 is reported as a missing-permission problem ("this identity may not read its definition ... needs read"); a 401 is a rejected token -- wrong tenant or audience -- and should name `az login --tenant` / the credential source.
6. Smaller: `rdl --dry-run` prints `(analyzers: none)` for paginated reports; `doctor` has no `--workspace`; `--format json` still prints the wrapper's narration on stderr; the envelope's `workspace` field is `None` in service mode; `explain bpa` shows two different Tabular Editor paths (Tool vs Command); `list` still names the `local/` scope `desktop`.

---

## `all --workspace` Runs Every Service Analyzer And Reports Only What Ran

**Requirements**:
- Given `all --workspace WS`, should run every service-capable analyzer -- `bpa`, `pbir`, `a11y`, `rdl`, `pql-test`, and `playwright` -- or name each one it skips and why; `--dry-run` should list the same set
- Given one deployed item whose export fails, should report that item as failed and still analyze the analyzer's other items
- Given a service run, should build the aggregate summary only from what this run produced -- never from the local checkout -- so its rows, envelope paths, and totals agree with `run.json`

---

## pql-test Honors A Workspace Target

**Requirements**:
- Given `pql-test "WS.Workspace/NAME.SemanticModel"` or `pql-test "WS.Workspace/NAME"`, should run that one deployed model over XMLA, the way `--workspace` runs every model
- Given a workspace target that names no deployed model, should exit non-zero naming the model and workspace, never 0 with "no artifacts found under <cwd>"

---

## Exports Fit Windows Path Limits

**Requirements**:
- Given a deployed item with a long display name and deep PBIR/TMDL parts, should export it under the default results directory from a typical repository path on Windows without exceeding 260 characters (drop the repeated name/GUID segments, or shorten them)
- Given an export that still cannot be written because a path is too long, should name a shorter `--output-dir` or Windows long-path support for every analyzer, not only `pbir`

---

## Native Output Honors --output-dir

**Requirements**:
- Given `--output-dir DIR`, should write each analyzer's native output (`native.json`/`native.xml`) under DIR beside its envelope, never under `./fab-test-results/`

---

## A Rejected Token Is Not A Missing Permission

**Requirements**:
- Given Fabric answers HTTP 401, should say the token was rejected (wrong tenant or audience) and name the credential that was used and `az login --tenant` / the service-principal tenant variable as the fix
- Given Fabric answers HTTP 403, should keep today's missing-permission message

---

## Document All Three Callers

**Requirements**:
- Given the human caller, should update README and `docs/QUICK-VALIDATION.md` with the mode-resolution matrix, service-mode examples (typed, untyped, standalone), auth options, `--keep-export`, and the `--all` threshold.
- Given the pipeline caller, should add a copy-pasteable CI snippet running `fab-test all --workspace` with service-principal secrets under `docs/examples/`.
- Given the agent caller, should update the fab-test skill in SudoLang — `SKILL.md`, `references/targeting-and-discovery.md` (the scopes table and the retired fabric-cicd rule, decision 2), `references/credentials.md`, `references/flags.md` — synced byte-for-byte to `src/fab_test/skill/` (guarded by `tests/test_skill_resource.py`).
- Given vision.md names the fabric-cicd boundary, should amend it per decision 2 (read-only ephemeral export for testing is in scope; deployment remains out).
- Given an epic-sized `src/` change, should bump MINOR in `src/fab_test/__init__.py` (`.dev1`) and add a CHANGELOG entry via `aidd-log`.

---

## pql-test Connects As fab-test's Identity

**Requirements**:
- Given a service principal configured in the environment or a `.env` file, under either the `FABRIC_SERVICE_PRINCIPAL_*` or the `FABRIC_CLIENT_*` names, should run pql-test as that same service principal.
- Given fab-test signed in as a person and pql-test saved as another account, should stop the pql-test run naming both accounts and the sign-in to run.
- Given pql-test's own sign-in status cannot be read, should let the run proceed rather than block on the check.
- Given pql-test could not connect to a deployed model, should report that it could not connect and why, not that the model has no tests.
- Given pql-test reached a model without PQL.Assert installed, should report that the model has no tests.
- Given the pql-test wrapper, should stay within its module size budget by keeping result classification in its own module.

---

## Quality Gates

**Requirements**:
- Given the whole repository, should pass `ruff check .`, `tests/test_complexity_budget.py`, and `tests/test_module_budget.py` — `fab_test_parser.py` (35.9K) and `_target.py` (10.7K) are near or over their ceilings, so split on existing seams rather than raise exemptions.
- Given the full suite, should pass with `--cov --cov-fail-under=80` over `src/fab_test`.
- Given CI-dependent tests, should pass once with `GITHUB_ACTIONS=true CI=true`.
