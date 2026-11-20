# Fabric Data Agent Testing Epic

**Status**: 📋 PLANNED — 11 discovery decisions recorded 2026-10-04; decisions 3 and 10 rewritten and 12–16 added 2026-11-19 against [`aidd-command-grammar`](../.github/skills/aidd-command-grammar/SKILL.md). Supersedes PR #49.
**Goal**: A new `data-agent` analyzer that evaluates deployed Fabric Data Agents by running promptfoo with a packaged Python provider, following [fabric-data-agent-testing-template](https://github.com/clientfirsttech/fabric-data-agent-testing-template), with test suites authored through `fab-test data-agent tests init` and `tests lint`.

## Overview

WHY: Teams deploying Fabric Data Agents have no way to regression-test the agent's actual answers — whether it refuses irrelevant questions, returns the right figures, or holds a conversation — short of asking it by hand. The template repository proves the shape (promptfoo driving the agent's Assistants-compatible API), but it is a standalone Node project with a TypeScript provider, hand-built URLs, and its own CI parsing; nothing about it speaks fab-test's one contract. This epic ports the provider to promptfoo's Python contract (`call_api(prompt, options, context)`), ships it inside the fab-test package, gives people and agents `tests init` and `tests lint` to write and check a suite, and wires the run through the same envelope, exit codes, modes, HTML report, and telemetry as every other analyzer. A Data Agent only exists deployed, so every run is a service test: the suites beside each `*.DataAgent` folder supply the denominator while execution reaches the service. PR #49 built a first cut before the command grammar, feature flags, the `local`/`service` mode rename and the Core Module Split landed on `dev`; this epic ports what still fits (decision 16).

**Decisions** (1–11 recorded 2026-10-04 at discovery review; 3 and 10 rewritten and 12–16 proposed by Claude and accepted by the user 2026-11-19):

