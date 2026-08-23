# Playwright Through The Front Door Epic

**Status**: 📋 PLANNED
**Goal**: `fab-test playwright` says what it needs before it needs it, and takes it from `fab-test.yml` and `.fab-test/` — no traceback, no metadata scavenger hunt.

## Overview

`fab-test playwright` is the last command in the CLI that has not been moved onto the
front door the rest of it already uses, and running it on a laptop proves it twice in
one invocation. It resolved `SampleModel-PQLAssert` fine — discovery goes through
`build_fabric_service_client`, which falls back to `DefaultAzureCredential` — and then
died on a raw MSAL `ValueError` when it went to fetch the embed token. Playwright
genuinely needs a service principal for that step — an ambient `az login` cannot
generate an embed token, unlike `pql-test`, which authenticates interactively. That is
not the bug. The bug is that nothing said so: `_build_config_from_args` disables the
required-field check exactly when `--artifact` is passed, which the CLI always does, so
the one validation that names `FABRIC_TENANT_ID` never ran. An empty tenant became
`https://login.microsoftonline.com/`, msal raised, and `_run_single_report` catches only
`PowerBiApiError` — so the exception ran clean off the top of `sys.exit(main())`.

Two principles broke. **Tell the caller how to fix it** — the output named a msal
URL-parsing rule, not the variable to set, after two successful API calls had already
made the run look healthy. And the front door: `fab-test.yml` has had a `workspace:` key
since Artifact Targeting §3 — validated, and flowing all the way through to
`--workspace-id` — but `playwright` is the one caller that still routes around it into
`environments.yml` first. That is why a workspace GUID had to be hand-edited into
`.github/metadata/environments.yml`. The key is also absent from the `fab-test init`
template and from `config --show`, so there was no way to discover it existed.

Nothing here is a new subsystem. Most of these tasks delete code, re-point a path, or
reuse something already written.

---

## 1. Playwright refuses early and by name when it has no service principal

**Scope decision (2026-08-22, user)**: embed-token generation genuinely requires a
service principal — client ID and secret. An ambient `az login` is not sufficient for
this analyzer, unlike `pql-test`, which can authenticate interactively. So the fix is
**not** to add a `DefaultAzureCredential` fallback to the embed path. It is to say so,
before any of the work that currently happens first.

That makes the real defect a validation one, and a sharp one. `_build_config_from_args`
calls:

```python
service_resolved = bool(args.artifact or args.impact_manifest)
config = load_config(args.env_file, required=not service_resolved)
```

