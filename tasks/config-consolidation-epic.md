# Config Consolidation Epic

**Status**: 🚧 IN-PROGRESS
**Goal**: One front door for configuration and rule tuning, with a single precedence rule and no forked rule files.

## Overview
Adopting `fab-test` today means learning six configuration surfaces — `[tool.fab-test]` in `pyproject.toml`, `.github/metadata/analyzers.json`, `.github/metadata/environments.yml`, two large rule files, a `.env` file that must be passed explicitly with `--env-file`, and roughly twenty-eight environment variables. Worse, tuning a single Best Practice Analyzer rule means forking all 72 rules in a 56 KB `BPARules.json`, which then drifts from upstream forever. A user cannot answer "where did this value come from?" without reading source. This epic keeps every existing surface working but puts one optional config file in front of them, gives every setting the same precedence chain, makes rule changes additive overlays, and makes credentials discoverable instead of hand-wired.

Runs last of the three epics: the surfaces worth consolidating are only fully known once `doctor`, `list`, and `fab-test local` exist. Tasks are ordered so each builds on the previous.

---

## 1. Load and Discover `fab-test.yml` ✅

Introduce the config file itself, with nothing depending on it yet.

**Requirements**:
- Given a `fab-test.yml` at the repository root, then it is discovered and parsed into a plain dictionary.
- Given `--config PATH`, then that file is loaded instead of the discovered one.
- Given no config file exists, then an empty configuration is returned and behavior is identical to today.
- Given malformed YAML, then the CLI exits `2` naming the file and the parse error.

**Files**: new `_config.py`, `fab_test.py`
**Tests**: `pytest tests/test_config_loader.py`

---

## 2. Merge With `[tool.fab-test]` ✅

Fold the existing `pyproject.toml` table into the new loader so there is one in-memory configuration.

**Requirements**:
- Given both sources exist, then `fab-test.yml` wins and the CLI warns once about the duplicate source.
- Given only `[tool.fab-test]` exists, then every current setting resolves exactly as it does today.
- Given the merge, then `_load_pyproject_config` has one remaining caller so the logic is not duplicated.

**Files**: `_config.py`, `fab_test.py`
**Tests**: `pytest tests/test_config_loader.py -k merge`

---

## 3. Validate Keys With Suggestions ✅

Catch typos at the config layer instead of silently ignoring them.

**Requirements**:
- Given an unknown key, then the CLI exits `2` naming the key and the closest valid key.
- Given a key with the wrong type, then the CLI exits `2` naming the expected type.
- Given a valid config, then validation adds no measurable startup cost.

**Files**: `_config.py`
**Tests**: `pytest tests/test_config_loader.py -k unknown_key`

---

## 4. Centralize Precedence Resolution ✅

Route every setting through one resolver so precedence cannot drift per flag.

**Scope decision (2026-08-19)**: built `resolve_setting()` in `_config.py` with origin tracking, and made `_resolve_timeout`/`_apply_environment_default` thin wrappers around it. `jobs`, `format`, `artifact_dir`, and `output_dir` keep their existing (working) CLI > config > default behavior via baked-in argparse defaults rather than migrating to the same None-sentinel + resolver pattern — they have no env var today, and per user direction that migration is deferred to task 5, once `fab-test config --show` reveals what origin tracking actually needs for them.

**Requirements**:
- Given any setting, then precedence is CLI flag > environment variable > config file > packaged default, with no per-setting exceptions.
- Given the resolver, then `_resolve_timeout` and `_apply_environment_default` are replaced by calls into it rather than kept alongside it.
- Given a resolved value, then the resolver also returns its origin.

**Files**: `_config.py`, `fab_test.py`
**Tests**: `pytest tests/test_config_loader.py -k precedence`

---

## 5. Add `fab-test config --show` ✅

Answer "where did this value come from?" without reading source.

**Requirements**:
- Given `fab-test config --show`, then every effective setting prints with its value and origin (`flag`, `env:NAME`, `fab-test.yml:key`, `default`).
- Given `--format json`, then the same data is emitted as a single JSON document.
- Given a setting holding a secret, then the origin prints and the value is redacted.

**Files**: `fab_test.py`, `fab_test_summary.py`
**Tests**: `pytest -m fab_test tests/test_config_show.py`

---

## 6. Build the Rule Overlay Engine ✅

Apply deltas to a packaged ruleset instead of forking it.

**Requirements**:
- Given `rules.bpa.disable: [RULE_ID]`, then that rule is removed from the effective ruleset and all others stay upstream.
- Given `rules.bpa.severity: {RULE_ID: warning}`, then that rule's severity is overridden.
- Given `rules.bpa.extend: PATH`, then rules from that file are added.
- Given an overlay names a rule ID that does not exist upstream, then the CLI exits `2` listing the unmatched IDs.

**Files**: new `_rule_overlay.py`
**Tests**: `pytest tests/test_rule_overlay.py`

---

## 7. Wire Overlays Into BPA and PBIR ✅

Make the engine reachable from the analyzers that own rule files.

**Requirements**:
- Given overlays are configured, then the resolved ruleset is written to the run output directory and passed to the tool.
- Given a finding is produced, then the resolved ruleset it came from is traceable from the result.
- Given `--bpa-rules-path` or `--rules-path` is passed explicitly, then the overlay is ignored and the file is used verbatim.

**Files**: `fab_test_registry.py`, `_rule_overlay.py`
**Tests**: `pytest -m bpa` then `pytest -m pbir`

---

