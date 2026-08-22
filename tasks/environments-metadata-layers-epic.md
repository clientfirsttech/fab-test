# Environments Metadata Layers Epic

**Status**: ✅ COMPLETED (5/5 tasks, 1 found and recorded)
**Goal**: `environments.yml` resolves through the same layers as every other metadata file, and a Playwright run with no environment says so instead of crashing.

## Overview

A consumer who installs `fab-test` from an index is told to put tuned metadata in
`.fab-test/metadata/`. The TestPyPI Release epic delivered that for the three files its
analyzers read — `BPARules.json`, `pbi-inspector-custom-rules.json`, `analyzers.json` —
and deliberately stopped there. `environments.yml` was left on the old path, hardcoded
`.github/metadata/environments.yml` in six separate places, so the one file a consumer is
most likely to need to override is the one file the override chain does not reach. The
same sweep found a live crash: `fab-test playwright --artifact X` without `--env` raises
`AttributeError` and prints a traceback, because the fallback chain reads a field that
does not exist. That is two vision principles at once — *tell the caller how to fix it*
for the crash, and *one contract* for the six paths.

`environments.yml` cannot take the packaged fallback the other four files take. It carries
workspace GUIDs and branch policy, so a copy baked into the wheel would silently aim a
`prod` deployment at whatever workspace happened to be packaged. This epic adds
`packaged=False` to the resolver **with** the callers that need it, rather than
speculatively, and centralizes it in one `resolve_environments_yml()` so no caller can get
it wrong.

**Provenance**: the work resumes commit `d4b27bf` on the `refactor/metadata-layers`
worktree, preserved at tag `wip/metadata-layers-d4b27bf`. That commit built a competing
`_metadata.py` while another session shipped one to `dev`; the two sessions converged by
cross-session message on keeping `dev`'s tested resolver and rebasing these call sites
onto it. Its resolver half is dropped. Everything below is the half that survived, plus
the crash fix that had no epic to live in.

---

## 1. Refuse a Playwright Run With No Environment ✅