`fab-test playwright` **always** passes `--artifact`. So the required-field check —
which lists `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, and `FABRIC_CLIENT_SECRET` by name
and raises a perfectly good `ValueError` — is switched off on the only path a user
takes. It survives solely for direct `invoke_playwright` calls, which nobody makes.

The delay is what made it hostile. `build_fabric_service_client` *does* accept an ambient
credential, so discovery succeeded, the report resolved, the run printed a heading — and
only then did an empty tenant reach msal. The two halves of one command disagree about
what credentials suffice, and the disagreement surfaces as a stack trace two API calls
deep instead of a refusal on line one.

The duplicated service-principal branch between `_acquire_access_token` and
`_authenticate_service_principal` is still duplication, but it is **not** the same policy
in two places — one legitimately allows ambient and the other must not. Collapse the
shared part if it is clean to do so; do not collapse the policies.

**Requirements**:
- Given `--artifact` and an incomplete service principal, should refuse **before** building a client or making any network call, naming every missing variable
- Given the refusal, should name where to set them: `.env`, the environment, or `--env-file` — per the vision's fourth principle
- Given a complete service principal, should behave exactly as today
- Given `pql-test` or any analyzer that accepts interactive auth, should be unaffected — this requirement is Playwright's, not the CLI's
- Given the refusal, should exit `127` (missing prerequisite), consistent with the readiness-probe contract, not `1`
- Given `fab-test doctor`, should report `playwright` as not ready for the same reason rather than a false green

**Verification**: run `fab-test playwright` with no `.env`. The current behaviour is a
msal traceback after two successful API calls; the required behaviour is an immediate,
named refusal. Then set a real service principal and confirm a passing envelope against
DEV — the epic is not done on the refusal alone.

---

## 2. No exception leaves the Playwright wrapper as a traceback

`_run_single_report` catches `PowerBiApiError` and writes an envelope; every other
exception escapes to the console. That asymmetry is why the run produced a stack trace
instead of a `❌` row with a reason — and why `run.json` would have carried
`"detail": null` for it, leaving the agent caller told that it failed and not why.

**Requirements**:
- Given any exception during embed-context acquisition, should write an error envelope, emit `::error::` to stderr, and return 1 — never propagate
- Given the failure is a credential problem, should name the config key or environment variable that resolves it, per the vision's fourth principle
- Given `--format json`, should keep stdout pure JSON on this path
- Given a resolution failure inside a multi-artifact run, should leave the other artifacts' results intact and reflected in the summary

---

## 3. `workspace:` in fab-test.yml is enough — `environments.yml` becomes optional

When a workspace ID is already resolved — from a `WORKSPACE.Workspace/...` target,
`--workspace-id`, `FABRIC_WORKSPACE_ID`, or `workspace:` in `fab-test.yml` — there is
nothing left for `environments.yml` to supply, and `_build_config_from_args` should not
open it. Today it calls `resolve_environment` unconditionally, so a missing file or an
absent `dev:` key fails a run whose workspace was never in question.

**Requirements**:
- Given `workspace:` set in `fab-test.yml` and no `environments.yml` anywhere, should run without error
- Given `workspace:` set as a display name rather than a GUID, should resolve it through the existing `resolve_workspace_id` path
- Given no workspace resolved from any source, should read `environments.yml` exactly as it does today
- Given neither a workspace nor an `environments.yml`, should name **both** routes — the `workspace:` key and the metadata file — not only the one it looked at last
- Given a repository that pins its workspace in `environments.yml` today, should be unaffected (backward-compat constraint)

---

## 4. `workspace:` becomes discoverable

The key works and is documented nowhere a user would look: not in the `fab-test.yml`
scaffolded by `fab-test init`, not in `_SETTING_SPECS`, and therefore not in
`config --show`. A setting that cannot be found is a setting that does not exist.

**Requirements**:
- Given `fab-test init`, should scaffold a commented `workspace:` line alongside `environment:`
- Given `fab-test config --show`, should list `workspace` with its effective value and origin
- Given the value came from `FABRIC_WORKSPACE_ID`, should report that origin rather than the file
- Given `--format json`, should include the row in the same shape as every other setting

---

## 5. "No Report matching X" prints the names it already has

[`resolve_item`](../src/fabric_ci_cd_dataops/scripts/playwright_validation/resolver.py#L272)
builds `candidates=all_names` — every report actually in the workspace — attaches it to
the exception, and then formats a message that mentions none of them. That is why
`ThinReport` failed with a dead end while the CLI was holding the answer. It also calls
`client.list_items` twice on that path.

**Requirements**:
- Given no item matches, should name the closest candidates from the workspace in the message
- Given the workspace contains no items of that type at all, should say so rather than print an empty list
- Given many items, should cap the listed names so the message stays readable in an 80-column terminal
- Given the no-match path, should list the workspace once, not twice

---

## 6. Document all three callers

Per the Definition of Done in [vision.md](../vision.md): the agent gets the updated
skill, the human gets README and docs, the pipeline gets copy-pasteable YAML. Run this
through the `document` skill so the three cannot drift.

**Requirements**:
- Given the `fab-test` skill, should document that `playwright` needs no service principal and no `environments.yml` when `workspace:` is set
- Given README and `docs/QUICK-VALIDATION.md`, should show the minimal working config — `az login`, a `fab-test.yml` with `workspace:` and `environment:`, nothing else
- Given the pipeline docs, should keep the service-principal path as the CI recommendation and show it unchanged
- Given `.env.example`, should say plainly that all three variables are optional for local use

---

## 7. Re-align this repository onto the layout a consumer is told to use

Runs **last**, after 1-6 are green. This repository is still on the legacy
`.github/metadata/` layout, which is why the consumer path is not dogfooded and why
tasks 1-5 exist at all: a fresh `fab-test init` produces `fab-test.yml` and
`.env.example` and nothing else, so a new user reaches a sharp edge this checkout is
insulated from. Moving is now cheap, because most of the directory is dead weight —
measured, not assumed:

| File | Finding |
|------|---------|
| `rules/BPARules.json` | Byte-identical to the packaged copy |
| `rules/pbi-inspector-custom-rules.json` | Byte-identical |
| `analyzers.json` | Byte-identical |
| `artifact-map.json` | Byte-identical |
| `testbed.json` | **Zero callers** in `src/`, `tests/`, or `.github/` |
| `environments.yml` | The only file doing real work |

[`tests/test_packaged_metadata.py`](../tests/test_packaged_metadata.py) exists to fail
if those four ever drift — a test whose job is keeping a redundant copy redundant. It
has to change with them, not be deleted: its real subject is that the wheel ships a
usable ruleset, which stays worth asserting.

The justification in [`_metadata.py`](../src/fabric_ci_cd_dataops/scripts/_metadata.py#L39)
is also stale. It says `.github/metadata` stays searched "so existing repositories and
every workflow under `.github/workflows/` keep working". Nine pipeline workflows were
deleted; the four that remain reference `.github/metadata` **nowhere**. Consumer
repositories in the field still justify keeping the *search layer* — they do not
justify this repository keeping the *directory*, and conflating the two is what let it
sit here unexamined.

**Requirements**:
- Given the four byte-identical files are deleted from `.github/metadata/`, should resolve every one of them to the packaged copy with no behaviour change
- Given `fab-test config --show`, should report `rules.bpa` and `rules.pbir` with origin `packaged` rather than `.github/metadata`
- Given `environments.yml` moves to `.fab-test/metadata/`, should resolve there and be reported with that origin
- Given `testbed.json` has no caller, should be deleted — and if a caller is found during the task, should be recorded as a finding instead, not silently kept
- Given `_OVERRIDE_LAYERS` still lists `.github/metadata`, should keep it (consumers in the field) with the comment corrected to say why, not the stale workflow claim
- Given `analyzers.json` hardcodes `.github/metadata/rules/...` inside its `args` — in the **packaged** copy too, so the wheel points consumers at a directory they are told never to create — should resolve those through the metadata layers like every other path
- Given the full suite, should stay above the 80% coverage floor with no test deleted merely because its fixture moved

**Verification**: this task is the end-to-end proof of the epic. With `.github/metadata/`
reduced to nothing and no `.env` present, `fab-test playwright` against DEV on `az login`
alone must return a passing envelope. If it does not, tasks 1-3 were not finished.

---

## 8. `.fab-test/.env` — one directory, with the guard that makes it safe

Since Playwright needs a service principal (task 1), a `.env` is a normal part of the
local setup rather than an edge case, and it should live where everything else
fab-test owns lives. Two things have to be true first.

**There are already two `.env` discovery implementations, and they disagree.**
[`_credentials.py`](../src/fabric_ci_cd_dataops/scripts/_credentials.py#L175) defaults to
a bare `Path(".env")` — relative to the working directory.
[`playwright_validation/config.py`](../src/fabric_ci_cd_dataops/scripts/playwright_validation/config.py#L169)
defaults to `repo_root / ".env"`. They agree only when the CLI is invoked from the
repository root, which is why nobody has noticed. Adding a search path to one and not
the other would repeat the exact fork this epic exists to fix, so the search order gets
defined once and both callers read it.

**`.fab-test/` is committed; a `.env` in it is not.** `.fab-test/metadata/` is meant to
be checked in. Putting a client secret in the same directory means one `git add
.fab-test/` away from a leaked credential, and **a consumer's `.gitignore` is not this
repository's** — this repo happens to ignore `.env` at any depth, and a consumer repo
may not. The location is only safe if fab-test ships the guard itself.

**Requirements**:
- Given the search order `--env-file` > `PLAYWRIGHT_ENV_FILE` > `.fab-test/.env` > `./.env`, should be defined in one place and used by both `_credentials` and the Playwright config loader
- Given a repository with a root `.env` and no `.fab-test/.env`, should keep working unchanged (backward-compat constraint) — root stays supported, not deprecated
- Given both exist, should prefer `.fab-test/.env` and report which one supplied the credential in `fab-test auth status`
- Given `fab-test init`, should write `.fab-test/.gitignore` containing `.env`, so the secret is protected by fab-test's own scaffolding rather than by the consumer having the right root `.gitignore`
- Given `fab-test init`, should scaffold `.fab-test/.env.example` alongside it, replacing the root `.env.example` for new repositories
- Given a `.env` is found, should never echo its values to stdout, an envelope, the manifest, or telemetry (secrets constraint)
- Given the CLI is invoked from a subdirectory, should resolve the same file both callers resolve — the current cwd/repo-root split is fixed, not preserved

---

## Blast Radius

`power_bi_api._acquire_access_token` (task 1) and `resolve_item` (task 5) both have more
than one caller. Enumerate before editing, run each through the real CLI afterwards:

| Shared code | Callers to exercise |
|-------------|---------------------|
| `get_embed_context` / `_acquire_access_token` | `fab-test playwright`, `fab-test playwright-impact` (via the manifest path) |
| `resolve_item` | `resolve_report`, `resolve_semantic_model_dependents`, `fab-test dependencies` |
| `_build_config_from_args` | `--artifact` path, `--impact-manifest` path, bare `.env` path |
| `.env` discovery (task 8) | `_credentials.probe_credentials`, `_credentials.resolve_service_principal`, `playwright_validation.config.load_config`, `build_fabric_service_client`, `auth status`, `doctor` |
| metadata resolution (task 7) | `bpa`, `pbir`, `list`, `explain`, `doctor`, `config --show`, `run_analyzer.py` |
