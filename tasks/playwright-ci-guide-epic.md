# Playwright CI Guide Epic

**Status**: 🔄 IN-PROGRESS (2/7 tasks: setup guide drafted; CLI gaps 5/6 fixed, spec packaging fixed 2026-09-26)
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

---

## Add the live demo workflow to this repository

Add `.github/workflows/playwright-demo.yml`, which runs the same steps as the example against this repository's own deployed demo reports.

**Requirements**:
- Given `tests/test_workflow_triggers.py`, should add `playwright-demo.yml` to `_EXPECTED_WORKFLOWS` and update the module docstring to record why this one service-principal workflow is allowed back in, so the policy change is visible in the diff and doesn't slip in unnoticed.
- Given the triggers, should be `workflow_dispatch` only, with no `pull_request`, `push`, or `schedule`, so it never runs on a PR and never needs secrets that a fork can't see.
- Given credentials, should read them only from a protected `fabric-demo` GitHub Environment with required reviewers, so no one can dispatch against the tenant without approval.
- Given that the demo tests this repository's current code, should install from the checkout (`pip install -e .`), unlike the consumer example. A comment should point readers to the example for the published-package path.
- Given the artifact input, should default to `SampleModel-PQLAssert` (4 cases, verified green) and offer `Not Working Visuals` (Page 1 fails with `Missing_References`, verified red) as a choice, so the same workflow shows both a green and a red run.

---

## Guard the guide and both workflows against drift

Add a documentation test in the style of `tests/test_a11y_documentation.py` that fails when either workflow or the guide stops matching the CLI.

**Requirements**:
- Given the example and demo workflows, should parse each as YAML and assert the browser install step comes before any `fab-test` step, that the upload runs with `if: always()`, and that no secret value is inlined.
- Given the environment variable names the CLI reads for Playwright, should assert that the guide and both workflows name the same set, so a renamed variable breaks the build instead of the reader's first run.
- Given the demo workflow, should assert its triggers are exactly `workflow_dispatch` and its job names an `environment`, so a later edit can't quietly expose it to PRs.

---

## Prove it end to end, locally first and then in CI

Run the demo locally from `.fab-test/.env`, then dispatch the demo workflow and run the copied example in a scratch consumer repository. Each runs once against a passing report and once against `Not Working Visuals`.

**Requirements**:
- Given `.fab-test/.env` on a developer machine, should reproduce the same pass and fail results locally with `fab-test doctor` and `fab-test playwright --report` before any CI run, so a CI failure can only come from CI setup.
- Given the passing report, should finish with exit `0`, a green step summary, and an uploaded artifact whose `report.html` links resolve to the bundled screenshots.
- Given the broken report, should fail with exit `1`, with the step summary and `findings` naming only the failing cases.
- Given anything the guide got wrong or left out during these runs, should be corrected in the guide before this task closes, since the runs test the documentation as much as the workflows.

---

## Sync all three callers

Use the `document` skill so README, QUICK-VALIDATION, and the fab-test skill all point at the guide and the example rather than keeping their own copies.

**Requirements**:
- Given README's "Playwright: the minimal working config" section, should link to `docs/PLAYWRIGHT-CI.md` for CI setup rather than restating it.
- Given README, QUICK-VALIDATION, and `references/flags.md` each list only `Report.Read.All` and `SemanticModel.Read.All`, should point to the guide's full permission list (`App.Read.All`, `Dataset.Read.All`, `SemanticModel.Read.All`, `Report.Read.All`, `Workspace.Read.All` with admin consent), the Member role, and XMLA endpoint access.
- Given QUICK-VALIDATION's partial Playwright snippet, should point to the full example workflow so the two cannot disagree, and should link to the demo workflow's run history as the working reference.
- Given the fab-test skill, should tell an agent where the example workflow and prerequisites live and which exit codes mean setup problems (`127`) versus report failures (`1`), with the packaged copy under `src/fab_test/skill/` kept identical.

---