1. ✅ Analyzer name is **`data-agent`** with alias **`agent`** (registry key `data_agent`; the registry key, results folder, and envelope analyzer field agree).
2. ✅ The provider is **Python**, shipped inside the fab-test package and declared to promptfoo as `file://.../fabric_data_agent_provider.py` — a port of the template's `provider.ts`, not a dependency on it.
3. ✅ *(rewritten 2026-11-19; was a `promptfooconfig.yaml` inside the folder)* The suite lives **beside the item folder** as `<Item>.DataAgent.promptfoo.yaml`, because Fabric's Commit to Git deletes files inside an item folder that aren't part of its definition. The noun is `tests`; the suffix names the format, as pbir's `contract` is `.odcs.yaml`. The suite records `fabTestDataAgent: <logicalId>` from the item's `.platform` and pairs by it, not by name; fab-test strips the key from the config it hands promptfoo.
4. ✅ The agent URL is **resolved via the Fabric API** from the workspace + artifact name — this is a service test; users never hand-build `.../dataagents/{id}/aiassistant/openai` URLs (an explicit URL in config remains an escape hatch, not a requirement).
5. ✅ Auth is **service principal only** — the existing `build_azure_credential` env-SP chain; no `--interactive`, no device code, mirroring the template's client-credentials flow. Scope defaults to the template's `https://analysis.windows.net/powerbi/api/.default`, overridable via `FABRIC_SCOPE`.
6. ✅ v1 keeps **promptfoo-native assertions** as authored (`javascript`, `contains`, `regex`, …); LLM-graded rubrics are deferred until a judge-key story exists.
7. ✅ **Multi-turn conversations are in v1**: the template's `conversation`/`reset` thread-reuse vars, which force promptfoo `maxConcurrency: 1` / `workers: 1`.
8. ✅ **Never in `local`**; in `all` only when a workspace is configured (same rule as `sqldb-test`) — live LLM calls cost time and capacity.
9. ✅ Workspace enumeration over **5 agents** warns and stops; `--all` forces it (Service Targeting decision 9's semantics, lower threshold because each agent run is slow). In CI or `--format json`, the stop is an exit-`2` refusal naming `--all`, never a prompt.
10. ✅ *(rewritten 2026-11-19; was `fab-test data-agent init`, which collides with TARGET)* **`fab-test data-agent tests init`** writes the suite from the item's definition, asking which questions to test, and **`tests lint`** checks it without the service. No `.env.example`: `fab-test init` already scaffolds the credentials. A `playwright` authoring flow stays a plan.md task.
11. ✅ **Independent** of the blocked Promptfoo Skill Evaluation epic — this epic's promptfoo tool seam may incidentally help it, but neither blocks the other. The win32-arm64 limitation (`@libsql/win32-arm64-msvc` unpublished) is surfaced by `doctor`, not solved here.
12. ✅ **A bare run is `service`.** The suites are read from `--artifact-dir`, but nothing runs locally, so `fab-test data-agent` takes its workspace from `--workspace` → `FABRIC_WORKSPACE_ID` → `workspace:` in config, and exits `2` naming all three when none is set. This is the one analyzer-specific exception to `_mode.py`'s "a bare invocation stays local", and the banner's `source` says where the workspace came from.
13. ✅ **`tests lint` wraps `promptfoo validate`**, run with fab-test's pinned promptfoo on the config the run would generate, plus fab-test's own checks. Characterize promptfoo 0.124.0 first, as pql-test 0.2.1 was for `contract lint`.
14. ✅ **`tests init` never guesses an answer.** It suggests refusal tests from what the agent's data sources don't cover and questions from their selected tables, but every expected figure is `needs_human`, as `contract init` never guesses a fiscal year.
15. ✅ *(accepted by the user 2026-11-19)* **The noun is a real argparse subparser** for `data-agent tests` and for `pbir contract`. Data Agent must not copy pbir's argv check in `fab_test.py` (a known gap), so this epic fixes both in one place. The generic init/lint helpers move out of `_slicer_init_output.py` into a shared module now that a second caller exists (vision: no abstraction until the second caller). **Consistent, and fudgable by pointing:** a verb out of place (`fab-test pbir lint`), a plural noun (`contracts`) or a retired spelling (`data-agent init`) exits `2` naming the exact command meant — never runs it under a second spelling, and never passes having checked nothing, as `fab-test pbir lint` does today. An item really named `init` or `lint` still runs as a TARGET. The rule is a grammar Constraint, so every authoring flow inherits it.
16. ✅ **PR #49 is superseded, not rebased** (it conflicts in 21 files). Its provider, URL resolution and the wrapper's result mapping and redaction are ported onto `dev`'s layout; its `data-agent init`, registry and bootstrap edits, and raised module-budget ceilings are not.

---

## Promptfoo Tool Seam

**Status**: ✅ IMPLEMENTED 2026-10-06 (`archive_type: npm_package`, `platform_limitations`; Node floor is 22, not 18 -- promptfoo 0.124.0 declares `engines: node >= 22.22.0`).

Register promptfoo as a wrapped external tool so install, readiness, and provenance behave like every other wrapped tool.

**Requirements**:
- Given `analyzers.json`, should carry a `tool_install` entry for promptfoo (npm, pinned version, `requires_runtime: node >= 22`), a THIRD-PARTY.md row, and `_WRAPPED_TOOLS` registration.
- Given `fab-test doctor`, should report promptfoo readiness without running an eval, and on win32-arm64 should name the `@libsql/win32-arm64-msvc` platform limitation as the remediation rather than failing opaquely.
- Given a machine without Node, should exit `127` naming the runtime requirement, as the other Node-wrapped tools do.

---

## Python Provider Module

**Status**: ✅ 2026-11-19. `fabric_data_agent_provider.py` (323 lines, 97% covered by 20 tests in `tests/test_data_agent_provider.py`). Beyond PR #49: PR #49's provider could not load under promptfoo — 0.124.0's `wrapper.py` imports it with `spec_from_file_location(<stem>, path)`, no parent package, so its relative imports raised `ImportError` (reproduced); imports are now absolute and a test loads it the way promptfoo does. Credentials come from `resolve_service_principal` (aliases, `.fab-test/.env`, the incomplete-principal message) instead of `os.environ[...]` `KeyError`s, and a secret read from a `.env` file is redacted too. Credential errors, a 401 after one refresh, and a 403 are final (no retries) and name the fix; tokens are redacted from every error.

Port the template's `provider.ts` to promptfoo's Python provider contract, starting from PR #49's `fabric_data_agent_provider.py` and its tests.

**Requirements**:
- Given promptfoo invokes `call_api(prompt, options, context)`, should run the template's lifecycle — create assistant, create thread, post message, create run, poll until terminal (2 s interval, configurable timeout), read the last assistant message's text, delete the thread — against `{base_url}/...?api-version=2024-05-01-preview`, returning `{"output": text}` or `{"error": message}`.
- Given a token is needed, should acquire it via the client-credentials flow from `FABRIC_TENANT_ID`/`FABRIC_CLIENT_ID`/`FABRIC_CLIENT_SECRET` with the scope from decision 5, cache it in memory, and refresh 300 s before expiry; a partial service principal fails with the existing `IncompleteServicePrincipalError` remediation, never a fallback.
- Given a transient failure, should retry up to `max_retries` (default 3) with `retry_delay` sleeps before returning an `error` response; given a 401, should refresh the token once and then name a rejected token, as the service paths do.
- Given `vars.conversation` on a test case, should reuse the thread across turns keyed by base URL + conversation id; given `vars.reset`, should delete and recreate it; given thread-not-found, should evict the cached thread and recreate (decision 7).
- Given any output path — provider response, logs, envelope, telemetry — should never contain the token or client secret.
- Given the provider is pure Python in the package, should be unit-tested against a mocked token endpoint and agent API with no live service.

---

## Agent URL Resolution

Resolve a Data Agent's API URL from its name via the Fabric API (decision 4).

**Requirements**:
- Given a workspace and a Data Agent item name or GUID, should resolve the item via the Fabric items API and construct `https://api.fabric.microsoft.com/v1/workspaces/{ws}/dataagents/{id}/aiassistant/openai`, reusing the existing service-client/credential path — no new auth subsystem.
- Given an ambiguous or missing name, should exit listing the workspace's Data Agent items, never a raw HTTP error.
- Given an explicit URL in the suite, should use it unchanged (escape hatch, not requirement).
- Given `--dry-run`, should list the agents and resolved denominators without acquiring a token.

---

## Suite Pairing And Effective Config

One pairing rule that the run, `tests init` and `tests lint` all call, and the generated config promptfoo actually reads.

**Requirements**:
- Given `--artifact-dir`, should treat each `*.DataAgent` folder as one item and pair it with the `*.DataAgent.promptfoo.yaml` whose `fabTestDataAgent` equals the folder's `.platform` logicalId, and match the item to its deployed agent by the `.platform` `displayName`.
- Given an item with no paired suite, should be `skipped` with a remediation naming `fab-test data-agent tests init <item>`, never a batch failure; given two suites claiming one logicalId, should exit `2` naming both.
- Given a typed service target (`"Dev/Sales Agent"`) with no item folder to pair on, should take `--tests FILE`, which overrides pairing on every verb and on the run, as `--contract` does for pbir.
- Given a suite, should generate the effective config at run time with the packaged provider path, the resolved agent URL, `maxConcurrency: 1` when any test uses conversations, and `fabTestDataAgent` removed — users never reference the provider file or hand-build URLs.
- Given the template's `fabric_urls`/`vars.agent` shape in a suite, should honor it so a template-repo user migrates without rewriting tests.

---

## Analyzer Wrapper (`invoke_data_agent.py`)

Run `promptfoo eval --output results.json` and map results to the one contract, porting PR #49's mapping and redaction.

**Requirements**:
- Given promptfoo's `results.results[]`, should map each failed assertion (`success`/`pass`, `gradingResult.componentResults[].pass`) to a Finding and populate `test_results` in test shape (suite/test/passed/expected/actual); exit 0/1 is decided from findings per `_artifact_exit_code`.
- Given the envelope and native output, should write both under `<output_dir>/data_agent/<results_stem>/`, and attach the HTML report via `attach_report` before `write_envelope` so `--report`/`--open-report` work.
- Given promptfoo loads the provider by file path and imports `fab_test`, should run promptfoo with `PROMPTFOO_PYTHON` set to fab-test's own interpreter, and `--env-file` passed on as `PLAYWRIGHT_ENV_FILE`, the variable `resolve_service_principal` searches.
- Given any test uses `conversation`, should set the provider's `workers: 1` as well as `maxConcurrency: 1`: the thread cache lives in one Python worker's memory, and promptfoo 0.124.0 takes `config.workers` over `PROMPTFOO_PYTHON_WORKERS` and `-j`.
- Given missing credentials, should preflight-exit `127` naming the exact env vars and `fab-test auth status` before any promptfoo invocation; given a promptfoo crash or usage error, should write an error envelope — never report a prerequisite failure as test verdicts (the pytest-usage-error lesson).
- Given `ANALYZER_VERBOSITY=summary`/`-q`, should honor the QuietLine contract; given `--format json`, stdout stays one pure document.
- Given telemetry, should route to `fabric_dynamic_analysis` with artifact_type `DataAgent`, mode as a dimension, and no connection details.

---

## Registration And Mode Wiring

All analyzer-contract touch points, behind the feature flag, with decision 12's mode rule.

**Requirements**:
- Given the analyzer contract checklist, should register in `ANALYZER_REGISTRY`, `ANALYZER_SCOPES` (path + workspace, never desktop) and `_CLOUD_ANALYZERS` (`fab_test_registry.py`), `_COMMAND_BUILDERS` (`_command_builders.py`), readiness (`_readiness.py`), the parser (with the `agent` alias), `analyzers.json`, a pytest marker, and `conftest`'s marker maps — copying no known gap.
- Given the [Feature Flags epic](feature-flags-epic.md), should register the real builder and the `tests` verbs only when `is_enabled("data_agent")`; while `FAB_TEST_ENABLE_DATA_AGENT` is unset, `fab-test data-agent` / `agent`, with any arguments including `tests init`, is the disabled stub (exit `2`, "not enabled in this release") and `--help` is unchanged.
- Given `fab-test data-agent` (bare), should resolve mode `service` with the workspace from decision 12 and run each paired suite; given `"Dev.Workspace/Sales Agent"`, mode `service` for that agent; given `--workspace Dev` with no TARGET, enumerate the workspace's agents and pair each with a local item by display name (unpaired => `skipped`); given `local/NAME`, exit `2`.
- Given more than 5 enumerated agents, should warn and stop unless `--all`; in CI or `--format json`, an exit-`2` refusal naming `--all` (decision 9).
- Given `fab-test all`, should include `data-agent` only when a workspace is configured; given `fab-test local`, never (decision 8).
- Given the banner, envelope, `--dry-run`, `explain`, `-q` line, and telemetry, should surface `mode`/`source` exactly as the Service Targeting epic defines.

---

## Authoring Noun Dispatch

Make `tests` and `contract` real argparse subparsers of their analyzers (decision 15), and share the authoring helpers.

**Requirements**:
- Given `fab-test data-agent tests init|lint` and `fab-test pbir contract init|lint`, should dispatch through argparse, so `--help`, `fab-test help`, `list --format json` and `explain` name the verbs, and `fab_test.py`'s argv check and its known-gaps.md entry are removed.
- Given an item named `tests` or `contract`, should be reachable as `./tests` or `./contract`.
- Given a near miss — `fab-test pbir lint`, `fab-test pbir init Sales`, `fab-test pbir contracts init`, `fab-test data-agent init Sales` (or `agent`) — and no item by that name, should exit `2` with `did you mean: <the exact command>`, carrying the TARGET and flags as typed; given an item really named `init` or `lint`, should run it as a TARGET.
- Given `fab-test pbir lint` exits 0 today having checked nothing, should add a CHANGELOG line for the change to exit `2`.
- Given the generic helpers in `_slicer_init_output.py` (input and output flags, run-flag refusal, `can_ask`, `level`, `next_command`, `print_payload`), should move them to one shared module that both flows import, with pbir's tests unchanged.
- Given the blast-radius rule, should run the slicer contract walkthrough's commands unchanged through the installed console script.

---

## `fab-test data-agent tests init`

Write a starter suite from the item's definition (decisions 10 and 14), planned with `/command-grammar plan data-agent tests`.

**Requirements**:
- Given `tests init Sales.DataAgent` (or `--artifact Sales`), should write `Sales.DataAgent.promptfoo.yaml` beside the folder with `fabTestDataAgent` set, refusal tests, questions from each data source's selected tables, and one conversation pair, each test with a stable id.
- Given TARGET, `--artifact`, `--artifact-dir`, `--format` and `--tests FILE`, should read exactly as the run's (name, metavar, shared help from `_cli_utils`), with each default resolved flag → env → `fab-test.yml`/`pyproject.toml` → packaged.
- Given the definition's data sources and `aiInstructions`, should suggest each question, mark every expected answer `needs_human`, and never write a guessed figure.
- Given an existing suite, should append new tests and keep existing ids; changing or replacing one needs `--force`.
- Given `--questions`, should print every question with `suggested` and `needs_human` and stop (one document with `--format json`); given `--answers FILE`, should apply answers by question id.
- Given no TTY, CI, or `--format json` and a missing answer, should exit `2` before asking anything, naming `--questions` and `--answers`.
- Given `--dry-run`, should show the suite and write nothing.
- Given `-q`, should print `tests written added=N replaced=N kept=N unchanged=N PATH`; given the default, should add the next step `fab-test data-agent tests lint <TARGET>`; given `--format json`, should carry it as `next`.
- Given a run-only flag (`--report`, `--open-report`, `--telemetry`, `--timeout`, `--workspace`, `--all`, `--output-dir`), should exit `2` naming `fab-test data-agent`, never argparse's "unrecognized arguments"; given Ctrl-C, should exit `130` with no traceback.

---

## `fab-test data-agent tests lint`

Check a suite against its item without the service (decision 13).

**Requirements**:
- Given promptfoo 0.124.0, should characterize `promptfoo validate` first — its help, exit codes, JSON output, and whether it accepts unknown top-level keys and per-test `metadata` — and record the result in this epic before TDD.
- Given `tests lint Sales.DataAgent`, should find the suite by the run's pairing, build the effective config as the run does with a placeholder agent URL, run `promptfoo validate` on it, add fab-test's own checks (the suite reads, pairs with an item, has unique test ids, and holds no credential or hand-built agent URL), and exit 0 clean, 1 on findings, 2 when nothing pairs, 127 when promptfoo is missing.
- Given no TARGET, should lint every suite under `--artifact-dir`, with JSON `{ok, suites: [...], next}` either way and `next` null unless ok.
- Given any outcome, should write no file and no envelope.
- Given `-q`, the default, `-v` and `--format json`, should print one line per suite shaped like the run's, then name `fab-test data-agent <TARGET>` as the next step.
- Given both verbs, should run each under `-q`, the default, `-v`, `--format json`, a refused run-only flag, and (init only) `--dry-run`, `--questions` and `--answers` through the installed console script before review passes.

---

## Authoring Grammar Parity Test

The parser-driven test plan.md deferred until a second authoring flow landed.

**Requirements**:
- Given every authoring verb in the parser, should assert the shared input and output flags carry the run's metavars, help and config-resolved defaults, that run-only flags are refused, and that each verb is listed in `--help` and the fab-test skill — ratcheted like `tests/test_analyzer_contract_parity.py`, with `_KNOWN_GAPS` mirroring known-gaps.md.

---

## Document All Three Callers

**Requirements**:
- Given the human caller, should add `docs/DATA-AGENT-TESTS-WALKTHROUGH.md` modeled on the slicer walkthrough (save the agent, init, lint, run, break it, CI, opening with an init-to-CI flowchart), and update README and `docs/QUICK-VALIDATION.md` with the mode matrix, SP setup (workspace role + data-source access, per the template's README), and the 5-agent threshold.
- Given each flow's flag table, should add one to the fab-test skill's flags.md (both copies) and the walkthrough, with a row per flag and a column each for `tests init`, `tests lint` and the run.
- Given the pipeline caller, should add GitHub Actions and Azure DevOps snippets under `docs/examples/`, path-filtered on `**/*.DataAgent/**` and `**/*.DataAgent.promptfoo.yaml`, running `tests lint` before the run and relying on fab-test's exit codes.
- Given the agent caller, should update the fab-test skill in SudoLang (`SKILL.md` and the targeting/flags/credentials references), synced byte-for-byte to `src/fab_test/skill/`.
- Given a `src/` change in the beta series, should bump the version per vision.md's Versioning, re-stamp the skill frontmatter, and add a CHANGELOG entry via `aidd-log`.

---

## Verify Live Against A Real Data Agent

**Requirements**:
- Given `agent-sample-model` deployed and a service principal, should run bare mode, a typed service target, `--workspace` enumeration, and `tests init` → `tests lint` → the run through the installed console script, including a deliberately failing assertion, a multi-turn conversation, and the missing-credentials `127` path.
- Given the blast-radius rule, should exercise `all`, `list`, `explain`, `doctor`, `-q`, `--format json`, `--dry-run`, `--report`, and the >5-agent refusal with and without `--all`.
- Given the live run passes, should delete `data_agent` from `_FEATURES` and `FEATURE_SPELLINGS`, so the documented command exists (Feature Flags decision 3).

---

## AIDD Review

**Requirements**:
- Given the epic's diff, should be reviewed by a reviewer not anchored on the implementation, with aidd-review, aidd-python, aidd-module-budgets, aidd-tdd, aidd-analyzer-contract, aidd-command-grammar and aidd-polite-review, exercising the CLI on scratch copies.

---

## Quality Gates

**Requirements**:
- Given the whole repository, should pass `ruff check .`, `tests/test_complexity_budget.py`, and `tests/test_module_budget.py` — plan the new modules' seams up front rather than grow existing files at their ceilings.
- Given the full suite, should pass with `--cov --cov-fail-under=80` over `src/fab_test`, in CI's two halves.
- Given CI-dependent tests, should pass once with `GITHUB_ACTIONS=true CI=true`.
