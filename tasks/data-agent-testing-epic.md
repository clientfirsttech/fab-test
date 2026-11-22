# Fabric Data Agent Testing Epic

**Status**: 🔧 IN PROGRESS — Reviews 1 and 2 done 2026-11-21; docs, the parity test and the blast-radius pass remain. 11 discovery decisions recorded 2026-10-04; decisions 3 and 10 rewritten and 12–16 added 2026-11-19 against [`aidd-command-grammar`](../.github/skills/aidd-command-grammar/SKILL.md). Supersedes PR #49.
**Goal**: A new `data-agent` analyzer that evaluates deployed Fabric Data Agents by running promptfoo with a packaged Python provider, following [fabric-data-agent-testing-template](https://github.com/clientfirsttech/fabric-data-agent-testing-template), with test suites authored through `fab-test data-agent tests init` and `tests lint`.

## Overview

WHY: Teams deploying Fabric Data Agents have no way to regression-test the agent's actual answers — whether it refuses irrelevant questions, returns the right figures, or holds a conversation — short of asking it by hand. The template repository proves the shape (promptfoo driving the agent's Assistants-compatible API), but it is a standalone Node project with a TypeScript provider, hand-built URLs, and its own CI parsing; nothing about it speaks fab-test's one contract. This epic ports the provider to promptfoo's Python contract (`call_api(prompt, options, context)`), ships it inside the fab-test package, gives people and agents `tests init` and `tests lint` to write and check a suite, and wires the run through the same envelope, exit codes, modes, HTML report, and telemetry as every other analyzer. A Data Agent only exists deployed, so every run is a service test: the suites beside each `*.DataAgent` folder supply the denominator while execution reaches the service. PR #49 built a first cut before the command grammar, feature flags, the `local`/`service` mode rename and the Core Module Split landed on `dev`; this epic ports what still fits (decision 16).

