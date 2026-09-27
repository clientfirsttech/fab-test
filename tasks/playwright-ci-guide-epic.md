# Playwright CI Guide Epic

**Status**: 🔄 IN-PROGRESS (7/8 tasks: setup guide, all 6 CLI gaps, the example workflow, the demo workflow, the drift test, proving it end to end in CI, and syncing the three doc callers done; non-PBIP RLS role discovery remains, tracked separately since it needs a new runtime dependency decision)
**Goal**: Give a team a documented, copy-ready GitHub Actions path from "no service principal" to a green `fab-test playwright` run against their own Fabric workspace.

## Overview

`fab-test playwright` is the one analyzer that cannot fall back to `az login`. It needs a service principal with the right grants, tenant settings, and workspace role, plus a browser on the runner. Today someone setting it up in CI has to piece that together from README fragments and a partial snippet in QUICK-VALIDATION that nothing runs, so each team rediscovers the missing grant or the missing `playwright install` the hard way. This epic adds one end-to-end setup guide, a complete example workflow people can copy into their own repository, and a manually triggered demo workflow in this repository that shows it working against a real workspace. Tests keep the guide and both workflows in step with the CLI. The demo workflow deliberately reverses the "no service-principal credentials here" policy in `tests/test_workflow_triggers.py`, but only for a dispatch-only workflow behind a protected Environment, so PRs stay free of the noise that policy was written to stop.

---

## Write the service principal and workspace setup guide

Add `docs/PLAYWRIGHT-CI.md`, covering every step outside GitHub that has to happen before the first run.

**Requirements**:
- Given a reader with no app registration, should walk through creating the Entra app and secret and granting `App.Read.All`, `Dataset.Read.All`, `SemanticModel.Read.All`, `Report.Read.All`, and `Workspace.Read.All` with admin consent, stating what degrades without the discovery grants (fallback to the default page and role, not a failure).
- Given a tenant where service principals are blocked from Fabric/Power BI APIs, should name the admin-portal tenant setting and the security group to add the app to, since this is the most common silent blocker.
- Given the target workspace, should state the minimum workspace role for the service principal and that the report must already be deployed, because Playwright renders the published report, not the local folder.
- Given the setup is finished, should have the reader confirm it locally with credentials in `.fab-test/.env` (picked up with no flag, per the `--env-file > PLAYWRIGHT_ENV_FILE > .fab-test/.env > ./.env` search order), `fab-test doctor`, and one `fab-test playwright` run before touching CI, and should explain what exit `127` and its named missing variables mean.
- Given `fab-test init` scaffolds `PLAYWRIGHT_WORKSPACE_ID` while workspace resolution documents only `--workspace-id`, `FABRIC_WORKSPACE_ID`, and `workspace:` in `fab-test.yml`, should verify through the real CLI which names actually resolve a workspace for `--artifact` and document only those. If they disagree, the mismatch should be raised as its own fix and not papered over in the guide.
- Given a common failure (render timeout, permissions panel, token-scope error), should map it to the evidence file that names it (`event_log.json`, `embed_error_details.txt`) and the fix.

---

## Close the CLI gaps the guide surfaced

Fix the mismatches between documented and actual behavior that the first local run exposed, so the guide can describe one path with no caveats.

