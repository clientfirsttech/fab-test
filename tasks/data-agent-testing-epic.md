# Fabric Data Agent Testing Epic

**Status**: ✅ IMPLEMENTED — code, docs, workflow examples, and mocked validation landed 2026-10-04. Live-service verification remains **pending-live** because this session had no real deployed Data Agent to hit.
**Goal**: A new `data-agent` analyzer that evaluates deployed Fabric Data Agents by running promptfoo with a packaged Python provider, following [fabric-data-agent-testing-template](https://github.com/clientfirsttech/fabric-data-agent-testing-template), under the repo/service mode standardization.

## Overview

WHY: Teams deploying Fabric Data Agents have no way to regression-test the agent's actual answers — whether it refuses irrelevant questions, returns the right figures, or holds a conversation — short of asking it by hand. The template repository proves the shape (promptfoo driving the agent's Assistants-compatible API), but it is a standalone Node project with a TypeScript provider, hand-built URLs, and its own CI parsing; nothing about it speaks fab-test's one contract. This epic ports the provider to promptfoo's Python contract (`call_api(prompt, options, context)`), ships it inside the fab-test package so users author only test cases, and wires the run through the same envelope, exit codes, modes, HTML report, and telemetry as every other analyzer. A Data Agent only exists deployed, so this is always a **service test**: repo mode supplies the denominator (each `*.DataAgent` folder's authored tests) while execution reaches the service; there is no desktop mode.

**Decisions** (recorded 2026-10-04 at discovery review):

1. ✅ Analyzer name is **`data-agent`** with alias **`agent`** (registry key `data_agent`; the registry key, results folder, and envelope analyzer field agree).
2. ✅ The provider is **Python**, shipped inside the fab-test package and declared to promptfoo as `file://.../fabric_data_agent_provider.py` — a port of the template's `provider.ts`, not a dependency on it.
3. ✅ Tests are authored **per `*.DataAgent` folder** (a `promptfooconfig.yaml` beside the artifact) — the repo-scan denominator falls out of the existing folder-suffix convention, matching the template's CI path filters (`artifacts/**.DataAgent/**`).
4. ✅ The agent URL is **resolved via the Fabric API** from the workspace + artifact name — this is a service test; users never hand-build `.../dataagents/{id}/aiassistant/openai` URLs (an explicit URL in config remains an escape hatch, not a requirement).
5. ✅ Auth is **service principal only** — the existing `build_azure_credential` env-SP chain; no `--interactive`, no device code, mirroring the template's client-credentials flow. Scope defaults to the template's `https://analysis.windows.net/powerbi/api/.default`, overridable via `FABRIC_SCOPE`.
6. ✅ v1 keeps **promptfoo-native assertions** as authored (`javascript`, `contains`, `regex`, …); LLM-graded rubrics are deferred until a judge-key story exists.
7. ✅ **Multi-turn conversations are in v1**: the template's `conversation`/`reset` thread-reuse vars, which force promptfoo `maxConcurrency: 1` / `workers: 1`.
8. ✅ **Never in `local`**; in `all` only when a workspace is configured (same rule as `sqldb-test`) — live LLM calls cost time and capacity.
9. ✅ Workspace enumeration over **5 agents** warns and stops; `--all` forces it (Service Targeting decision 9's semantics, lower threshold because each agent run is slow). In CI or `--format json`, the stop is an exit-`2` refusal naming `--all`, never a prompt.
10. ✅ **`fab-test data-agent init`** scaffolds a starter `promptfooconfig.yaml` + `.env.example` from the template's shape. A generic/`playwright` init is out of this epic's scope — recorded as a standalone follow-up task in plan.md.
11. ✅ **Independent** of the blocked Promptfoo Skill Evaluation epic — this epic's promptfoo tool seam may incidentally help it, but neither blocks the other. The win32-arm64 limitation (`@libsql/win32-arm64-msvc` unpublished) is surfaced by `doctor`, not solved here.

## Completion Summary

- ✅ Promptfoo tool seam implemented: analyzer metadata, npm bootstrap, doctor readiness, tool-update checks, and THIRD-PARTY notice.
- ✅ Python provider implemented and unit-tested with mocked token + Data Agent API responses.
- ✅ Data Agent URL resolution, wrapper mapping, mode wiring, alias parsing, telemetry routing, and `fab-test all` gating implemented.
- ✅ `fab-test data-agent init` scaffolding implemented.
- ✅ README, QUICK-VALIDATION, fab-test skill, and GitHub Actions / Azure DevOps examples updated.
- ✅ Installed-console-script and dry-run/mock verification completed locally.
- 🟡 **pending-live**: end-to-end calls against a real deployed Data Agent, including the live >5-agent refusal and service-principal permissions, were not runnable in this session.

---

## Promptfoo Tool Seam

**Status**: ✅ done

Register promptfoo as a wrapped external tool so install, readiness, and provenance behave like every other wrapped tool.

**Requirements**:
- Given `analyzers.json`, should carry a `tool_install` entry for promptfoo (npm, pinned version, `requires_runtime: node >= 18`), a THIRD-PARTY.md row, and `_WRAPPED_TOOLS` registration.
- Given `fab-test doctor`, should report promptfoo readiness without running an eval, and on win32-arm64 should name the `@libsql/win32-arm64-msvc` platform limitation as the remediation rather than failing opaquely.
- Given a machine without Node, should exit `127` naming the runtime requirement, as the other Node-wrapped tools do.

---

## Python Provider Module

**Status**: ✅ done

Port the template's `provider.ts` to promptfoo's Python provider contract, shipped inside the package.

**Requirements**:
- Given promptfoo invokes `call_api(prompt, options, context)`, should run the template's lifecycle — create assistant, create thread, post message, create run, poll until terminal (2 s interval, configurable timeout), read the last assistant message's text, delete the thread — against `{base_url}/...?api-version=2024-05-01-preview`, returning `{"output": text}` or `{"error": message}`.
- Given a token is needed, should acquire it via the client-credentials flow from `FABRIC_TENANT_ID`/`FABRIC_CLIENT_ID`/`FABRIC_CLIENT_SECRET` with the scope from decision 5, cache it in memory, and refresh 300 s before expiry; a partial service principal fails with the existing `IncompleteServicePrincipalError` remediation, never a fallback.
- Given a transient failure, should retry up to `max_retries` (default 3) with `retry_delay` sleeps before returning an `error` response.
- Given `vars.conversation` on a test case, should reuse the thread across turns keyed by base URL + conversation id; given `vars.reset`, should delete and recreate it; given thread-not-found, should evict the cached thread and recreate (decision 7).
- Given any output path — provider response, logs, envelope, telemetry — should never contain the token or client secret.
- Given the provider is pure Python in the package, should be unit-tested against a mocked token endpoint and agent API with no live service.

---

## Agent URL Resolution

**Status**: ✅ done

Resolve a Data Agent's API URL from its name via the Fabric API (decision 4).

**Requirements**:
- Given a workspace and a Data Agent item name or GUID, should resolve the item via the Fabric items API and construct `https://api.fabric.microsoft.com/v1/workspaces/{ws}/dataagents/{id}/aiassistant/openai`, reusing the existing service-client/credential path — no new auth subsystem.
- Given an ambiguous or missing name, should exit listing the workspace's Data Agent items, never a raw HTTP error.
- Given an explicit URL in the artifact's config, should use it unchanged (escape hatch, not requirement).
- Given `--dry-run`, should list the agents and resolved denominators without acquiring a token.

---

## Config Discovery And Effective Config Generation

**Status**: ✅ done

Each `*.DataAgent` folder authors only tests; fab-test generates the effective promptfoo config.

**Requirements**:
- Given a repo scan, should treat each `*.DataAgent` folder containing a `promptfooconfig.yaml` as one artifact; a `*.DataAgent` folder without one is `skipped` with a remediation naming `fab-test data-agent init`, never a batch failure.
- Given an authored config, should generate the effective config at run time injecting the packaged provider path, the resolved agent URL, and `maxConcurrency: 1` when any test uses conversations — users never reference the provider file or hand-build URLs.
- Given the template's `fabric_urls`/`vars.agent` shape in an authored config, should honor it so a template-repo user migrates without rewriting tests.

---

## Analyzer Wrapper (`invoke_data_agent.py`)

**Status**: ✅ done

Run `promptfoo eval --output results.json` and map results to the one contract.

**Requirements**:
- Given promptfoo's `results.results[]`, should map each failed assertion (`success`/`pass`, `gradingResult.componentResults[].pass`) to a Finding and populate `test_results` in test shape (suite/test/passed/expected/actual); exit 0/1 is decided from findings per `_artifact_exit_code`.
- Given promptfoo's HTML `outputPath`, should attach it via `attach_report` before `write_envelope` so `--report`/`--open-report` work.
- Given missing credentials, should preflight-exit `127` naming the exact env vars and `fab-test auth status` before any promptfoo invocation; given a promptfoo crash or usage error, should write an error envelope — never report a prerequisite failure as test verdicts (the pytest-usage-error lesson).
- Given `ANALYZER_VERBOSITY=summary`/`-q`, should honor the QuietLine contract; given `--format json`, stdout stays one pure document.
- Given telemetry, should route to `fabric_dynamic_analysis` with artifact_type the Fabric item type name, mode as a dimension, and no connection details.

---

## Registration And Mode Wiring

**Status**: ✅ done

All analyzer-contract touch points plus the Service Targeting mode rule.

**Requirements**:
- Given the analyzer contract checklist, should register in `ANALYZER_REGISTRY`, `ANALYZER_SCOPES` (repo + workspace, never desktop), `_COMMAND_BUILDERS`, the parser (with the `agent` alias), `analyzers.json`, a pytest marker, and `conftest`'s marker maps — verified against `references/checklist.md`, copying no known gap.
- Given `fab-test data-agent` (bare), should resolve mode `repo` — each `*.DataAgent` folder's tests against its deployed agent; given `"Dev.Workspace/Sales Agent"`, mode `service` for that one agent; given `--workspace Dev` with no TARGET, mode `service` enumerating every deployed Data Agent (paired with authored tests; no tests => `skipped`); given `local/NAME`, exit `2` — no desktop mode.
- Given more than 5 enumerated agents, should warn and stop unless `--all`; in CI or `--format json`, an exit-`2` refusal naming `--all` (decision 9).
- Given `fab-test all`, should include `data-agent` only when a workspace is configured; given `fab-test local`, never (decision 8).
- Given the banner, envelope, `--dry-run`, `explain`, `-q` line, and telemetry, should surface `mode`/`source` exactly as the Service Targeting epic defines.

---

## Init Scaffolding

**Status**: ✅ done

`fab-test data-agent init` writes a starter so green-field setup is one command (decision 10).

**Requirements**:
- Given `fab-test data-agent init NAME`, should create `NAME.DataAgent/promptfooconfig.yaml` with commented example tests (relevance refusal, substring, regex, one conversation pair) and a `.env.example` naming the four `FABRIC_*` vars — derived from the template repo's shape.
- Given the target folder already has a `promptfooconfig.yaml`, should refuse without `--force`, never overwrite silently.
- Given the scaffold, should run green end-to-end once the user fills in workspace/agent name and credentials — verified in the live task.

---

## Verify Live Against A Real Data Agent

**Status**: 🟡 pending-live

**Requirements**:
- Given a real deployed Data Agent and a service principal, should run bare repo mode, a typed service target, and `--workspace` enumeration through the installed console script, including a deliberately failing assertion, a multi-turn conversation, and the missing-credentials `127` path.
- Given the blast-radius rule, should exercise `all`, `list`, `explain`, `doctor`, `-q`, `--format json`, `--dry-run`, `--report`, and the >5-agent refusal with and without `--all`.
- Verified here instead: the installed console-script path, dry-run path, init scaffolding, promptfoo result mapping, and provider lifecycle were covered with mocked/token-endpoint tests and local CLI contract tests. Real service execution is deferred until a workspace hosts a deployed Data Agent for the test principal.

---

## Document All Three Callers

**Status**: ✅ done

**Requirements**:
- Given the human caller, should update README and `docs/QUICK-VALIDATION.md` with the `.DataAgent` convention, `init`, mode matrix, SP setup (workspace role + data-source access, per the template's README), and the 5-agent threshold.
- Given the pipeline caller, should add copy-pasteable GitHub Actions and Azure DevOps snippets path-filtered on `**/*.DataAgent/**` under `docs/examples/`, replacing the template's JSON-reparse step with fab-test's exit codes.
- Given the agent caller, should update the fab-test skill in SudoLang (`SKILL.md` and the targeting/flags/credentials references), synced byte-for-byte to `src/fab_test/skill/` (guarded by `tests/test_skill_resource.py`).
- Given an epic-sized `src/` change, should bump MINOR in `src/fab_test/__init__.py` (`.dev1`), re-stamp the skill frontmatter version, and add a CHANGELOG entry via `aidd-log`.

---

## Quality Gates

**Status**: ✅ done — `ruff check .`, budget tests, full `pytest --cov --cov-fail-under=80`, and CI-mode `pytest` all passed in this branch

**Requirements**:
- Given the whole repository, should pass `ruff check .`, `tests/test_complexity_budget.py`, and `tests/test_module_budget.py` — plan the new modules' seams up front rather than grow existing files at their ceilings.
- Given the full suite, should pass with `--cov --cov-fail-under=80` over `src/fab_test`.
- Given CI-dependent tests, should pass once with `GITHUB_ACTIONS=true CI=true`.