**Decisions** (1–11 recorded 2026-10-04 at discovery review; 3 and 10 rewritten and 12–16 proposed by Claude and accepted by the user 2026-11-19; 17–21 made by Claude at the user's request 2026-11-21 from Review 1, on security and OWASP grounds):

1. ✅ Analyzer name is **`data-agent`** with alias **`agent`** (registry key `data_agent`; the registry key, results folder, and envelope analyzer field agree).
2. ✅ The provider is **Python**, shipped inside the fab-test package and declared to promptfoo as `file://.../fabric_data_agent_provider.py` — a port of the template's `provider.ts`, not a dependency on it.
3. ✅ *(rewritten 2026-11-19; was a `promptfooconfig.yaml` inside the folder; location superseded 2026-11-21 by decision 22, `fab-tests/data-agent/`)* The suite lives **beside the item folder** as `<Item>.DataAgent.promptfoo.yaml`, because Fabric's Commit to Git deletes files inside an item folder that aren't part of its definition. The noun is `tests`; the suffix names the format, as pbir's `contract` is `.odcs.yaml`. The suite records `fabTestDataAgent: <logicalId>` from the item's `.platform` and pairs by it, not by name; fab-test strips the key from the config it hands promptfoo.
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
17. ✅ *(Review 1, decided 2026-11-21 on OWASP A01/A10/A02)* **The bearer token only goes to Fabric hosts.** Before every request, including each poll, the provider checks that the host is `https`. The host must be `api.fabric.microsoft.com` or end in `.fabric.microsoft.com` or `.powerbi.com`. The provider never follows a redirect; a 3xx is an error naming the target host. `thread_id` and `run_id` are URL-quoted. Any other host is allowed only by `FAB_TEST_DATA_AGENT_ALLOWED_HOSTS`, read from the caller's environment and never from the suite or `fab-test.yml`. A suite can't widen where the token goes, because whoever writes the suite controls its URL.
18. ✅ *(Review 1, decided 2026-11-21; resolves lint against decision 4)* **Lint and run apply one URL rule.** An explicit `base_url` or `fabric_urls` on an allowed host is a **warning** in lint: the escape hatch still works, and a template user can still migrate. A host that isn't allowed is a **finding** (exit 1) in lint and a refusal in the run, with the same message. Credential keys in a suite stay findings.
19. ✅ *(Review 1, decided 2026-11-21 on A02/A08, least privilege)* **promptfoo's environment carries no secret.** The wrapper removes `FABRIC_CLIENT_SECRET` and its aliases from the environment it hands promptfoo. It also removes `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID` and their aliases. The provider reads the principal from the credential file: the caller's `--env-file` when given, or else a temp file the wrapper writes in a private `mkdtemp` directory and deletes in `finally`. This keeps the secret out of promptfoo's `{{ env.* }}` templating, its logs and casual `process.env` reads. It doesn't sandbox a hostile suite, which could still read the file. So the residual risk is documented: **a suite is code. Run it only from trusted branches, never from `pull_request_target` or fork PRs that carry secrets.**
20. ✅ *(Review 1, decided 2026-11-21; revised the same day at the user's question)* **Telemetry carries the redacted envelope, answers included, like every analyzer.** The destination is the team's own opt-in Eventhouse or Lakehouse, not a third party. Every analyzer already embeds its redacted envelope as `results`, including sqldb-test and pql-test actuals. Answer history is what makes drift visible. Stripping it would be a one-off exception that removes the trail's main value. The residual risk (A01): Eventhouse readers see answers drawn with the service principal's access, which may exceed theirs. Document it beside the telemetry setup: grant the telemetry database to the same audience as the agent's data sources. Never send tokens, secrets or credentials; tests assert the table, `artifact_type: DataAgent`, the mode dimension and the absence of secrets.
21. ✅ *(Review 1, decided 2026-11-21)* **The `all` banner stays the session's mode.** Each analyzer row shows its own `mode`/`source`, so `data-agent` reads `mode=service` inside an `all` run. This keeps Service Targeting's banner meaning without adding a `mixed` value.
22. ✅ *(proposed 2026-11-21 after the user couldn't find two suites, accepted the same day as recommended: `fab-tests/` at the repo root with a subfolder per flow, pbir contracts included; "we need a non-blocking (with Fabric Git Integration) folder for the tests so it's easy to reference")* **Test files get their own folder, outside the Git-connected one.**
    - **Where:** `fab-tests/` at the repo root by default, one subfolder per flow (`fab-tests/data-agent/agent-sample-model.DataAgent.promptfoo.yaml`, `fab-tests/pbir/Sales.Report.odcs.yaml`).
    - **Configurable:** `tests_dir:` in `fab-test.yml` and `--tests-dir`, resolved flag → env → config → packaged, like every input.
    - **Pairing:** still by logicalId, so a file's folder never matters. Discovery reads `tests_dir` as well as `--artifact-dir`, so suites next to their item keep working.
    - **init:** writes a new suite to `tests_dir`, extends an existing one where it already lives, and always prints the path.
    - **Why outside the connected folder:** per Microsoft Learn (Git integration, "Considerations and limitations"), Commit to Git deletes files inside an item folder, and files outside item folders aren't deleted. But a Git subfolder becomes a workspace folder, and "empty folders in Git are deleted automatically". So a `tests/` subfolder inside the connected folder risks deletion, while a folder outside it is never touched. The CI/CD best-practices page recommends keeping non-Fabric project files outside the Git folder.
    - **Scope:** covers pbir's `contract` as well, since one rule keeps every authoring flow alike (aidd-command-grammar). Existing files are moved with `git mv`; nothing is regenerated.
    - **Done 2026-11-21.**
      - **Code:** `_tests_dir.py` holds the rule (`tests_dir`, `flow_dir`, `search_roots`). `fab-tests/` is anchored to the named item's repository, or the artifacts' when no item is named, never to the caller's directory. A scratch copy therefore never reads the repository's own files, which claim the same items. A named item outside `--artifact-dir` is searched for beside itself.
      - **Flags and config:** `--tests-dir` is on both runs and all four authoring verbs. `tests_dir` is in `_VALID_KEYS` and the JSON schema.
      - **Moved:** this repo's contract and suite, with `git mv`.
      - **Updated:** messages, README, the slicer guide and walkthrough, both skill copies, the grammar skill, checklist and known-gaps, and the story map. Authoring-grammar decision 7 is marked superseded.
      - **Tests:** 10 in `tests/test_tests_dir.py`; full suite 3637 passed.
      - **Live:** `pbir` paired `fab-tests\pbir\…odcs.yaml`, and `data-agent` lint and run paired `fab-tests\data-agent\…` and passed.
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

**Status**: ✅ 2026-11-19. `fabric_data_agent_provider.py` (now 441 lines, tested by `tests/test_data_agent_provider.py` and `tests/test_data_agent_provider_failures.py`, 37 tests). The package shim `src/fab_test/fabric_data_agent_provider.py` is the path promptfoo loads. Beyond PR #49: PR #49's provider could not load under promptfoo — 0.124.0's `wrapper.py` imports it with `spec_from_file_location(<stem>, path)`, no parent package, so its relative imports raised `ImportError` (reproduced); imports are now absolute and a test loads it the way promptfoo does. Credentials come from `resolve_service_principal` (aliases, `.fab-test/.env`, the incomplete-principal message) instead of `os.environ[...]` `KeyError`s, and a secret read from a `.env` file is redacted too. Credential errors, a 401 after one refresh, and a 403 are final (no retries) and name the fix; tokens are redacted from every error.

Port the template's `provider.ts` to promptfoo's Python provider contract, starting from PR #49's `fabric_data_agent_provider.py` and its tests.

**Requirements**:
- Given promptfoo invokes `call_api(prompt, options, context)`, should run the template's lifecycle — create assistant, create thread, post message, create run, poll until terminal (2 s interval, configurable timeout), read the last assistant message's text, delete the thread — against `{base_url}/...?api-version=2024-05-01-preview`, returning `{"output": text}` or `{"error": message}`.
- Given a token is needed, should acquire it via the client-credentials flow from `FABRIC_TENANT_ID`/`FABRIC_CLIENT_ID`/`FABRIC_CLIENT_SECRET` with the scope from decision 5, cache it in memory, and refresh 300 s before expiry; a partial service principal fails with the existing `IncompleteServicePrincipalError` remediation, never a fallback.
- Given a transient failure, should retry up to `max_retries` (default 3) with `retry_delay` sleeps before returning an `error` response; given a 401, should refresh the token once and then name a rejected token, as the service paths do.
- Given `vars.conversation` on a test case, should reuse the thread across turns keyed by base URL + conversation id; given `vars.reset`, should delete and recreate it; given thread-not-found, should evict the cached thread and recreate (decision 7).
- Given any output path — provider response, logs, envelope, telemetry — should never contain the token or client secret.
- Given the provider is pure Python in the package, should be unit-tested against a mocked token endpoint and agent API with no live service.
- Given promptfoo starts a fresh persistent Python worker, should load the packaged provider and run the suite rather than failing to import fab-test.

---

## Agent URL Resolution

**Status**: ✅ 2026-11-19 for resolution (`_data_agent_resolution.py`, 8 tests); the explicit-URL escape hatch is the provider's `base_url` and the wrapper honors it, and `--dry-run` belongs to the wrapper and registration tasks. Reuses `resolve_item`, whose no-match message already lists the workspace's agents, so PR #49's extra wrapper for that is dropped. Adds what Data Agents need: a GUID resolves by id, `.DataAgent` is stripped here because the shared suffix list has none, and two agents sharing a name are listed with their ids and a "pass the GUID" remedy instead of "Sales Agent, Sales Agent".

Resolve a Data Agent's API URL from its name via the Fabric API (decision 4).

**Requirements**:
- Given a workspace and a Data Agent item name or GUID, should resolve the item via the Fabric items API and construct `https://api.fabric.microsoft.com/v1/workspaces/{ws}/dataagents/{id}/aiassistant/openai`, reusing the existing service-client/credential path — no new auth subsystem.
- Given an ambiguous or missing name, should exit listing the workspace's Data Agent items, never a raw HTTP error.
- Given an explicit URL in the suite, should use it unchanged (escape hatch, not requirement).
- Given `--dry-run`, should list the agents and resolved denominators without acquiring a token.

---

## Suite Pairing And Effective Config

**Status**: Implemented 2026-11-19 in `_data_agent_suite.py`. Shared logicalId pairing, duplicate
claim refusal, explicit `--tests`, packaged-provider injection, native/template config preservation,
and conversation concurrency are covered. Malformed config values are refused rather than silently
replaced with defaults. The current run accepts inline test mappings; external
test-file loading is not implemented. promptfoo 0.124.0 accepts the effective config and per-test
`metadata.id` through `validate config --config FILE` (real-tool test); bare `validate` is a command
group, not the validation invocation. Its help offers no JSON output flag.
On Windows with Node 26.1.0, one CI-mode validation ended in a libuv shutdown assertion
after printing "Configuration is valid"; a same-environment focused rerun passed.
The lint task must verify clean exit behavior on its supported CI runtime, not treat
that success-shaped log as a successful validation.

One pairing rule that the run, `tests init` and `tests lint` all call, and the generated config promptfoo actually reads.

**Requirements**:
- Given `--artifact-dir`, should treat each `*.DataAgent` folder as one item and pair it with the `*.DataAgent.promptfoo.yaml` whose `fabTestDataAgent` equals the folder's `.platform` logicalId, and match the item to its deployed agent by the `.platform` `displayName`.
- Given an item with no paired suite, should be `skipped` with a remediation naming `fab-test data-agent tests init <item>`, never a batch failure; given two suites claiming one logicalId, should exit `2` naming both.
- Given a typed service target (`"Dev/Sales Agent"`) with no item folder to pair on, should take `--tests FILE`, which overrides pairing on every verb and on the run, as `--contract` does for pbir.
- Given a suite, should generate the effective config at run time with the packaged provider path, the resolved agent URL, `maxConcurrency: 1` when any test uses conversations, and `fabTestDataAgent` removed — users never reference the provider file or hand-build URLs.
- Given the template's `fabric_urls`/`vars.agent` shape in a suite, should honor it so a template-repo user migrates without rewriting tests.

---

## Analyzer Wrapper (`invoke_data_agent.py`)

**Status**: Implemented 2026-11-19. Real promptfoo 0.124.0 eval with an echo Python provider
verifies pass/fail result mapping without live agent calls; the installed console script is
exercised under default, `-q`, `-v`, JSON, `--report`, and CI-suppressed `--open-report`.
Native output is captured temporarily and persisted redacted, as are the effective config,
envelope and report. `--no-cache --no-write --no-share` prevent upstream cache/database/share
copies; promptfoo's config directory is isolated per run. The wrapper passes its own interpreter
and the credential-file override, and pins conversation workers to one.
The installed-console timeout regression confirms the wrapper writes its error envelope before
the outer CLI deadline. Latest focused verification: 172 checks pass with `CI=true` and
`GITHUB_ACTIONS=true`, including the timeout, config guards, registration, ratchets and skill sync;
whole-repository ruff is clean. Live-agent verification remains pending below.

Run `promptfoo eval --output results.json` and map results to the one contract, porting PR #49's mapping and redaction.

**Requirements**:
- Given promptfoo's `results.results[]`, should map each failed assertion (`success`/`pass`, `gradingResult.componentResults[].pass`) to a Finding and populate `test_results` in test shape (suite/test/passed/expected/actual); exit 0/1 is decided from findings per `_artifact_exit_code`.
- Given the envelope and native output, should write both under `<output_dir>/data_agent/<results_stem>/`, and attach the HTML report via `attach_report` before `write_envelope` so `--report`/`--open-report` work.
- Given promptfoo loads the provider by file path and imports `fab_test`, should run promptfoo with `PROMPTFOO_PYTHON` set to fab-test's own interpreter, and `--env-file` passed on as `PLAYWRIGHT_ENV_FILE`, the variable `resolve_service_principal` searches.
- Given any test uses `conversation`, should set the provider's `workers: 1` as well as `maxConcurrency: 1`: the thread cache lives in one Python worker's memory, and promptfoo 0.124.0 takes `config.workers` over `PROMPTFOO_PYTHON_WORKERS` and `-j`.
- Given missing credentials, should preflight-exit `127` naming the exact env vars and `fab-test auth status` before any promptfoo invocation; given a promptfoo crash or usage error, should write an error envelope — never report a prerequisite failure as test verdicts (the pytest-usage-error lesson).
- Given a suite in a different directory from the caller, should use the same credentials in promptfoo as the preflight; given a provider or worker error, should report an error rather than an assertion failure.
- Given `ANALYZER_VERBOSITY=summary`/`-q`, should honor the QuietLine contract; given `--format json`, stdout stays one pure document.
- Given telemetry, should route to `fabric_dynamic_analysis` with artifact_type `DataAgent`, mode as a dimension, and no connection details.

---

## Registration And Mode Wiring

**Status**: Run wiring implemented 2026-11-19 behind `FAB_TEST_ENABLE_DATA_AGENT`. Includes
service-only mode, aliases, scoped discovery, tool/credential readiness, telemetry routing,
workspace enumeration limit, `all` opt-in with a workspace, and exclusion from `local`.
The `tests` noun is registered too (Authoring Noun Dispatch). A dry run lists local
denominators without a token; it cannot enumerate a live workspace inventory offline.

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

## `tests init`: Your Questions, How The Answer Matches, And Follow-ups

**Status**: ✅ 2026-11-21. The user writes the questions; suggestions are a `?` away and a number picks one (the user's correction: "I'm not asking the questions"). `_data_agent_init_tests.py` holds the match types, ids, chains, `--answers` parsing and the prompt loop, with 60 tests in `tests/test_data_agent_init_prompts.py`, including the whole console flow with typed input. The written regex and JavaScript checks were verified in Node against the live run's answers. Live: init `--answers` → lint → run against `agent-sample-model` passed 3 of 3 (`16,376` by number, `Yes.` as a starts-with follow-up in the same conversation, a refusal).
- **Departures from the sketch below:** the user's own questions come first; Enter on "Expected answer" means the agent should decline, so there is no separate `r` step; starts and ends with ignore case and trailing punctuation (`Yes.` starts with `yes`). The `--answers` shape is `{"tests": [...]}` only. The old `{suggestion-id: answer}` shape, unreleased, now exits 2 naming the new one.
- **Known gap:** a follow-up whose root is replaced with `--force` and no follow-ups keeps its old conversation id.
- **Appending, politely (2026-11-21, the user: "polite software design would ask about that right?"):** init now says where the questions go before the first one: `Writing a new suite: PATH`, or `PATH has 3 tests:` with each id and question, and `--tests FILE` for a separate suite. A blanket "append? [y/N]" would be excise, since adding is why the person ran init and git undoes it. The question is asked only where intent is unclear and the default lost work: typing a question the suite already has (case, spacing and the trailing `?` don't matter) asks `[k]eep it (Enter) or [r]eplace with a new answer?`. Before this, init silently kept the old test and dropped the new answer. A matching question takes the existing id, even a hand-written one like `character-count`, so it is never added twice. `--answers` takes `"replace": true` for parity.
- **Add or start over (2026-11-21, the user: "wouldn't you want to ask to replace the file or append?"):** yes. Starting a suite over is a real intent with no other path: `--force` replaces only matching tests. So when a suite exists, the listing ends with `[a]dd to it (Enter) or [r]eplace all 3 tests?`. Enter keeps the common path one key. `r` writes nothing until the person has written new questions, and none at all leaves the file untouched. The result line carries `removed=N` (`would remove=N` in a dry run). A console dry run offers `Replace the 3 tests in PATH with 2 new ones? [y/N]`. `--answers` takes `"replace_all": true`.

What a session looks like (stderr prompts, defaults in brackets):

```
Suggested: How many rows are in the MarvelFact table?  Keep it? [Y/n] y
  Expected answer: 16,376
  Match: [n]umber  [c]ontains  e[x]act  [s]tarts with  [e]nds with  [p]attern  [r]efuses  (Enter = number)
  Follow-up in the same conversation? (Enter for none): Is that more than 10,000? Answer yes or no.
    Expected answer: yes
    Match: [c]ontains  e[x]act  [s]tarts with  [e]nds with  [n]umber  [p]attern  [r]efuses  (Enter = contains) s
    Follow-up in the same conversation? (Enter for none):
Your own question? (Enter to finish): Which character appears most often?
  Expected answer: Spider-Man
  ...
```

Polite by design (aidd-polite-review): every choice is one key, Enter takes the default shown, and the default is listed first. A refusal question needs no expected answer, so choosing `r` skips "Expected answer". A typo re-asks the same prompt naming the valid keys. It never restarts the session or loses the answers already given.

**Requirements**:
- Given today's `--questions` on `agent-sample-model`, should fix what it shows. Ids are two GUIDs joined (`table-6605505c-…-743cae73-…`); use the table's name, slugged, with a suffix only on a clash. A row count is suggested for `_Measures`, a measures-only table; skip tables with no columns, or suggest a question about one of its measures instead.
- Given the suggestions, should ask keep or skip for each, then ask for the caller's own questions until a blank line. Suggestions stay suggestions: every expected answer still comes from a person (decision 14).
- Given an expected answer, should ask how it matches with one key per type, case-insensitive, also accepting the full name. Each type writes a promptfoo assertion:
  - `c` contains → `icontains`
  - `x` exact → `equals`. Choosing it notes that agents rarely answer word for word.
  - `s` starts with → `starts-with`
  - `e` ends with → a `regex` anchored at the end, escaped for JavaScript
  - `n` number → a `regex` that accepts the digits with or without thousands separators (`16,?376`)
  - `p` pattern → `regex` as typed
  - `r` refuses → the refusal check the sample suite uses. It asks no expected answer.

  Enter takes the default: `number` when the answer is a number, `contains` otherwise. The default is listed first. An unknown key re-asks naming the valid keys, keeping every earlier answer.
- Given the keep or skip question, should take `y`/`n`, with Enter as yes. A follow-up or your own question ends on Enter alone.
- Given any question, should ask for a follow-up after it, and after each follow-up, until a blank line. A chain shares `vars.conversation` (the first question's id), with `reset: true` on the first turn. Follow-ups get ids `<first-id>-follow-up-<n>`. The chain is written in order, because the run pins `maxConcurrency: 1` for conversations.
- Given `--questions`, should list the suggestions, the match types and the follow-up shape. Given `--answers FILE`, should accept everything the prompts do, so an agent or a pipeline can author the same suite: a string (`contains`, as today), or `{"match", "value", "follow_ups": [...]}` per id, plus `"custom": [{"id", "query", "match", "value", "follow_ups"}]`. `match` takes the full name or the key (`"number"` or `"n"`), and `equals`/`regex` stay accepted spellings of exact/pattern. The suite always records the promptfoo assertion, never the key. An unknown match type exits 2 naming the valid ones.
- Given an existing suite, should keep existing ids and chains, append new ones, and replace one only with `--force`, as today.
- Given `-q`, the default, `-v`, `--format json`, `--dry-run`, `--questions` and `--answers`, should run each through the installed console script. `--dry-run` should show the chain as it will be written.

---

## `fab-test data-agent tests lint`

Check a suite against its item without the service (decision 13).

**Status**: In progress. The CLI verb now performs offline pairing, test-id, credential
and URL checks and pinned promptfoo config validation. Focused installed-console tests
cover discovery, malformed files, duplicate suite claims and explicit config; ordinary
analyzer targets still parse. Near-miss guidance, discovery, parity, all output modes
and the live init-to-run flow remain to be verified. On Windows with Node 26.1.0,
the real-validator test again hit the intermittent libuv shutdown assertion before a
focused rerun passed; supported CI runtime behavior still needs verification.

**Requirements**:
- Given promptfoo 0.124.0, should characterize `promptfoo validate` first — its help, exit codes, JSON output, and whether it accepts unknown top-level keys and per-test `metadata` — and record the result in this epic before TDD.
- Given `tests lint Sales.DataAgent`, should find the suite by the run's pairing, build the effective config as the run does with a placeholder agent URL, run `promptfoo validate` on it, add fab-test's own checks (the suite reads, pairs with an item, has unique test ids, and holds no credential or hand-built agent URL), and exit 0 clean, 1 on findings, 2 when nothing pairs, 127 when promptfoo is missing.
- Given no TARGET, should lint every suite under `--artifact-dir`, with JSON `{ok, suites: [...], next}` either way and `next` null unless ok.
- Given any outcome, should write no file and no envelope.
- Given `-q`, the default, `-v` and `--format json`, should print one line per suite shaped like the run's, then name `fab-test data-agent <TARGET>` as the next step.
- Given both verbs, should run each under `-q`, the default, `-v`, `--format json`, a refused run-only flag, and (init only) `--dry-run`, `--questions` and `--answers` through the installed console script before review passes.

---

## Authoring Grammar Parity Test

**Status**: ✅ 2026-11-21 (`b8544e8`). `tests/test_authoring_grammar_parity.py` walks the parser for every `<analyzer> <noun> <verb>` and checks six touch points: shared inputs, config defaults, the file flag, `-q`/`-v`, run-only flags refused (52 cases), and listed in list/explain, `help` and both flags.md copies. `_KNOWN_GAPS` holds one entry, mirrored in known-gaps.md: `contract init` has no `--contract FILE`. pbir's run and `contract lint` now share one `--contract` help string.

The parser-driven test plan.md deferred until a second authoring flow landed.

**Requirements**:
- Given every authoring verb in the parser, should assert the shared input and output flags carry the run's metavars, help and config-resolved defaults, that run-only flags are refused, and that each verb is listed in `--help` and the fab-test skill — ratcheted like `tests/test_analyzer_contract_parity.py`, with `_KNOWN_GAPS` mirroring known-gaps.md.

---

## Document All Three Callers

**Status**: ✅ 2026-11-21.
- **Human:** `docs/DATA-AGENT-TESTS-WALKTHROUGH.md` (flowchart, the service principal's setup per Microsoft Learn, init, lint, run, break it, CI, the flag table, troubleshooting). README and QUICK-VALIDATION link to it, give the service principal's setup, and QUICK-VALIDATION's stale "beside the item" location is fixed.
- **Pipeline:** `docs/examples/{github-actions,azure-devops}/data-agent-tests.yml`. Each lints without secrets, then runs on path changes and weekly.
- **Agent:** the skill (both copies) gains the flags.md table and Data Agent sections in credentials.md and targeting-and-discovery.md. SKILL.md gains suggestions, final failures, the principal's setup and where the docs are.
- **Guard:** `tests/test_data_agent_docs.py` fails if the walkthrough's flag table misses a flag of the run or either verb, or if a pipeline stops pinning this release or linting first.
- Version: b5 is unpublished, so no bump. The CHANGELOG entry is from Review 2.

**Requirements**:
- Given the human caller, should add `docs/DATA-AGENT-TESTS-WALKTHROUGH.md` modeled on the slicer walkthrough (save the agent, init, lint, run, break it, CI, opening with an init-to-CI flowchart), and update README and `docs/QUICK-VALIDATION.md` with the mode matrix, SP setup (workspace role + data-source access, per the template's README), and the 5-agent threshold.
- Given each flow's flag table, should add one to the fab-test skill's flags.md (both copies) and the walkthrough, with a row per flag and a column each for `tests init`, `tests lint` and the run.
- Given the pipeline caller, should add GitHub Actions and Azure DevOps snippets under `docs/examples/`, path-filtered on `**/*.DataAgent/**` and `**/*.DataAgent.promptfoo.yaml`, running `tests lint` before the run and relying on fab-test's exit codes.
- Given the agent caller, should update the fab-test skill in SudoLang (`SKILL.md` and the targeting/flags/credentials references), synced byte-for-byte to `src/fab_test/skill/`.
- Given a `src/` change in the beta series, should bump the version per vision.md's Versioning, re-stamp the skill frontmatter, and add a CHANGELOG entry via `aidd-log`.

---

## Verify Live Against A Real Data Agent

**Status**: Pending-live. Mocked Fabric calls and promptfoo's echo-provider checks do not
satisfy this task. The checked-in `agent-sample-model.DataAgent` already declares
`SampleModel-PQLAssert` as a semantic-model source; its published datasource has a placeholder
workspace ID, so the deployed binding must be verified before claiming a live test.
On 2026-11-20 the configured service principal accessed `fab-test-working-area` and its
published `agent-sample-model`. Its published definition binds `SampleModel-PQLAssert`
(`15b32997-f24c-4a7f-a1a2-d5f2f9bfb990`) in that workspace and selects `MarvelFact`.
A direct provider smoke question, "How many characters are in the data?", returned `0`;
the same question on retry returned `16,376`, which the user independently verified on
2026-11-20. FabricIQ MCP query tools were unavailable here, so the baseline's query and
verification method have not been independently recorded. Neither smoke call is a passing suite.
The installed CLI subsequently ran the paired suite against the published agent: on
2026-11-20, `fab-test data-agent agent-sample-model --artifact-dir fabric-artifacts
--workspace 2aea22b0-2e68-485a-8902-e8e5da32e3ef --timeout 600 --report -q`
exited 0 with promptfoo 0.124.0 and cft-fab-test 1.10.0b5. The factual answer was
`16,376`, the conversation follow-up `Yes.`, and the agent declined the private-balance
request. Redacted envelope and HTML report are in the session's
`files/data-agent-live-credentials-fixed/data_agent/agent-sample-model/`.
An isolated suite with the intentionally wrong `999,?999` expectation exited 1:
the agent answered `16,376`, and the assertion appeared in both the redacted envelope
and HTML report under `files/data-agent-live-intentional-failure/data_agent/agent-sample-model/`.
Running the unchanged paired suite again exited 0 with the same three answers; its
redacted evidence is under `files/data-agent-live-recovery/data_agent/agent-sample-model/`.
Bare `fab-test data-agent`, with `FABRIC_WORKSPACE_ID` set, also exited 0 with
`mode: service` and `source: env`; evidence is under
`files/data-agent-live-bare/data_agent/agent-sample-model/`.
Workspace enumeration with `--workspace` and no TARGET exited 0 for one agent,
and stdout parsed as one JSON document; its redacted evidence is under
`files/data-agent-live-enumeration/data_agent/agent-sample-model/`.
The typed `fab-test-working-area.Workspace/agent-sample-model.DataAgent` target also
exited 0 with `source: target`; evidence is under
`files/data-agent-live-typed/data_agent/agent-sample-model/`.
With credential variables unset and an absent `--env-file`, the installed CLI exited
127 and named the required service-principal variables and `fab-test auth status`.
On 2026-11-21, after the Review 1 security fixes (decisions 17 and 19) and the merge of `dev` (`fef5706`), the same paired-suite command exited 0 in 55 s: `16,376`, `Yes.`, and a refusal of the private-balance question. The token went only to the resolved Fabric host. The worker read the principal from the private temp file, which was gone after the run. The client secret appeared in none of the result files. The refusal was the agent's generic "There's content here I can't work with…", not a scoped decline. It passes the refusal check, but a `refuses` match type should be judged against such wording.
The initial attempts exposed and led to fixes for a persistent-worker import collision,
credential-file resolution after the working directory changed, and provider errors
being mislabeled as assertion failures. Independent query provenance, authoring, and
the remaining CLI blast-radius checks are still pending.

**Requirements**:
- Given the existing `agent-sample-model` and `SampleModel-PQLAssert`, should verify the deployed agent is published, bound to the actual deployed sample semantic model, and accessible to the test service principal; any required deployment, rebinding, or permission changes need explicit approval.
- Given the selected `MarvelFact` table and `[Number of Characters]` measure, should query the semantic model independently to record verified expected answers, then ask the real Data Agent matching questions and compare its answers with those baselines, never with guessed figures or an echo provider.
- Given the verified sample source, should author `agent-sample-model.DataAgent.promptfoo.yaml` beside the item, pair it using the item's logicalId, and include a grounded factual question, an out-of-scope refusal, and a conversation whose follow-up depends on the first turn.
- Given that live suite, should demonstrate a clean run exits `0`, a deliberately incorrect expected answer exits `1` with the failed assertion in the envelope and HTML report, and restoring the verified expectation returns the suite to passing.
- Given a live run, should record the command, package/promptfoo versions, verified source binding, baseline answers, observed answers, exit codes, and redacted result/report locations; should keep this task pending-live and the feature flag in place until these checks are evidenced.
- Given `agent-sample-model` deployed and a service principal, should run bare mode, a typed service target, `--workspace` enumeration, and `tests init` → `tests lint` → the run through the installed console script, including a deliberately failing assertion, a multi-turn conversation, and the missing-credentials `127` path.
- Given the blast-radius rule, should exercise `all`, `list`, `explain`, `doctor`, `-q`, `--format json`, `--dry-run`, `--report`, and the >5-agent refusal with and without `--all`.
- Given the live run passes, should delete `data_agent` from `_FEATURES` and `FEATURE_SPELLINGS`, so the documented command exists (Feature Flags decision 3). *(2026-11-21, at the user's request after the passing live run: step one of `_feature_flags`' release path is done. The default is `True`, and `FAB_TEST_ENABLE_DATA_AGENT=0` still turns it off. README, QUICK-VALIDATION and the skill drop "feature-gated". The flag tests now set every flag off explicitly. The output-contract test passes `data-agent` a workspace, since the dry run is service-only and offline. Deleting the row waits for a release.)*

---

## AIDD Review

**Status**: Review 1 done 2026-11-21 by an unanchored reviewer (aidd-review, python, module-budgets, tdd, analyzer-contract, command-grammar, polite-review; CLI exercised on scratch copies, no service calls). Gates: `ruff check .` clean; complexity and module-budget tests pass; non-playwright half 3518 passed, 87% coverage, 3 failures only in `tests/test_rtk_hook_safety.py` (the hook file is deleted in the working tree, unrelated to this epic); focused data-agent tests 118 passed; `pip-audit` clean. Findings are the next section. Playwright half and the `CI=true` pass are still to run (Quality Gates).

**Requirements**:
- Given the epic's diff, should be reviewed by a reviewer not anchored on the implementation, with aidd-review, aidd-python, aidd-module-budgets, aidd-tdd, aidd-analyzer-contract, aidd-command-grammar and aidd-polite-review, exercising the CLI on scratch copies.

---

## Review 1 Follow-ups

**Status**: 📋 PLANNED. Ordered by severity; each is a task to do test-first. The **decide** points are settled by decisions 17–21 (2026-11-21): item 2 → 17, item 3 → 19, item 4 → 18, item 11 → 20, the `all` banner nit → 21.

**Blocking**:
1. ✅ *(2026-11-21: `near_miss` in `_authoring_parser.py`, called once from `fab_test._authoring_dispatch`; verbs, `contracts`/`test` spellings, aliases, flags as typed, real `init`/`lint`/`contracts` items run as targets; installed-console test for `pbir lint` → 2; CHANGELOG line. The Data Agent changelog entry waits for its feature, item 12.)* **Near-miss guidance is unmet** (Authoring Noun Dispatch). `fab-test pbir lint` still exits 0 having checked nothing; `pbir init Sales`, `pbir contracts init`, `data-agent init Sales`, `data-agent test lint` give argparse's generic error. Implement `did you mean: <exact command>` (exit 2, TARGET and flags as typed) once in `_authoring_parser`, unless an item has that name; add the CHANGELOG line for `pbir lint` 0 → 2.
2. ✅ *(2026-11-21: provider host check on every bearer request, `_RefuseRedirects` opener, quoted ids, userinfo refused; `effective_config` refuses a suite or provider `env` that sets `FAB_TEST_*`, `FABRIC_*`, `AZURE_*`, `PROMPTFOO_*` or `PLAYWRIGHT_ENV_FILE`. Lint's warn/fail split is item 4.)* **Provider sends the bearer token to any HTTPS host in a suite, and keeps it across redirects** (`fabric_data_agent_provider.py` `_validated_base_url`, `urllib` redirects). Allowlist Fabric/Power BI hosts or require an explicit opt-in; refuse redirects; re-check the host inside `_http_json`. Quote `thread_id`/`run_id` in URLs. **decide**: the allowlist and the opt-in's spelling.
3. ✅ *(2026-11-21: `_promptfoo_env` strips every service-principal spelling and the Azure SDK secrets. The provider reads the preflight's principal from a file in the run's private temp dir, deleted with it. The trust boundary is in README, QUICK-VALIDATION and the skill, both copies. Note: the real-validator tests hit the known Windows libuv shutdown assertion in 2 of 3 serial runs on Node 26.1.0. That makes lint report a valid suite as an error, so it is in item 5's scope.)* **A suite is code run with the service-principal secret in its environment** (`invoke_data_agent._evaluate` passes `os.environ`). Document the trust boundary (never run on untrusted PRs) in README, QUICK-VALIDATION and the skill; **decide** whether to also pass the secret only to the provider worker via the credential-file path.

**Should-fix**:
4. ✅ *(Review 2 item 5)* **Lint rejects what the run honors** (`base_url`, `fabric_urls`; decision 4's escape hatch and the template-migration requirement). **decide**: lint warns, or the escape hatch is documented as unlintable.
5. ✅ *(Review 2 item 6)* **`tests lint` never installs promptfoo** (`_data_agent_lint_command.py` probes; the run resolves). A fresh CI runner exits 127 at lint, and lint skips its own offline checks when promptfoo is absent. Bootstrap like the run, or run `suite_problems` first and report 127 for the upstream half only.
6. ✅ *(Review 2 item 10)* **Help advertises `data-agent [TARGET] tests …`, which does not parse**; the noun only works as the first word. Scan for the noun before the verb, or drop `[TARGET]` from the usage.
7. ✅ *(Review 2 item 10)* **Discoverability**: `fab-test help`, `list --format json` and `explain data-agent` do not name the verbs; `known-gaps.md` still describes the removed argv check.
8. **Docs contradict the code**: README, QUICK-VALIDATION, skill and flags.md say init/lint are pending. Still to write: flag table (init, lint, run columns), mode matrix and SP setup, `docs/DATA-AGENT-TESTS-WALKTHROUGH.md`, `docs/examples/` CI snippets, skill targeting and credentials references (copies stay byte-identical).
9. **Shared authoring module is half done**: run-flag refusal and `add_output_flags` remain in `_slicer_init_output.py` and are re-implemented in `_data_agent_authoring.py` and `_authoring_parser.py`; the authoring layer imports private names from `invoke_data_agent` and `_data_agent_lint_command`.
10. **`tests init` is thin (decision 14)**: one hard-coded refusal, `aiInstructions` appended as text, `suggested` always null. Derive refusals from what the sources do not cover and questions from selected tables.
11. ✅ *(Review 2 item 11; the docs caveat was already done)* **Telemetry is untested.** Add tests for the table, `artifact_type: DataAgent`, mode and no secrets; answers stay (decision 20); document the reader-access caveat.
12. ✅ *(Review 2 item 13; no bump: b5 is unpublished)* **Version bump and CHANGELOG entry** are missing for the data-agent work (`aidd-log`; skill frontmatter re-stamp).
13. ✅ *(Review 2 item 12: a dated note; the next addition extracts)* **Module budgets**: `fab_test_parser.py` is 1131 lines (hard limit 800) and grew without a dated exemption note; `fab_test_summary.py` is 792; `fab_test.py` 443 (soft 400). Add the exemption note or extract the data-agent parser wiring.
14. ✅ *(Review 2 item 8)* **Retry re-posts a user turn** on a persistent conversation thread when the failure follows the post. Make the post idempotent or do not retry after a successful post.
15. **Out-of-scope changes in the diff** (`fabric-artifacts/README.md`, `tests/test_rdl_fixture_generator.py`, `.platform` edits, the deleted rtk hook): commit separately; restore the hook or drop its test before the final gate.

**From the 2026-11-21 live attempt** (after syncing with `dev`; the workspace's capacity was paused, so Fabric answered `CapacityNotActive`. The token came from the new private credential file, and the resolved URL passed the host check):
16. ✅ *(Review 2 item 9)* The summary line read `❌ agent-sample-model — no findings` for an error envelope. It should say `error` and show the message's first line.
17. ✅ *(Review 2 item 8)* The provider retried a Fabric error marked `"isRetriable": false`. It should treat that flag, and `CapacityNotActive`, as final and name the fix: resume the capacity.
18. ✅ *(2026-11-21: the provider appends one line per answer to `FAB_TEST_DATA_AGENT_PROGRESS`, a file in the wrapper's private temp dir. `_data_agent_progress.Progress` tails it every 0.25 s while promptfoo runs. The lines go to the terminal itself (`CONOUT$`, `/dev/tty`), because fab-test replays the wrapper's stderr only at exit. After grading, `show_verdicts` prints ✓/✗ per test with the failed check. Off under `-q`, in CI, and with no console. Tested with a buffer while a fake promptfoo runs; a live run passed in 49 s.)* **A run is silent for about a minute and looks hung** (the user asked "seems like fab-test data_agent hanging", 2026-11-21; it passed in 58 s). Each question is several agent calls, about 20 s; the wrapper captures promptfoo and prints only at the end. Print `asking 3 questions of agent-sample-model (live agent calls, about 20 s each)` up front. Then print one line per answer on stderr as it lands: `✓ 1/3 Count characters (18 s)`, or `✗` with the failed check. Keep it quiet under `-q`, and keep stdout pure under `--format json`. Severity High: the most frequent path (polite: "keep the caller informed").

**Nits**: dead `contract_main` and `import os as os`; `_run_targets.py` conditional; `default_type="DataAgent"` hard-coded twice (move to `service_item_type`); `-q` with `--dry-run` prints full text; `explain` prints an empty `--promptfoo-path`; bare-JWT redaction; provider re-reads the principal on every call (cache per process); `_existing()` refuses any `#`; `all` banner stays `mode=local` when `data_agent` runs in service mode (**decide** against Service Targeting); stale epic text (header "PLANNED", provider line/test counts, the package shim `src/fab_test/fabric_data_agent_provider.py`, Registration's "tests noun remains").

**Missing tasks confirmed**: Authoring Grammar Parity Test (no file), Document All Three Callers (above), blast-radius pass of both verbs through the installed console script.

---

## Review 2 Follow-ups

**Status**: ✅ 2026-11-21 (commits `f060346`, `4568810`, `fff12d3`, `36eb322` and the checkpoint after them), except the nits noted below. Review 2 was done by an unanchored reviewer with the same skills as Review 1. Gates: ruff, complexity and pip-audit are clean. The non-playwright half had 3648 passed, 88%; its only failures are the rtk hook tests (Review 1 item 15). The playwright half had 204 passed, 90.48%; its 16 live-parity failures are a 401, because the service principal no longer sees the parity tests' workspace (environmental). `1.10.0b5` is not on PyPI (the user, 2026-11-21), so these fixes stay in b5. The user said "do the fixes". Each item below is done test-first, together with the open Review 1 items it names.

**Blocking**:
1. ✅ `tests init` drops a new question whose slug matches an existing id (the 40-character truncation, or a hand-written id). New ids must avoid every id already in the suite. An existing id is reused only on a matching question or an explicit `"id"`.
2. ✅ With no `.git`, `fab-tests/` is never searched, so the run skips every item and exits 0. Outside a repository, `fab-tests/` is read from the working directory, as a relative `tests_dir` already is.

**Should-fix**:
3. ✅ A `#` inside a quoted value reads as a comment, so init can't extend its own output. Detect real YAML comments.
4. ✅ A folder named `lint`/`test`/`init` in the working directory defeats the near-miss guard. Only an item folder (suffix or `.platform`) counts.
5. ✅ Decision 18 (Review 1 item 4): lint warns on an allowed explicit URL and fails a disallowed host with the run's message. The run refuses a disallowed host before promptfoo starts.
6. ✅ `tests lint` without promptfoo (Review 1 item 5): run the offline checks first, then bootstrap promptfoo the way the run does.
7. ✅ Lint hands `promptfoo validate` the full environment. Strip it as the run does (decision 19).
8. ✅ Provider retries (Review 1 items 14, 17):
   - `isRetriable: false` and `CapacityNotActive` are final, and the message names the fix.
   - Never retry after the message is posted.
   - A poll timeout is final.
   - A created thread is deleted even if the post fails.
9. ✅ An error envelope reads `❌ … no findings` (Review 1 item 16). Show `error` and the message's first line.
10. ✅ Grammar and discoverability (Review 1 items 6, 7):
    - Fix the `[TARGET] tests` usage.
    - Name the verbs in `help`, `list --format json` and `explain`.
    - Update `known-gaps.md`.
    - Fix the stale `--answers` help, and make `--tests` help the same on every verb.
    - Print the credential remediation once.
11. ✅ Test quality:
    - Show requests go through the redirect-refusing opener.
    - Test the userinfo check on an allowed host.
    - Replace the progress test's fixed sleep with a wait-until.
    - Add the telemetry tests (Review 1 item 11).
12. ✅ Module budgets (Review 1 item 13): add a dated note on `fab_test_parser.py`'s exemption, or extract the wiring.
13. ✅ CHANGELOG entry for the data-agent feature (Review 1 item 12). No version bump: b5 is unpublished.

**Nits**:
- ✅ `-q --dry-run` prints one line.
- ✅ `explain` no longer shows an empty `--promptfoo-path`.
- ✅ Refusals name the whole command and the items found.
- ✅ Stale epic text.
- Kept: `import os as os` in `_slicer_init_output.py` is a re-export that `test_slicer_init_output.py` patches, so it isn't dead.
- Open: `default_type="DataAgent"` is hard-coded twice. Moving it to `SERVICE_ITEM_TYPES` would route data-agent through the service-export path its other callers share. That's a blast-radius change, not a nit.
- Open: the provider re-reads the principal on every call. A per-process cache would need clearing between tests, and a read costs one small file.

**Still open after Review 2** (planned tasks, not review fixes):
- ✅ Review 1 item 8: docs (Document All Three Callers).
- ✅ Review 1 item 9: one `run_flag` refusal for both flows; `named_item` is public (`4c70381`).
- ✅ Review 1 item 10: unselected tables are suggested as declines, only figure measures are suggested, and the agent's instructions are shown (`4c70381`).
- Review 1 item 15: `.github/hooks/rtk-rewrite.json` is deleted in the working tree (the user's change), so `tests/test_rtk_hook_safety.py` fails 3 tests. Restore the file, or remove it and its test, before the final gate.
- ✅ The Authoring Grammar Parity Test. Still open: the blast-radius pass and Quality Gates.

---

## Quality Gates

**Requirements**:
- Given the whole repository, should pass `ruff check .`, `tests/test_complexity_budget.py`, and `tests/test_module_budget.py` — plan the new modules' seams up front rather than grow existing files at their ceilings.
- Given the full suite, should pass with `--cov --cov-fail-under=80` over `src/fab_test`, in CI's two halves.
- Given CI-dependent tests, should pass once with `GITHUB_ACTIONS=true CI=true`.