**Requirements**:
- Given `--artifact` with a workspace from `--workspace-id`, `FABRIC_WORKSPACE_ID`, or `workspace:`, should not also require `--env`, since README documents that form as the no-config path and today it fails with "No environment given".
- Given a workspace only in `PLAYWRIGHT_WORKSPACE_ID` (as `fab-test init` scaffolds) or in `workspace:` in `fab-test.yml`, `doctor` should report the same readiness the run itself acts on, not ❌ for a run that succeeds.
- Given no `--env-file`, `auth status` and workspace-name resolution should use the same `.fab-test/.env` search as credential probing, not fall back to the ambient Azure identity and report a reachable workspace as unreachable.
- Given missing service-principal variables, should exit `127` as README and the skill's Agent Contract promise, not `1`, so a pipeline can tell setup failures from render failures.
- Given `fab-test playwright` installed from the wheel and run outside this repository, should find its pytest spec. Today `_SPEC_PATH` is `<cwd>/tests/test_playwright_visual.py`, which ships in no wheel, so every consumer run fails with `ERROR: usage: python -m pytest` (verified 2026-09-26 from `.venv-test` in a scratch folder).
  **Fixed 2026-09-26**: the render checks moved into the package (`playwright_validation/render_spec.py` + `render_helpers.py`); `tests/test_playwright_visual.py` now holds only their unit tests. `invoke_playwright.py._spec_path()` resolves the spec from the installed module, and `check_wheel_contents.py`'s `REQUIRED` guards it shipping. Verified end to end from `.venv-test` (a wheel-equivalent editable install) run from a scratch directory with no checkout: exit 0 against `SampleModel-PQLAssert`. Splitting `test_report_visual_renders` into `_resolve_case_config`/`_embed_interactive_report`/`_finish_interactive_case` kept `tests/test_complexity_budget.py`'s ceiling at 0 -- the function's pre-existing complexity had been invisible in `tests/`, which this repo's own complexity scan does not cover, and became visible only once it moved into `src/`.
  **New finding, same task**: with the spec now reachable, the *next* failure for a genuine `pip install fab-test` consumer is `pytest`, `pytest-playwright`, `pytest-html`, and `pytest-xdist` all being dev-only dependencies of this project -- a consumer must `pip install` all four separately, or the run fails with a raw `unrecognized arguments: --html=...` usage error. This was already true before today and is already asserted by `tests/test_invoke_playwright.py::test_pytest_html_and_pytest_playwright_are_dev_dependencies`, but the one doc that named the extra install step (`references/flags.md`'s "Browser setup") only named `pytest-html`, silently missing the other three -- corrected 2026-09-26 in `flags.md` and `docs/PLAYWRIGHT-CI.md`. Left open: `fab-test doctor`/`playwright` still surface a raw pytest usage error here instead of a `fab-test`-style remediation message (exit 127 naming the missing package) -- a deliberate design decision on which of these four become hard runtime dependencies vs. stay an extra install step, not folded into this task without asking.
- Given a real Playwright run, should collect only the report render cases, not the 11 unit tests that share `test_playwright_visual.py` today.
  **Fixed 2026-09-26** as a byproduct of the Render Spec Packaging split above: `render_spec.py` (the file `invoke_playwright.py` points pytest at) holds only `test_report_visual_renders`; the 11 unit tests stayed behind in `tests/test_playwright_visual.py`, which nothing points a real run at. All six gaps in this task are now closed.

---

## Author the copy-ready example workflow

Add `docs/examples/github-actions/playwright-live.yml`, a complete workflow a consumer drops into their own `.github/workflows/`.

**Requirements**:
- Given a consumer repository, should install `fab-test` the way a consumer does (the published package, with the TestPyPI line shown until the first final release) and should never assume a checkout of this repository.
- Given the runner, should run `playwright install --with-deps chromium` before `fab-test`, since the pip install alone leaves no browser binary.
- Given credentials, should read `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, and `FABRIC_CLIENT_SECRET` from a GitHub Environment's secrets and `FABRIC_WORKSPACE_ID` from a variable, and should run `fab-test doctor` first so a missing value fails fast with exit `127`.
- Given the triggers, should use `workflow_dispatch` with `artifact`, `pages`, and `roles` inputs plus a commented-out `schedule`, and should not use `pull_request`, where fork PRs get no secrets.
- Given a failing run, should still upload `fab-test-results/**`, including `playwright/test-cases/**`, under `if: always()`, and should write a per-case pass/fail table from the envelope's `test_results` to `$GITHUB_STEP_SUMMARY`.
- Given the GitHub-side setup, should be covered in the guide: creating the Environment, adding required reviewers, and entering each secret and variable by the exact name the workflow reads.

**Done 2026-09-27.** `docs/examples/github-actions/playwright-live.yml`, with `artifact`/`dataset_id`/`dataset_workspace_id`/`pages`/`roles` dispatch inputs covering all three targeting shapes (per the "show off `--dataset-id`/`--dataset-workspace-id`, not just a bare `--artifact` run" note in `plan.md`). `docs/PLAYWRIGHT-CI.md` gained the GitHub Environment setup steps and a table describing the three input shapes. Live-verified against the real workspace: ran the workflow's exact commands and its step-summary script by hand against `--dataset-workspace-id` alone (2 reports, "every dataset" mode) -- caught a real bug doing it, not a hypothetical one: the upload step's `test-cases/**` glob was flat (`playwright/test-cases/**`), but the real layout nests it per report (`playwright/<report>/test-cases/**`); a dataset-targeted or batch run producing more than one report would have uploaded nothing there and left every `report.html` linking to files that were never included. The same flat pattern was already wrong in `docs/QUICK-VALIDATION.md`, README.md, and `references/flags.md` (both copies) -- fixed all four, and added `tests/test_playwright_test_cases_path_docs.py` so it can't drift back silently.

---

## Add the live demo workflow to this repository

Add `.github/workflows/playwright-demo.yml`, which runs the same steps as the example against this repository's own deployed demo reports.

**Requirements**:
- Given `tests/test_workflow_triggers.py`, should add `playwright-demo.yml` to `_EXPECTED_WORKFLOWS` and update the module docstring to record why this one service-principal workflow is allowed back in, so the policy change is visible in the diff and doesn't slip in unnoticed.
- Given the triggers, should be `workflow_dispatch` only, with no `pull_request`, `push`, or `schedule`, so it never runs on a PR and never needs secrets that a fork can't see.
- Given credentials, should read them only from a protected `fabric-demo` GitHub Environment with required reviewers, so no one can dispatch against the tenant without approval.
- Given that the demo tests this repository's current code, should install from the checkout (`pip install -e .`), unlike the consumer example. A comment should point readers to the example for the published-package path.
- Given the artifact input, should default to `SampleModel-PQLAssert` (4 cases, verified green) and offer `Not Working Visuals` (Page 1 fails with `Missing_References`, verified red) as a choice, so the same workflow shows both a green and a red run.

**Done 2026-09-27**, with two deliberate deviations from the letter of the above, both explained here rather than silently:
- `pip install -e ".[dev]"`, not `pip install -e .` -- `pyproject.toml`'s `dev` extra already declares `pytest`/`pytest-playwright`/`pytest-html`/`pytest-xdist`, so one install covers fab-test and everything Playwright needs, closing the same dev-only-dependency gap the "Close the CLI gaps" task found for the published-package path.
- `artifact` is free text with a default, not a `choice` of two reports -- by the time this task was built, `--dataset-id`/`--dataset-workspace-id` targeting existed too (Playwright Dataset Target epic), so the workflow gained `dataset_id`/`dataset_workspace_id` inputs alongside `artifact`; a fixed two-report choice list would have fought "leave `artifact` blank to target a dataset instead."
- Workspace targeting is `--env <environment>` (a `choice` input resolved through this repository's own committed `.fab-test/metadata/environments.yml`) plus an optional `workspace_id` override that wins over it -- raised directly by the user while setting up the `fabric-demo` Environment ("how do I make that dynamic... depending on the test I may want to call it against the test workspace or the dev workspace"), instead of one fixed `FABRIC_WORKSPACE_ID` Environment variable like the consumer-facing example workflow. `dev` already resolves to a real workspace with nothing else supplied; `test`/`prod` have no `workspace_id` in that file yet, so they need the override until they do. `docs/PLAYWRIGHT-CI.md` gained a "Picking dev, test, or prod at dispatch time" section documenting the pattern for a consumer who wants the same flexibility.

Live-verified by replicating the workflow's exact steps by hand against the real workspace: from a directory with no checkout, `--env dev` fails correctly (`environments.yml not found`, naming the fallbacks) -- confirming the checkout step is load-bearing, not decorative; from the repository root (what `actions/checkout@v4` gives the real job), the same command resolves `dev` to the workspace and passes, exit 0.

A drift test (`tests/test_playwright_workflows_drift.py`) now guards both this workflow and the example one together, satisfying all three requirements of "Guard the guide and both workflows against drift" below in the same pass: browser install before any `fab-test` step, `if: always()` on every upload, and no inlined secret (both workflows); the guide and both workflows naming the same three credential variables; and the demo's triggers being exactly `workflow_dispatch` with its job naming a protected `environment`.

---

## Guard the guide and both workflows against drift

Add a documentation test in the style of `tests/test_a11y_documentation.py` that fails when either workflow or the guide stops matching the CLI.

**Requirements**:
- Given the example and demo workflows, should parse each as YAML and assert the browser install step comes before any `fab-test` step, that the upload runs with `if: always()`, and that no secret value is inlined.
- Given the environment variable names the CLI reads for Playwright, should assert that the guide and both workflows name the same set, so a renamed variable breaks the build instead of the reader's first run.
- Given the demo workflow, should assert its triggers are exactly `workflow_dispatch` and its job names an `environment`, so a later edit can't quietly expose it to PRs.

**Done 2026-09-27** as part of building the demo workflow above -- see that task's note for what `tests/test_playwright_workflows_drift.py` covers.

---

## Prove it end to end, locally first and then in CI

Run the demo locally from `.fab-test/.env`, then dispatch the demo workflow and run the copied example in a scratch consumer repository. Each runs once against a passing report and once against `Not Working Visuals`.

**Requirements**:
- Given `.fab-test/.env` on a developer machine, should reproduce the same pass and fail results locally with `fab-test doctor` and `fab-test playwright --report` before any CI run, so a CI failure can only come from CI setup.
- Given the passing report, should finish with exit `0`, a green step summary, and an uploaded artifact whose `report.html` links resolve to the bundled screenshots.
- Given the broken report, should fail with exit `1`, with the step summary and `findings` naming only the failing cases.
- Given anything the guide got wrong or left out during these runs, should be corrected in the guide before this task closes, since the runs test the documentation as much as the workflows.

**Done 2026-09-27** via real `gh workflow run` dispatches against the demo workflow (not a local replay) -- caught four real bugs in CI that a local run alone wouldn't have hit, each fixed and re-verified live:
- `doctor` has no visibility into `--env`/`environments.yml` and no `--workspace-id` flag, so it reported every cloud analyzer "no workspace ... resolved" and exited 1 even with a fully configured service principal -- fixed by resolving the same workspace the run step uses and exporting it as `FABRIC_WORKSPACE_ID` before calling `doctor`.
- The job's container runs steps under `sh`, not `bash`; the run step's `args=(...)` bash-array syntax failed with `Syntax error: ( unexpected` -- fixed with POSIX `set --` positional parameters instead.
- `playwright` is unpinned in `pyproject.toml`; a new release (1.63.0) shipped between two dispatches of this same workflow while the container image stayed pinned to the older tag, so the installed driver's browser revision didn't match what the image baked in (`BrowserType.launch: Executable doesn't exist at .../chromium_headless_shell-<rev>/...`) -- fixed by pinning the pip install to the same version as the container tag (`PLAYWRIGHT_PIN`), so the two can only drift on a deliberate edit.
- Sweeping `--dataset-workspace-id` alone across a real workspace hit RLS-secured datasets (`RLSTest*`) that `generate_embed_token` couldn't mint a token for: `use_rls and user_name and role` required a discovered role name even to attach an identity at all, so a dataset needing an effective identity but with no discoverable role could never get one. Added `test_rls`/`PLAYWRIGHT_USE_RLS`/`PLAYWRIGHT_USER_NAME` wiring to the demo workflow so RLS testing is opt-in rather than silently off -- that part stands. The obvious fix in `power_bi_api.py` (drop the `role` requirement, send `"roles": []` when none was discovered) was tried and **reverted after a live re-run proved it a net regression**: Power BI rejected all 6 *non*-RLS datasets with "shouldn't have effective identity" (they'd previously passed with no identity attached at all), while the 3 `RLSTest*` datasets still failed -- now with "requires roles to be included in provided effective identity" instead of "requires effective identity to be provided". That second error is the real information: these datasets have genuine named roles that discovery isn't finding; an empty roles list was never going to satisfy them. The guard is back to requiring `role`, and the actual fix belongs in role discovery, not here.

Left open, tracked as its own task below: role discovery itself (`get_semantic_model_roles`) still only reads the semantic model's Fabric *definition* (TMDL role files), which 404s for a non-PBIP-enabled model, and that's confirmed now to be the actual blocker for `RLSTest*` -- not just a theoretical gap.

---

## Discover RLS roles for non-PBIP-enabled semantic models

**Status**: 📋 PLANNED

`get_semantic_model_roles` (`service_client.py`) discovers roles by downloading the semantic model's Fabric definition and reading `definition/roles/<Name>.tmdl` part paths. That's blind to any model not enabled for PBIP/Git-integration-style definition download -- `getDefinition` 404s, and discovery silently returns `[]` with no warning (indistinguishable from "this model genuinely has no roles").

The obvious portable fix -- the Power BI REST `executeQueries` API running `EVALUATE INFO.ROLES()` -- is a dead end: Microsoft's own docs state plainly that `executeQueries` supports DAX queries only, and **"INFO functions ... are not supported."** Confirmed by a prior working implementation ([kerski/pbi-dataops-visual-error-testing](https://github.com/kerski/pbi-dataops-visual-error-testing)) that runs `INFO.ROLES()` a different way entirely: `Invoke-ASCmd` (PowerShell's `SqlServer` module, backed by AMO/ADOMD.NET) against the model's true XMLA endpoint, parsing the raw XMLA/SOAP response. That path is Windows/PowerShell-shaped and pulls in a .NET client library `fab-test` has never depended on.

Options for a Python-side, Linux-CI-compatible equivalent, roughly cheapest to most involved:
- **ADOMD.NET via pythonnet**: `Microsoft.AnalysisServices.AdomdClient.NetCore` (NuGet) targets .NET Core/Linux, so it isn't inherently Windows-only -- but it needs the .NET runtime present in the container image and a Python/.NET bridge (`pythonnet`), a real new dependency chain for one discovery call.
- **Hand-rolled XMLA-over-SOAP**: XMLA is plain SOAP-over-HTTPS, so a raw `Execute` envelope posted with the existing AAD bearer token is possible in pure Python (`requests`) with no new runtime dependency -- but means implementing SOAP envelope construction and parsing the XMLA rowset response from scratch, with no existing client library to lean on.
- **Leave the gap documented**: keep today's TMDL-only discovery and accept that a non-PBIP RLS-secured model simply can't be Playwright-tested under RLS yet.

Confirmed live (not just theoretical) that this is a real, present blocker, not a hypothetical edge case: dispatching against the workspace's `RLSTest*` datasets with `PLAYWRIGHT_USE_RLS`/`PLAYWRIGHT_USER_NAME` both set still failed GenerateToken with *"requires roles to be included in provided effective identity"* -- Power BI confirming these models have genuine named roles that today's TMDL-based discovery never finds (silently, as `[]`, indistinguishable from "no roles defined").

**Requirements**:
- Given a non-PBIP-enabled semantic model with RLS roles, should discover them, or should log a distinguishable warning (not silent `[]`) when discovery is genuinely not possible, so "no roles" and "couldn't check" never look the same in a doctor/CI run.
- Given whichever approach is chosen, should not require a Windows-only runtime on the demo workflow's Linux container, since that's where this gap was actually found.
- Given `generate_embed_token`'s `use_rls and user_name and role` guard, should only be revisited once discovery can actually return correct role names for these datasets -- loosening it before that (tried and reverted once already) breaks every non-RLS dataset instead.

---

## Sync all three callers

Use the `document` skill so README, QUICK-VALIDATION, and the fab-test skill all point at the guide and the example rather than keeping their own copies.

**Requirements**:
- Given README's "Playwright: the minimal working config" section, should link to `docs/PLAYWRIGHT-CI.md` for CI setup rather than restating it.
- Given README, QUICK-VALIDATION, and `references/flags.md` each list only `Report.Read.All` and `SemanticModel.Read.All`, should point to the guide's full permission list (`App.Read.All`, `Dataset.Read.All`, `SemanticModel.Read.All`, `Report.Read.All`, `Workspace.Read.All` with admin consent), the Member role, and XMLA endpoint access.
- Given QUICK-VALIDATION's partial Playwright snippet, should point to the full example workflow so the two cannot disagree, and should link to the demo workflow's run history as the working reference.
- Given the fab-test skill, should tell an agent where the example workflow and prerequisites live and which exit codes mean setup problems (`127`) versus report failures (`1`), with the packaged copy under `src/fab_test/skill/` kept identical.

**Done 2026-09-27.** The `document` skill's own trigger (`.github/skills/document/SKILL.md`) covers CLI-flag/subcommand sync, not this task's guide-linking scope, so this was done directly against the four requirements above instead:
- README's "minimal working config" section gained a "Running this in CI" pointer to `docs/PLAYWRIGHT-CI.md` and the example workflow; its and QUICK-VALIDATION's partial `Report.Read.All`/`SemanticModel.Read.All` mentions now point to the guide's full five-permission list instead of restating two of them.
- QUICK-VALIDATION's Playwright pipeline snippet gained a pointer to the full example workflow and to this repository's own demo workflow run history (`https://github.com/kerski/fab-test/actions/workflows/playwright-demo.yml`) as the working reference.
- `.github/skills/fab-test/references/flags.md` gained an exit-code summary (`127` = setup problem, `1` = report failure) and pointers to the guide, the example workflow, and the demo workflow -- as plain-text paths, not markdown links, since this file also ships inside the installed package (`src/fab_test/skill/`) where a relative link into a sibling `docs/` folder wouldn't resolve.
- `tests/test_package_metadata.py::test_every_readme_link_resolves_off_the_project_page` caught the two new README links using relative paths (would 404 on the PyPI project page) -- fixed to the repository's established `https://github.com/kerski/fab-test/blob/main/...` convention.
- Re-synced `src/fab_test/skill/references/flags.md` from its authored counterpart; `tests/test_skill_resource.py` confirms parity.

---
