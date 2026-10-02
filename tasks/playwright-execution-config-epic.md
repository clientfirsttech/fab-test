# Playwright Execution Configuration Epic

**Status**: IMPLEMENTED (all 7 tasks verified locally through the installed CLI; not archived: live GitHub Actions and Azure DevOps runs are unverified, and the remote run was only exercised with a local Chromium also installed)
**Goal**: Run fab-test's generated Python report tests locally or on Azure-hosted browsers through an optional execution configuration.

## Overview

To shorten CI report validation without changing its verdicts, let callers select browser execution settings while fab-test retains discovery, generated cases, evidence, and the result contract. Discovery selected Python Playwright and pytest as the unchanged default, parallel cases within one report, service access-token authentication, and examples for both GitHub Actions and Azure DevOps. The user journey is recorded in [../plan/story-map/playwright-execution-config.yaml](../plan/story-map/playwright-execution-config.yaml). Azure compatibility is a proof gate, not an assumption derived from the JavaScript SDK or the older reference repository.

---

## Prove Python Azure browser compatibility (completed 2026-10-01)

Verified Python Playwright 1.63.0 and pytest-playwright 0.9.0: a direct remote Chromium smoke passed and paginated rendering was exercised. **Correction:** the isolated [proof harness](../tools/prove_azure_playwright.py) matrix run was not evidence of remote execution, because pytest-playwright's own fixtures overrode the harness's, so it ran locally. Remote matrix execution was first verified through the shipped adapter (a two-worker Azure run matched the local one-failed/one-passed verdict, and an invalid token was rejected as an execution error rather than passing locally). The harness's `ws_endpoint` key was also stale for Playwright 1.63, whose `connect()` takes `endpoint`.

**Requirements**:
- Given a user-provided endpoint and service access token, should prove a generated report case executes on an Azure-hosted browser through Python pytest without Node, npm, or a TypeScript runner.
- Given the reference repository uses the older JavaScript service package, should verify the current endpoint, authorization headers, session identifiers, browser version requirements, and launch-option handling against current service documentation and a live connection.
- Given the packaged render spec requires embed-sandbox launch settings, should prove those settings and Power BI embedding work remotely for interactive and paginated reports, with screenshots and case evidence retrieved locally.
- Given the installed pytest-playwright version, should confirm its supported remote connection fixture before reusing it rather than relying on upstream main alone.
- Given no compatible Python connection can be established, should record the blocker and request a revised plan without changing the Python-only constraint or claiming Azure support.
- Given the live paginated proof's valid-value lookup returned Fabric HTTP 400, should record parameter expansion as unverified pending the Dataset Execute Queries REST API tenant setting rather than treating the no-parameter rendering pass as full parameter coverage.

---

## Resolve optional execution configuration

Add a validated YAML configuration selector without changing fab-test's existing global config option.

**Requirements**:
- Given no execution configuration, should preserve existing local browser behavior, worker defaults, commands, environment variables, and result paths.
- Given an explicit selection, should resolve proposed --playwright-config, PLAYWRIGHT_CONFIG_PATH, and playwright_config in fab-test.yml in CLI > environment > fab-test config > default order, with paths relative to the owning config file or invocation as appropriate.
- Given local or Azure execution settings, should validate supported connection, launch, context, and worker settings without loading arbitrary scripts, pytest plugins, custom tests, or a speculative provider registry.
- Given a missing, malformed, unsupported, or TypeScript config, should refuse with exit 2 and name the path and corrective setting before Fabric discovery or browser authentication.
- Given config --show or --dry-run, should identify the selected config and its origin without connecting, acquiring credentials, or exposing tokens and authorization headers.
- Given --workers or PLAYWRIGHT_XDIST_WORKERS, should preserve their precedence over the execution config's worker setting.

---

## Resolve service credentials safely

Load Azure service credentials separately from Fabric embedding credentials without prompting at runtime.