## 8. Auto-Discover `.env` ✅

Remove the `--env-file` ceremony from the common path.

**Verification note (2026-08-19)**: `load_config(env_file=None)` already fell back to `repo_root / ".env"` and every playwright wrapper's `--env-file` already defaulted to `None`, so auto-discovery, explicit-override precedence, and non-leakage into `to_test_case_dict()` all already worked -- but none of it had a regression test proving it. This task turned out to be test coverage: added 4 tests that would have caught a regression in any of the three requirements below.

**Requirements**:
- Given a `.env` at the repository root, then it is discovered without `--env-file`.
- Given `--env-file PATH`, then it overrides auto-discovery.
- Given a discovered `.env`, then its values never appear in stdout, the run manifest, or telemetry.

**Files**: `playwright_validation/config.py`
**Tests**: `pytest -m playwright tests/test_playwright_config.py -k env_file`

---

## 9. Fall Back to Ambient Azure Credentials ✅

Let a developer already signed in to Azure skip secrets entirely.

**Scope note**: requirement 3 ("the run manifest records the source name") is satisfied up to this task's stated file scope: `FabricServiceClient.credential_source` is a clean, tested public attribute (`"service-principal"` or `"ambient:DefaultAzureCredential"`) that never carries the token. Actually writing it into `analyzer-results/run.json` needs a `fab_test.py`/`_run_manifest.py` change (playwright's wrapper has no connection to `RunManifest` today), which is outside this task's listed files -- tracked as a follow-up in plan.md.

**Requirements**:
- Given no service-principal variables are set, then `DefaultAzureCredential` is attempted before failing.
- Given credentials cannot be resolved by any source, then the error names each accepted source in precedence order.
- Given ambient credentials are used, then the run manifest records the source name but no token.

**Files**: `playwright_validation/fabric_service_client.py`, `playwright_validation/config.py`
**Tests**: `pytest tests/test_fabric_service_client.py -k credential`

---

## 10. Add `fab-test init` ✅

Make the first config file something the CLI writes, not something the user researches.

**Ordering note (2026-08-19)**: this task's own requirement 3 needs `fab-test config --validate`, but that's task 11 -- a forward reference the epic's stated task order doesn't resolve. Did task 11 first so this task's own requirement can be genuinely verified rather than deferred.

**Requirements**:
- Given `fab-test init`, then a commented `fab-test.yml` and `.env.example` are created without overwriting existing files.
- Given a config already exists, then the CLI reports what exists and exits `0` with no changes.
- Given the scaffolded file, then `fab-test config --validate` passes against it unmodified.

**Files**: `fab_test.py`, new template resources
**Tests**: `pytest -m fab_test tests/test_config_init.py`

---

## 11. Publish a JSON Schema and `--validate` ✅

Give editors completion and CI a check.

**Requirements**:
- Given `fab-test config --validate`, then the config is checked against the schema and errors name the offending path.
- Given the schema, then it ships in the package and is referenced from the docs.
- Given the schema and the loader's key list, then a test asserts they agree so the two cannot drift.

**Files**: new `schemas/fab-test.schema.json`, `_config.py`
**Tests**: `pytest tests/test_config_loader.py -k schema`

---

## 12. Sweep Backward Compatibility ✅

Guarantee existing repositories keep working untouched.

**Finding (not fixed here -- outside this task's file scope)**: `resolve_setting`'s origin label is always `fab-test.yml:<key>` for a config-sourced value, even when the value actually came from `[tool.fab-test]` in `pyproject.toml` and no `fab-test.yml` exists at all -- `merged_file_config` merges both sources into one dict before `resolve_setting` ever sees it, losing which file a key came from. The resolved *value* is always correct; only the displayed origin string doesn't distinguish the two files. Revisit if this becomes confusing in practice (e.g. `fab-test config --show` misattributing a pyproject-sourced setting to a nonexistent fab-test.yml).

**Requirements**:
- Given a repository with only `[tool.fab-test]` and `analyzers.json`, then every current command produces the same results as before this epic.
- Given every documented environment variable, then a test asserts it still overrides the config file.
- Given a config value the CLI also receives as a flag, then a test asserts the flag wins.

**Files**: `tests/test_config_loader.py`, `tests/test_fab_test.py`
**Tests**: `pytest -m fab_test` then full `pytest`

---

## 13. Document for All Three Callers

Cover the agent, the human, and the pipeline together, per the documentation constraint in [vision.md](../vision.md).

**Requirements**:
- Given the `fab-test` skill, then it documents the config schema, the precedence chain, and the rule-overlay keys so an agent can edit config without reading source.
- Given README and QUICK-VALIDATION, then one precedence table appears in both, matching the skill exactly.
- Given a pipeline author, then a workflow snippet shows which settings belong in committed `fab-test.yml` versus repository secrets.
- Given `fab-test init`, then the file it scaffolds is the same one the docs describe, so documentation and generator cannot drift.

**Files**: `.github/skills/fab-test/SKILL.md`, `README.md`, `docs/QUICK-VALIDATION.md`
**Tests**: `pytest` (full suite before commit)

---

## Deferred — Shared Base Configuration

Cut from this epic under the [vision.md](../vision.md) simplicity constraint ("no abstraction until the second caller"). An `extends: PATH_OR_URL` key would require remote fetching, offline caching, and cycle detection — the most machinery in this epic for the least-proven need. Revisit when a second organization actually asks to inherit a house config; the origin reporting built in task 5 already provides the mechanism to show where an inherited value came from.
