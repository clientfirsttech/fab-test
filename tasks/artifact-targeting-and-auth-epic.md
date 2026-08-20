# Artifact Targeting and Auth Epic

**Status**: 🚧 IN-PROGRESS
**Goal**: Name any artifact — local file, running Desktop instance, or deployed workspace item — with one grammar, and answer "which identity am I about to use?" without reading source.

## Overview

`fab-test` cannot name what it is about to test. Targeting today is `--artifact-dir DIR` plus `--artifact STEM`, so a workspace-hosted artifact is not expressible at all, `fab-test all --artifact Sales` cannot say *only the semantic model*, and local-versus-remote is **inferred** from whether `--workspace-id` happens to be set rather than stated by the caller — an agent cannot tell from the command what will happen. Meanwhile `check_readiness` returns `ready: true, "no external tool required"` for `pql_test`, `pql_lint`, and `playwright`, so `fab-test doctor` reports a green light with zero credentials and no reachable workspace. Both gaps hit the same vision principle — *tell the caller how to fix it* — and both are already solved conventions in the tool `fab-test` wraps: `pql-test run-tests` accepts `local/Sales` and `"MyWorkspace.Workspace/Sales.SemanticModel"`, and ships `auth login|logout|status`. This epic adopts that grammar as `fab-test`'s own, and gives credentials a first-class read-only surface — **without** `fab-test` ever storing a token.

Two decisions fix the scope. Targeting is a **positional grammar over an internal `(workspace, name, type)` model**: the surface is what a user pastes from `pql-test` or the Fabric CLI, the internals stay flag-shaped so `fab-test.yml` and `--workspace-id` compose with it. Auth is **read-only plus delegation**: `auth status` reports the resolved identity chain, `auth login` mints nothing and instead runs the underlying tool's login or names the exact variables to set. `fab-test` owning a token cache was rejected as a fourth credential store on one laptop and a violation of *facade, not fork* — see Deferred.

**Sequencing update (2026-08-20)**: Config Consolidation closed 13/13, shipping the `.env` auto-discovery and `DefaultAzureCredential` fallback that tasks 7–9 were waiting on. Every task is now unblocked. That also makes task 6 immediately stale in one respect — its `_credential_source()` recognizes only service-principal variables and says so in a comment, so a developer signed in with `az login` is now told they are not ready when they are. Task 7 moves up to run next, ahead of tasks 2–5, because it closes that gap rather than merely adding to it.

---

## 1. Parse the Target Grammar ✅

Introduce a target parser with nothing wired to it yet, so the grammar can be pinned down before it has callers.

**Done (2026-08-20)**: `_target.py` with `parse_target`, `ResolvedTarget`, and `TargetError`. Scope is decided by the first path segment: an explicit path prefix (`./`, `../`, `/`, `C:`) wins outright, then the reserved `local/` scheme, then a `.Workspace` suffix, else path. That ordering gives `./local/Sales` as the escape hatch for a directory genuinely named `local`. `path` is populated only when the target contains a separator, so a bare `Sales.SemanticModel` stays a discovery filter rather than a location. `KNOWN_ARTIFACT_TYPES` is asserted against the `ANALYZER_REGISTRY` globs so the two cannot drift.

New `_target.py` turns one string into a `ResolvedTarget` dataclass of `scope` (`path` | `desktop` | `workspace`), `workspace`, `name`, `type`, and `path`. Parsing only — no filesystem access, no network.

**Requirements**:
- Given `./src/Sales.SemanticModel`, then the target parses as scope `path` with name `Sales` and type `SemanticModel`.
- Given a bare `Sales`, then the target parses as scope `path` with name `Sales` and no type, so the analyzer's own glob still selects the type.
- Given `local/Sales`, then the target parses as scope `desktop` with name `Sales`.
- Given `Sales Dev.Workspace/Sales.SemanticModel`, then the target parses as scope `workspace` with workspace `Sales Dev`, name `Sales`, and type `SemanticModel`.
- Given a workspace-qualified target whose item half carries no `.Type` suffix, then parsing fails naming the accepted forms — a deployed item cannot be found by name alone.
- Given a target with an unknown type suffix, then parsing fails listing the types `fab-test` knows.