**Requirements**:
- Given Azure execution, should read PLAYWRIGHT_SERVICE_URL and PLAYWRIGHT_SERVICE_ACCESS_TOKEN using the existing --env-file > PLAYWRIGHT_ENV_FILE > .fab-test/.env > ./.env file-selection chain, with process environment values winning over file values.
- Given the Fabric client secret, should retain its existing embedding purpose rather than treating it as the Azure browser service token.
- Given a token in YAML or a credential-bearing connection URL, should reject it and name the supported environment variable instead of persisting or displaying it.
- Given a missing service prerequisite, should report it through readiness and the existing missing-prerequisite exit contract without network calls or an interactive prompt.
- Given an expired token or rejected connection, should report a tool/authentication error and remediation rather than a broken-visual finding or silent local fallback.
- Given diagnostics, envelopes, manifests, native output, telemetry, and browser evidence, should redact service credentials and embedding credentials before persistence or replay.

---

## Connect the generated Python tests

Extend browser setup using supported pytest-playwright fixtures while retaining ownership of generated cases and reports.

**Requirements**:
- Given an Azure configuration, should connect each worker to a remote browser while Python test processes and xdist remain on the invoking machine.
- Given local execution, should continue using the existing local launch path without requiring Azure credentials or network access to the browser service.
- Given connection timeout and report render timeout, should keep their meanings distinct and close remote browsers and contexts after pass, failure, or interruption.
- Given configuration that attempts to replace test selection, case identifiers, evidence paths, or result reporters, should refuse the override so only fab-test-generated report tests run.
- Given the wrapper and render spec are shared by CLI and direct wrapper invocation, should enumerate and exercise both callers, plus applicable aggregate dispatch, before declaring the adapter verified.
- Given growth in invoke_playwright.py, the parser, registry, or their tests, should respect existing module and complexity ratchets through focused extraction rather than unrelated refactoring or raised budgets.

---

## Bound concurrency and preserve results

Apply configurable worker limits to one report's generated matrix while retaining the facade's failure and evidence semantics.

**Requirements**:
- Given more generated cases than configured workers, should run at most that many workers for the current report and leave cross-report scheduling unchanged.
- Given remote service limits and parallel connections, should expose a clear worker cap and preserve unique case evidence, session correlation, and timeout budgeting without claiming a guaranteed speedup.
- Given the same generated matrix run locally and remotely, should preserve case identities, findings, test_results, envelope status, exit codes, and configured result locations.
- Given collection, setup, authentication, or connection failure before cases execute, should write error evidence without fabricating visual failures for unexecuted cases.
- Given --report, --open-report, quiet mode, JSON output, or telemetry, should preserve each existing contract without copying known analyzer deviations into the new path.
- Given focused tests for config resolution, worker bounds, connection failures, cleanup, and result parity, should demonstrate red then green through the actual owning code before broad verification.

---

## Document local and CI setup

Provide token-placement guidance and copy-ready Python workflows for all three callers.

**Requirements**:
- Given local testing, should show PLAYWRIGHT_SERVICE_URL and a placeholder PLAYWRIGHT_SERVICE_ACCESS_TOKEN in a gitignored .fab-test/.env, retain separate Fabric credential settings, and never ask the user to paste secrets into chat.
- Given GitHub Actions, should document PLAYWRIGHT_SERVICE_ACCESS_TOKEN as an Actions secret and PLAYWRIGHT_SERVICE_URL as a variable mapped into the test step's environment, including protected-environment scope where used.
- Given Azure DevOps, should document a secret variable or protected variable group for the token and explicit environment mapping into the test step.
- Given either CI system, should provide the Python install and invocation steps, JUnit and evidence publication after failure, and failure propagation without Node/npm or secrets in committed YAML.
- Given first Azure setup, should explain enabling workspace access-token authentication, token expiry and rotation, and that Azure-hosted browsers do not imply Azure portal reporting.
- Given the finished feature, should synchronize README, walkthroughs, QUICK-VALIDATION, the authored and packaged fab-test skills, and safe scaffolding through the document workflow.

---

## Quality gates

Verify the complete change through the installed CLI and the repository's required CI gates.

**Requirements**:
- Given the finished epic, should pass whole-repository ruff check ., the complexity and module-budget ratchets with ruff installed, full-suite coverage at or above 80%, and environment-sensitive tests with GITHUB_ACTIONS=true and CI=true as CI runs them.
- Given the installed console script, should verify default local execution and a live token-authenticated Azure run with multiple generated cases, capturing sanitized evidence of remote execution and equivalent results.
- Given both workflow examples, should verify their syntax, secret/variable mappings, artifact publication, and exit propagation, and disclose any platform whose live run remains unverified rather than marking the epic completed.