`fab-test playwright --artifact X` with no `--env` and no `FABRIC_ENVIRONMENT` prints a
traceback. [`invoke_playwright.py:167`](../src/fabric_ci_cd_dataops/scripts/invoke_playwright.py#L167)
resolves the environment as `args.environment or config.environment or "dev"`, and
[`PlaywrightValidationConfig`](../src/fabric_ci_cd_dataops/scripts/playwright_validation/config.py#L74-L88)
has no `environment` field — so the middle term raises `AttributeError` and the `"dev"`
fallback behind it is unreachable. Only a truthy `args.environment` short-circuits past
it, which is why passing `--env` has always hidden this.

First because it is independent of everything below, ships alone, and is the only live
crash in the set.

**Requirements**:
- Given `--artifact` and no environment from any source, should raise `ServiceResolutionError` naming `--env`, `FABRIC_ENVIRONMENT`, and `environment:` in `fab-test.yml`
- Given no environment, should report that before building a service client, so the caller is not told about a credential when the problem is a missing flag
- Given the error reaches the wrapper, should exit 1 with one `::error::` line and no traceback
- Given `--env` or `FABRIC_ENVIRONMENT` is set, should behave exactly as before

**Files**: `invoke_playwright.py`, `tests/test_invoke_playwright.py`

**Done (2026-08-21)**: the guard raises before `build_fabric_service_client`, so the
missing flag is reported instead of a credential. Proven both ways against both trees:
the three tests fail on `dev` -- one with `AttributeError: 'PlaywrightValidationConfig'
object has no attribute 'environment'`, the other two with a live
`ClientAuthenticationError` from a real call to `login.microsoftonline.com`, which is
the wrong problem reported at the cost of a network round trip -- and pass here.
Verified through the real entry point: one `::error::` line, exit 1, no traceback.

---

## 2. Teach the Resolver the Safety It Cannot Express ✅

`dev`'s `resolve_metadata(relative, repo_root) -> tuple[Path, str]` has no way to say
"this file has no packaged default". Add it additively, with the callers from task 3 that
justify it — not ahead of them.

Returning a `NamedTuple` rather than a plain tuple is a strict superset: `resolved, origin
= ...` keeps working for the three existing callers, `.path` / `.layer` read better than
indexing at the six new ones, and `__fspath__` lets it drop straight into `open()`.

**Requirements**:
- Given a relative path and `packaged=False`, should search the two repository layers only and never return the packaged path
- Given no layer supplies a file and `packaged=False`, should raise `MetadataNotFoundError` naming every candidate path, not only the last one tried
- Given the existing three callers unpack two values, should keep working unchanged
- Given a caller needs `environments.yml`, should reach it through one `resolve_environments_yml()` that fixes `packaged=False` in a single place
- Given the result is passed to `open()` or `Path()`, should work without an attribute access

**Files**: `_metadata.py`, `tests/test_metadata_resolution.py`

**Done (2026-08-21)**: fields named `path` / `origin`, not `path` / `layer` as the
handoff suggested -- `origin` is the word dev's module, its tests, and `config --show`
already use, and one word per concept beats matching the suggestion. Eight tests added
to their file rather than a competing one, including a guard that the three existing
callers' two-value unpacking still works.

---

## 3. Resolve `environments.yml` Through the Repository Layers ✅

Six sites hardcode `.github/metadata/environments.yml`. All six move to
`resolve_environments_yml()`. An explicit path argument still wins everywhere it exists
today — callers and tests pass one.

**Requirements**:
- Given `.fab-test/metadata/environments.yml` exists, should be preferred over the `.github/metadata/` copy
- Given only `.github/metadata/environments.yml` exists, should resolve to it without a warning — an absent override is a default
- Given neither exists, should fail naming both places the file could go
- Given a caller passes an explicit path, should use it unchanged
- Given no layer has the file, should never fall back to a packaged copy

**Files**: `deploy.py`, `check_promotion_safety.py`, `generate_fabric_cicd_config.py`, `validate_environments_schema.py`, `validate_environments_yaml.py`, `playwright_validation/resolver.py`

**Blast radius** (vision.md): six callers. Each was run through its real entry point in a
temp directory, both with `.fab-test/metadata/environments.yml` present and with neither
layer, rather than only the Playwright one that prompted the change:

| Caller | Override honoured | Absent names both places |
|--------|-------------------|--------------------------|
| `validate-environments-yaml` (console script) | exit 0, path printed | exit 1 |
| `validate_environments_schema` | resolved and validated | exit 1 |
| `generate_fabric_cicd_config` | `workspace_id: ws-from-fab-test-layer` written | exit 1 |
| `deploy` | config read, bogus env rejected before deploying | exit 1 |
| `check_promotion_safety` | config read, chain evaluated | `FileNotFoundError` |
| `playwright_validation/resolver` | workspace resolved | `ServiceResolutionError` |

**Done (2026-08-21)**: `deploy` needed a real artifact directory before it reaches config
loading at all, so the first attempt at its absent-file path proved nothing -- artifact
validation runs first and exits on its own message. Worth knowing for the next person who
verifies that path.

---

## Found, Not Fixed -- Emoji Output Crashes a Windows Console

`validate_environments_schema` prints `
🔍 Validating: {path}
` on the success path.
On a default Windows console (cp1252) that raises `UnicodeEncodeError` and exits with a
traceback, so the validator cannot report a *valid* file -- only an invalid one, whose
output happens to avoid the glyph. Confirmed identical on `dev`, so it is pre-existing
and not a regression from task 3; found only because the blast-radius rule sent every
caller through its real entry point.

Recorded rather than fixed: it is unrelated to metadata resolution, and unplanned scope
entering a planned epic is what left task 1's crash fix homeless in the first place. It
needs its own decision -- most likely `PYTHONIOENCODING`/`reconfigure` at the entry
points, or dropping decorative glyphs from machine-facing output, which is a wider call
than this epic should make.

---

## 4. Close the Last Two Metadata Loaders ✅

Recorded on `dev` as *Deferred From Metadata Packaging* in
[the TestPyPI Release epic](testpypi-release-epic.md). Neither is in `[project.scripts]`
— both are workflow-invoked and always run inside a checkout — so neither blocks a `pip`
consumer. Worth fixing, not urgent, and cheap once task 2 lands.

**Requirements**:
- Given `detect_changes.py` holds a fourth copy of the artifact-map loader that exits 1 when the file is absent, should resolve through the shared metadata layers like the other three
- Given `run_analyzer.py` defaults `--metadata-path` to a relative `.github/metadata/analyzers.json`, should resolve to a path that can exist in a wheel

**Files**: `_metadata.py`, `_artifact_types.py`, `detect_changes.py`, `run_analyzer.py`

**Done (2026-08-21)**: wider than "delegate to `_artifact_types`", because delegating
alone would not have satisfied the requirement. `_artifact_types` predates the layer work
and read `.github/metadata/` directly, so `.fab-test/metadata/artifact-map.json` was
ignored everywhere -- not just in `detect_changes`. It now resolves through `_metadata`
like the other four files, which is the actual "shared metadata layers" the requirement
asked for.

Verified through real entry points. A temp directory whose override map declares
`.KqlDatabase` parses `MyWs.Workspace/Thing.KqlDatabase`; the same target in a directory
with no override is rejected against the nine packaged types. `detect_changes` with no map
now falls back and proceeds, where `dev` exits 1 -- run side by side to confirm.

`tests/test_detect_changes.py::test_missing_map_exits` asserted the exit this task
removes, so it was rewritten rather than left: a test that pins the behaviour a
requirement changes is the requirement's problem, not the test's.

---

## 5. Document for All Three Callers ✅

**Requirements**:
- Given an agent reads a skill, should find `.fab-test/metadata/environments.yml` documented alongside the rulesets, and the new Playwright environment error with its remediation
- Given a human reads the README, should learn where to put `environments.yml` without reading source
- Given a pipeline author needs YAML, should get a copy-pasteable snippet that does not hand-derive the metadata path
- Given the docs land, should not collide with the TestPyPI Release epic's own tasks 4-8 in the shared checkout

**Files**: `.github/skills/fab-test/SKILL.md`, `README.md`, `docs/QUICK-VALIDATION.md`

**Done (2026-08-21)**: nothing documented `.fab-test/metadata/` before this -- the TestPyPI
Release epic shipped the mechanism and its own docs task had not landed yet, so all three
surfaces were describing a layout the code no longer had.

- **Agent**: a *Metadata files and where they come from* section in the skill -- the layer
  table, which files have a packaged fallback and which does not, and both new error messages
  verbatim with their exit code.
- **Human**: a *Where metadata lives* subsection in the README showing the directory to
  create, and why `environments.yml` is the one file with no shipped default.
- **Pipeline**: an *Overriding metadata in a pipeline* snippet -- no path flags, plus
  `validate-environments-yaml` as an early gate and `config --show --format json` to prove
  which ruleset is in force.

Both doc claims were checked against the running CLI rather than the source: `config --show
--format json` does report `rules.bpa`/`rules.pbir` with `origin`, and it covers rulesets
only -- not `analyzers.json`, `artifact-map.json`, or `environments.yml` -- so the sentence
says "ruleset", which is all it can honestly claim.

---

## Retrospective

**A finding deferred by everyone is a finding lost.** Task 1 fixed a live crash that both
sessions had already seen and both had correctly ruled out of their own epics -- once as
unplanned scope, once as superseded. Neither was wrong, and the result was still that the only
`AttributeError` on `dev` was recorded in no epic, no issue, and no test. It survived because a
commit message mentioned it in passing. The habit worth keeping is the *Found, Not Fixed*
section below: out of scope has to mean written down somewhere, not just not-here.

**"Delegate to the module that already does this" was not enough.** Task 4 looked like
replacing a duplicate loader with a one-line call. The module it delegated to, `_artifact_types`,
predated the layer work and read `.github/metadata/` directly -- so the documented
`.fab-test/` override had been silently doing nothing for the artifact map, in every caller.
Reading the delegate rather than trusting its name turned a tidy-up into the fix the
requirement actually asked for.

**Blast radius earned its place in vision.md again.** Running all six callers for real, rather
than only the Playwright one that prompted the change, is what surfaced the emoji crash below
and the fact that `deploy` validates its artifact path before it ever loads config -- so the
obvious way to test its missing-file path proves nothing.

**Tooling can lie about test results.** `rtk`'s pytest summary reported `No tests collected`
for runs that had actually collected and failed tests, and reported nothing collected for a
`-m playwright` selection that collected eight. Every red/green claim here was read from the
raw log or an unfiltered run. A wrapper that summarises test output is a wrapper that can
report a pass that did not happen.

---

## Constraints Carried From the Handoff

- Do not push to `dev` without a heads-up — another session is working the TestPyPI
  Release epic's tasks 4-8 in the shared checkout, and `dev` currently has its
  uncommitted publish-workflow changes.
- The shared editable install redirects imports to the shared checkout, so this
  worktree's tests need `PYTHONPATH` pointed at its own `src/`, or its own venv.
- Extend `dev`'s `test_metadata_resolution.py` rather than adding a competing file.