**Files**: new `_target.py`
**Tests**: `pytest tests/test_target.py`

---

## 2. Accept a Positional Target for Local Scopes

Wire the parser to the two scopes that need no network, and make `--artifact` an alias rather than a second mechanism.

`_add_common_flags` gains an optional positional `TARGET`. `discover_artifacts` takes a `ResolvedTarget` instead of a bare `stem_filter`, so type-qualified selection stops being the accident it is today ([`fab_test_registry.py:137-142`](../src/fabric_ci_cd_dataops/scripts/fab_test_registry.py#L137-L142) already matches full names, undocumented).

**Requirements**:
- Given `fab-test bpa ./src/Sales.SemanticModel`, then only that artifact is analyzed.
- Given `fab-test all Sales.SemanticModel`, then the semantic model runs and `Sales.Report` is not selected.
- Given `fab-test pql-test local/Sales`, then the run binds to the matching running Desktop instance and no workspace ID is required.
- Given `local/Sales` and no matching Desktop instance, then the CLI exits `127` naming the artifact and telling the caller to open the `.pbip` in Power BI Desktop.
- Given `--artifact STEM`, then it resolves through the same parser and keeps working exactly as before.
- Given both a positional target and `--artifact`, then the CLI exits `2` rather than silently preferring one.
- Given no target at all, then discovery behaves identically to today.

**Files**: `fab_test.py`, `fab_test_registry.py`, `_target.py`
**Tests**: `pytest -m fab_test tests/test_target.py -k local`

---

## 3. Resolve Workspace-Qualified Targets

Turn a workspace *name* into the IDs the analyzers already accept.

[`resolver.py`](../src/fabric_ci_cd_dataops/scripts/playwright_validation/resolver.py) already resolves an item name to an ID *within* a workspace; only workspace-name-to-ID is missing, one `GET /v1/workspaces` call. A `workspace` key joins `_VALID_KEYS` in `_config.py` so the value can live in `fab-test.yml` and resolve through the precedence chain built in Config Consolidation task 4.

**Requirements**:
- Given `Sales Dev.Workspace/Sales.SemanticModel`, then the workspace name resolves to its ID and the item name to its ID before the analyzer is invoked.
- Given a workspace name matching no workspace the identity can see, then the CLI exits `1` naming the workspace and listing the visible ones.
- Given a workspace name matching more than one workspace, then the CLI exits `2` listing the candidate IDs so the caller can pass a GUID instead.
- Given a target that is already a GUID where a name is expected, then it is used verbatim with no lookup.
- Given `--workspace-id` and a workspace-qualified target that disagree, then the CLI exits `2` naming both.
- Given `workspace:` in `fab-test.yml`, then a bare `Sales.SemanticModel` target resolves against it, and a positional workspace-qualified target overrides it.

**Files**: `_target.py`, `_config.py`, `playwright_validation/resolver.py`
**Tests**: `pytest tests/test_target.py -k workspace`

---

## 4. Reject Unsupported Scopes Per Analyzer

Parse the grammar universally, then fail honestly where it cannot be honored.

Only `pql-test` and `playwright` can act on a deployed item. `bpa`, `pbir`, and `pql-lint` read files on disk; making them accept a workspace target would mean downloading the artifact first, which is `fabric-cicd-deployment`'s job and a stated non-goal in [vision.md](../vision.md). The registry gains a supported-scope set per analyzer.

**Requirements**:
- Given `fab-test bpa "Sales Dev.Workspace/Sales.SemanticModel"`, then the CLI exits `2` explaining that `bpa` reads files and naming the path and `local/` forms that work.
- Given each analyzer, then its supported scopes are declared in one place in the registry rather than checked ad hoc per command builder.
- Given `fab-test list`, then each row reports which scopes that analyzer accepts.
- Given a scope rejection, then no analyzer subprocess is started and no result envelope is written.

**Files**: `fab_test_registry.py`, `fab_test.py`
**Tests**: `pytest -m fab_test tests/test_target.py -k scope`

---

## 5. Report the Resolved Target

Make what `fab-test` decided visible, which is where the agent-caller value actually lands.

**Requirements**:
- Given `fab-test explain pql-test local/Sales`, then the output shows the resolved scope, workspace, name, and type alongside the command that would run.
- Given any run, then `run.json` records the resolved target including its scope, so a completed run says whether it hit a file, Desktop, or a workspace.
- Given `--format json`, then the resolved target is a structured object, not an interpolated string.
- Given a resolved workspace target, then `run.json` records the workspace and item IDs but no token or secret.
- Given `--dry-run`, then the resolved target prints and nothing executes.

**Files**: `fab_test.py`, `_run_manifest.py`, `fab_test_summary.py`
**Tests**: `pytest -m fab_test tests/test_list_explain.py -k target` then `pytest tests/test_run_manifest.py`

---

## 6. Stop Reporting Cloud Analyzers as Unconditionally Ready ✅

Fix the false green. Independently shippable — depends on no other task in this epic and on nothing in Config Consolidation.

**Done (2026-08-19)**: `_CLOUD_ANALYZERS` (`pql_test`, `playwright`, `playwright-impact`, `dependencies`) now route through `_cloud_readiness`, which reports the target it would use or names every accepted source. Added `desktop_ports()` to `_desktop.py` — the presence-only half of `detect_desktop_instances`, since the latter shells out to PowerShell to resolve which file is open and `check_readiness` is contractually forbidden from spawning a subprocess. Credential detection covers both accepted spellings of the client pair; the ambient-Azure source arrives with Config Consolidation task 9 and task 7 reports the full chain.

[`check_readiness`](../src/fabric_ci_cd_dataops/scripts/fab_test_registry.py#L454-L467) short-circuits to `ready: true, "no external tool required"` for every analyzer without an external binary, so `doctor` greenlights `pql-test` and `playwright` with no credentials and no workspace.

**Requirements**:
- Given an analyzer that needs a workspace or credentials and neither is resolvable, then `doctor` reports it not ready with remediation naming what to set.
- Given an analyzer that genuinely needs nothing beyond a file on disk (`pql-lint`), then `doctor` still reports it ready.
- Given `pql-test` and a running Desktop instance but no workspace, then `doctor` reports it ready via Desktop and says so in the reason.
- Given `--format json`, then the readiness rows keep the same four keys they have today so existing consumers do not break.

**Files**: `fab_test_registry.py`
**Tests**: `pytest -m fab_test tests/test_doctor.py`

---

## 7. Probe the Credential Chain

Report which identity `fab-test` would actually use, once there is a chain worth reporting.

**Unblocked (2026-08-20)**: Config Consolidation tasks 8 and 9 have landed, so the chain this reports on now exists — `build_client_from_env` in `playwright_validation/fabric_service_client.py` documents it as explicit arguments, then environment variables, then `.env`, then `DefaultAzureCredential`, with ambient auth attempted only when *no* service-principal variable is set so a half-configured principal is surfaced as the mistake it is. Runs next, ahead of tasks 2–5, since task 6 currently under-reports readiness for anyone signed in via `az login`.

**Requirements**:
- Given resolvable credentials, then the probe reports the source that won (`env`, `.env`, ambient Azure, Desktop) and the tenant.
- Given no resolvable credentials, then the probe names every accepted source in precedence order.
- Given a probe, then it never prints a secret, token, or client secret to stdout, the run manifest, or telemetry.
- Given a probe, then it acquires no token and makes no network call unless a workspace was named.
- Given a named workspace, then the probe reports whether that workspace is reachable with the resolved identity.

**Files**: `fab_test_registry.py`, `playwright_validation/config.py`
**Tests**: `pytest tests/test_auth.py -k probe`

---

## 8. Add `fab-test auth status`

Promote the credential probe to a first-class noun, so "which identity am I using?" has an obvious command.

**Requirements**:
- Given `fab-test auth status`, then the resolved identity source, tenant, and any named workspace's reachability print in a readable table.
- Given `--format json`, then the same data emits as a single JSON document on stdout with narration on stderr.
- Given no credentials at all, then the command exits `127` — the established code for a missing prerequisite — and names each accepted source.
- Given credentials resolve, then the command exits `0` and prints no secret in either format.
- Given `auth status`, then it reuses the task 7 probe rather than reimplementing resolution.

**Files**: `fab_test.py`, `fab_test_summary.py`
**Tests**: `pytest -m fab_test tests/test_auth.py -k status`

---

## 9. Add a Delegating `fab-test auth login`

Give the human a next step without `fab-test` becoming a credential store.

`auth login` mints and persists nothing. It resolves what the situation needs and either runs the underlying tool's login or prints the exact command or variables to set. This also settles a naming collision before it ships: `--env` in `fab-test` means *test environment label* (`DEV`, `PROD`), while `pql-test`'s `--environment` means *Azure cloud*. The sovereign-cloud selector is `--cloud` and never `--environment`.

**Requirements**:
- Given `fab-test auth login` and `pql-test` on PATH, then `pql-test auth login` is delegated to and its exit code is propagated.
- Given delegation, then the command it ran prints before running, so the caller can reproduce it without `fab-test`.
- Given no delegable tool, then the command names the `az login` invocation or the service-principal variables to set, and exits `127`.
- Given `auth login`, then `fab-test` writes no token, credential, or cache file of its own anywhere on disk.
- Given `--cloud`, then the sovereign cloud passes through to the delegated tool.
- Given `--env DEV`, then it still means the test environment label, asserted by a regression test so the two never merge.

**Files**: `fab_test.py`, `fab_test_registry.py`
**Tests**: `pytest -m fab_test tests/test_auth.py -k login`

---

## 10. Document for All Three Callers

Cover the agent, the human, and the pipeline together, per the documentation constraint in [vision.md](../vision.md). Use the `document` skill so the three cannot drift.

**Requirements**:
- Given the `fab-test` skill, then it documents the full target grammar, which scopes each analyzer accepts, and the `auth` subcommands with their exit codes, so an agent can target an artifact without reading source.
- Given README and QUICK-VALIDATION, then one target-grammar table appears in both, matching the skill exactly.
- Given a pipeline author, then a workflow snippet shows a workspace-qualified target with the workspace in `fab-test.yml` and credentials in repository secrets.
- Given the docs, then they state plainly that `fab-test` stores no credentials and which tool owns the token, so no reader looks for a `fab-test` token cache.
- Given `--env` versus `--cloud`, then the distinction is documented wherever either appears.

**Files**: `.github/skills/fab-test/SKILL.md`, `README.md`, `docs/QUICK-VALIDATION.md`, `docs/QUICKSTART-LOCAL.md`
**Tests**: `pytest` (full suite with coverage before commit)

---

## Deferred — Downloading Workspace Artifacts for Static Analyzers

Making `bpa`, `pbir`, and `pql-lint` accept a workspace target requires exporting the item definition from Fabric first. That is artifact movement, which [vision.md](../vision.md) assigns to `fabric-cicd-deployment` and lists under Non-Goals. Task 4 rejects the combination with a message naming the forms that work. Revisit only if a caller demonstrates a workflow where exporting inside `fab-test` beats deploying and pointing at the repository.

## Deferred — A `fab-test` Token Cache

Full `auth login|logout` parity with `pql-test`, `fab`, and `az` — persistent token storage, refresh, sovereign-cloud handling — was cut for two reasons. It makes `fab-test` a credential store, which is the largest possible surface against the secrets constraint in [vision.md](../vision.md); and it is the fourth token cache on a machine that already has three, duplicating what upstream maintains against the *facade, not fork* principle. Task 9's delegation gives the same ergonomics with none of the storage. Revisit if a caller needs an identity that no underlying tool can itself acquire.
