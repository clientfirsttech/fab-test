# SQL Database Unit Testing (T-TEST) Epic

**Status**: 📋 PLANNED — all decisions recorded; awaiting the example repository before verification.
**Goal**: Add a `sqldb-test` analyzer that installs [T-TEST](https://github.com/uratol/t-test) idempotently into a Microsoft Fabric SQL database, runs its pure T-SQL unit tests, and reports through the same envelope, HTML report, exit codes, and telemetry as every other fab-test check.

## Overview

WHY: SQL databases in Fabric have no unit-testing story in fab-test, and tSQLt — the usual answer — needs CLR, which a Fabric SQL database does not allow. T-TEST is 100% T-SQL: two schemas (`test` for the framework, `tests` for the user's procedures), assertions written as scalar functions, and a self-discovering runner (`test.run`) over the `test.test` view. It fits the vision's "facade, not fork" principle: fab-test wraps the upstream `install.sql` unmodified, adds the contract (discovery, readiness, envelope, exit codes, report, telemetry), and leaves the assertions to upstream.

Two callers drive the design, mirroring Playwright's workspace-discovery contract:

| Mode | Invocation shape | Denominator |
|------|------------------|-------------|
| **Repository** | `fab-test sqldb-test` (bare) or `--artifact-dir PATH` | Every `*.SQLDatabase` folder found in the repo (Fabric Git-integration layout); each is resolved by display name in the workspace and tested there |
| **Remote** | `fab-test sqldb-test --workspace WS --artifact DB` (names or GUIDs) | Exactly the named deployed database; no repository scan |

Facts that shape the plan (verified against upstream `install.sql`, 20 KB, MIT):

- `install.sql` uses plain `CREATE SCHEMA/VIEW/FUNCTION/PROCEDURE` — **not idempotent**; a second run fails on the first existing object. fab-test must own idempotency.
- It ends with `EXEC test.run`, which runs the bundled self-tests in `[tests]` (e.g. `[tests].[test.format_message]`). Those self-tests would pollute user results unless excluded.
- `test.run` reports through `RAISERROR(..., 0, 1) WITH NOWAIT` info messages and throws on failure; there is **no results table**. Structured per-test results therefore have to come from fab-test enumerating `test.test` and executing each test itself.
- `test.log` declares `WITH EXECUTE AS 'dbo'`, and the self-test uses `IS DISTINCT FROM` (SQL 2022 compat). Both need a live check on Fabric SQL database before readiness is declared.
- T-TEST has no coverage feature, and neither do tSQLt nor Flyway; code coverage is parked (see the Parked section).

---

## Approve Targeting, Auth, And Decisions

Lock the contract before changing the parser or registry, as the Playwright epic did.

**Requirements**:
- Given `fab-test sqldb-test` with no workspace flag, should discover `*.SQLDatabase` folders under the CWD/`--artifact-dir`, resolve each by display name in the configured workspace (`--workspace`, `FABRIC_WORKSPACE_ID`, `workspace:` in config, or `--env`), and test each deployed database.
- Given `--workspace WS --artifact DB`, should test only that deployed SQL database, accept a GUID or display name for each, and never scan the repository.
- Given `--workspace WS` alone (no `--artifact`, no explicit `--artifact-dir`), should list every deployed SQLDatabase in the workspace and test each (decision 6, Playwright's standalone behaviour), naming each database it will install into in the run output and `--dry-run`.
- Given `--artifact-dir PATH --workspace WS`, should use the local folders as the denominator and resolve their names in WS, including when PATH is `.`.
- Given the positional target grammar, should accept `WS.Workspace/DB.SQLDatabase` for remote and `./src/DB.SQLDatabase` / `DB.SQLDatabase` for repository, via `ANALYZER_SCOPES["sqldb_test"] = {"path", "workspace"}`.
- Given a missing, ambiguous, or wrong-type name, should name the failure and remediation (use a GUID), never pick one arbitrarily.
- Given a service principal (`FABRIC_TENANT_ID` + `FABRIC_SERVICE_PRINCIPAL_ID`/`FABRIC_CLIENT_ID` + secret, env > `--env-file` > `.fab-test/.env` > `./.env`), should authenticate non-interactively; given none, should fall back to `DefaultAzureCredential` (az login / VS Code / managed identity) — the existing `build_azure_credential` rule, so there is one credential path.
- Given `--interactive` on a laptop, should sign in with `InteractiveBrowserCredential` (decision 7) in memory only: no device-code flow, no persistent or encrypted token cache (`cache_persistence_options` unset), nothing written to disk; the token lives for the process only. Given CI (`CI`/`GITHUB_ACTIONS`/`TF_BUILD` set) or no `--interactive`, should never prompt.
- Given a partially configured principal, should fail with `IncompleteServicePrincipalError`'s remediation rather than fall back.
- **Decisions** (recorded 2026-10-03 at review):
  1. ✅ Subcommand `sqldb-test`, registry key `sqldb_test`, alias `t-test`.
  2. ✅ SQL driver: `mssql-python` (pip-only, built-in Entra auth, no ODBC install) as a new optional extra `sqldb`. Missing extra => exit `127` naming `pip install "cft-fab-test[sqldb]"`, as other analyzers do for a missing tool.
  3. ✅ Repository mode is **run-only**: test procedures reach the database through Fabric Git sync or the user's own deployment; fab-test never creates or alters `[tests]` procedures (deployment stays a vision non-goal).
  4. ✅ A database with no user `[tests]` procedures is `skipped`, with a hint pointing to the `t-test` skill.
  5. ✅ Upstream version: track the **latest** `install.sql` from the T-TEST default branch, verified by checksum — fab-test records the sha256 (and commit SHA) of the script it installs, compares it with the database's marker to decide no-op vs. upgrade, and the tool-update check surfaces when upstream changes.
  6. ✅ `--workspace WS` alone tests every deployed SQLDatabase in the workspace.
  7. ✅ `--interactive` offers a browser sign-in for laptop users — no device code, and the token is never saved, cached to disk, or stored encrypted; `az login` / `DefaultAzureCredential` remains the default.
  8. ✅ `sqldb-test` runs in `fab-test all` only when a workspace is configured; never in `fab-test local`.

---

## Idempotent T-TEST Installation

Install or upgrade the framework without ever failing on a database that already has it.

**Requirements**:
- Given a database with no `test` schema, should execute upstream `install.sql` split on `GO` batches, skipping the trailing `EXEC test.run` batch so install never reports self-test output as user results.
- Given a run, should fetch the latest `install.sql` from the T-TEST default branch (cached under the tool cache, refreshed per the existing update-check rules) and compute its sha256; given a download failure, should fall back to the cached copy with a `warning`, or exit with remediation when none is cached.
- Given a database whose marker (`sys.extended_properties` on schema `test`, e.g. `fab_test.t_test_sha256` plus `fab_test.t_test_commit`) matches the script's sha256, should detect it and do nothing.
- Given a marker with a different sha256, or a `test` schema with no marker, should upgrade by rewriting each `CREATE` batch for the `test` schema to `CREATE OR ALTER` (schemas guarded with `IF SCHEMA_ID(...) IS NULL`), then update the marker; should never drop or alter anything in `[tests]` except the upstream self-test procedures.
- Given the upstream self-tests in `[tests]` (`test.*`), should install them only when `--include-framework-tests` is set, and always exclude them from user runs and results.
- Given `--install never`, should fail readiness with remediation if T-TEST is absent; given `--install auto` (default) should install/upgrade; given `--install only`, should install and exit without running tests (CI pre-step).
- Given the caller lacks `CREATE SCHEMA`/`ALTER` permission, should exit with an error envelope naming the required role (`db_owner` or `db_ddladmin`) rather than a raw driver error.
- Given `--dry-run`, should print the planned install action (none/install/upgrade) without connecting for writes.
- Given the same command run twice, should produce identical database state and a `no-op` install record in the envelope — an explicit idempotency test against a fake connection and once live.
- Given the upstream install script as an external tool, should register `tool_install.release_source` in `analyzers.json`, a `THIRD-PARTY.md` row (MIT), `_WRAPPED_TOOLS`, and `tools/check_tool_updates.py` coverage so upstream changes surface like other tool updates.

---

## Connect, Resolve, And Run Tests

Turn each targeted database into a list of executed tests with structured results.

**Requirements**:
- Given a workspace and database (name or GUID), should resolve the connection via Fabric REST `GET /v1/workspaces/{ws}/sqlDatabases/{id}` (`properties.serverFqdn`/`connectionString`, `databaseName`), reusing the existing Fabric service client and workspace resolver.
- Given a credential, should acquire a token for `https://database.windows.net/.default` and connect with TLS (`Encrypt=yes`); tokens and secrets must never reach stdout, the envelope, manifest, or telemetry (`redact_secrets`).
- Given an installed framework, should enumerate tests from `test.test` (`test_proc_full_name`, `tested_object_full_name`, `tested_action`), honoring `--test-names`, `--exclude-test-names`, `--schemas`, `--exclude-schemas` with T-TEST's own semantics.
- Given each selected test, should execute it individually (`EXEC test.run @test_names = N'<name>'`) so `@before_callback` and logging semantics stay upstream's, capturing pass/fail, error number, message, info messages, and duration.
- Given `--limit-failed N`, should stop after N failures and mark the remainder `skipped`, mirroring upstream `@limit_failed`.
- Given a test that leaves an open transaction, should roll it back and record a `warning` finding (T-TEST relies on `BEGIN TRAN / ROLLBACK` for isolation).
- Given `--timeout`, should cancel a hung test, record it as `error`, and continue.
- Given results, should emit `test_results` in the test shape (`suite_name` = tested object schema, `test_name`, `passed`, `expected`, `actual` parsed from `assert_equals` messages where present) and one `error` finding per failed test (`rule` `TTEST-FAIL` / `TTEST-ERROR`, `object` = test proc), so existing summary and HTML tables render unchanged.
- Given the analyzer contract, should exit 0 when all pass, 1 on any failure or tool/connection error (always writing an error envelope first), and honour `ANALYZER_OUTPUT_MODE=json`, `ANALYZER_VERBOSITY`, `-q`, and `--verbose`.
- Given zero user tests in `[tests]`, should report `skipped` (decision 4) with a hint to the `t-test` skill.
- Given `--native-output`, should write `native.txt` with the raw info-message stream so users can compare with an SSMS run.

---

## HTML Report, Summary, And Telemetry

Make results visible through the surfaces every analyzer already uses.

**Requirements**:
- Given an envelope, should call `attach_report` before `write_envelope` so `--report` / `--open-report` produce the per-artifact HTML with the test-results table and the findings table rendered by `_report_html.py`.
- Given a run over several databases, should appear in the run index, summary table, run manifest, CI annotations, and PR review comments with no new code in those consumers (envelope path parity: `<output>/sqldb_test/<db>/envelope.json`).
- Given telemetry is enabled, should route to `fabric_dynamic_analysis` in `_telemetry_table` (it executes against a live service), with `artifact_type` `SQLDatabase`, test counts, install action, and duration — never server names with credentials, tokens, or connection strings.
- Given `--telemetry --dry-run`, should show the payload that would ship.

---

## Registration And Reach

Make the analyzer discoverable like its siblings (per `aidd-analyzer-contract` checklist).

**Requirements**:
- Given the [Feature Flags epic](feature-flags-epic.md), should register the real builder (and `sqldb_test` in every registry, bundle, and readiness surface) only when `is_enabled("sqldb_test")`; while `FAB_TEST_ENABLE_SQLDB_TEST` is unset, `fab-test sqldb-test` is the disabled stub (exit `2`, "not enabled in this release"), no connection or credential is attempted, and `--help` is unchanged. Releasing the epic flips the flag's default to `True`, then deletes the entry.
- Given the artifact map, should add `.SQLDatabase` → `SQLDatabase` so discovery, `list`, and `explain` recognise the type.
- Given the registry, should add `ANALYZER_REGISTRY`, `ANALYZER_SCOPES`, `_COMMAND_BUILDERS`, `_CLOUD_ANALYZERS`, readiness, and `analyzers.json` (`analyzer_registry`, `artifact_analyzers.SQLDatabase.dynamic`).
- Given `fab_test_registry.py` and `fab_test_parser.py` sit at their module-budget ceilings, should split on their existing seams (or a new `_sqldb_target.py` / `sqldb_test/` package like `playwright_validation/`) rather than raise exemptions.
- Given `fab-test doctor`, should report readiness: driver extra installed, credential resolvable, and (with `--workspace`) connectivity and T-TEST install state, each with a named remediation.
- Given `fab-test all`, should include `sqldb-test` only when a workspace is configured, and otherwise list it as skipped with the flag that enables it; given `fab-test local`, should never include it (decision 8).
- Given a `rules.sqldb_test` overlay is not needed (no rules), should instead expose defaults (`install`, `schemas`, `limit_failed`) in `fab-test.schema.json` / `_config.py`.
- Given tests, should add a `sqldb_test` pytest marker in `pytest.ini` and `tests/conftest.py`, with a fake-connection seam so unit tests need no database, plus one opt-in `integration` test against the example repo.

---

## Verify Against The Example Repository

Prove both modes end to end with the user-supplied repo.

**Requirements**:
- Given the example repo (to be provided) checked out, should run repository mode with a service principal and with `az login`, and record per-database test counts and install action.
- Given the same databases, should run remote mode from an empty directory with names and with GUIDs and produce identical results.
- Given a second consecutive run, should show `install: no-op` and identical test verdicts.
- Given the real CLI, should run `sqldb-test`, `all`, `list`, `explain`, `doctor`, `--report`, `--open-report`, `--output-format json`, `-q`, and `--telemetry --dry-run` (blast-radius rule).

---

## Document All Three Callers And Skills

**Requirements**:
- Given the human caller, should update README and `docs/QUICK-VALIDATION.md` with install, repository-mode, and remote-mode examples (names and GUIDs), auth options, and report screenshots.
- Given the pipeline caller, should add copy-pasteable GitHub Actions and Azure DevOps snippets under `docs/examples/` (service principal secrets, `--install only` pre-step, JUnit-style results publish if needed).
- Given the agent caller, should update the fab-test skill (`.github/skills/fab-test/` and `references/flags.md`, `reports.md`, `targeting-and-discovery.md`, `credentials.md`) in SudoLang, synced byte-for-byte to `src/fab_test/skill/`.
- Given agents also need to *write* tests, should add a new `t-test` skill (`.github/skills/t-test/SKILL.md`, via `aidd-upskill`) covering naming (`[tests].[schema.object@action]`), `BEGIN TRAN/ROLLBACK`, assertion functions, the sentinel exception pattern, and when not to wrap in a transaction — linking to the `sqldb-*` skills for querying.
- Given an epic-sized `src/` change, should bump MINOR in `src/fab_test/__init__.py` (`.dev1`) and re-stamp both skill frontmatters; add a CHANGELOG entry via `aidd-log`.

---

## Quality Gates

**Requirements**:
- Given the whole repository, should pass `ruff check .`, `tests/test_complexity_budget.py` (with ruff installed), and `tests/test_module_budget.py`.
- Given the full suite, should pass with `--cov --cov-fail-under=80` over `src/fab_test`.
- Given CI-dependent tests, should pass once with `GITHUB_ACTIONS=true CI=true`.

---

## Parked: Code Coverage

Parked 2026-10-03 at review. Neither T-TEST, tSQLt, nor Flyway ships code coverage; in the tSQLt ecosystem it comes from a separate tool, [SQLCover](https://github.com/GoEddie/SQLCover), which captures executed statements with Extended Events (Redgate SQL Test surfaces SQLCover's results). Whether a Fabric SQL database permits a database-scoped Extended Events session is unverified. Revisit after the core analyzer ships, using SQLCover as the reference design and the example repository to confirm Extended Events support. Captured requirements, for when it is unparked:

- Given the `test.test` view and `sys.objects` (types `P`, `FN`, `IF`, `TF`, `V`, `TR`; excluding `test`, `tests`, and `sys`), should compute **object coverage**: objects with at least one test vs. total, per schema, listing untested objects.
- Given `--coverage statement` and a database where a database-scoped Extended Events session is permitted, should create a uniquely named session capturing `sp_statement_completed` / `sql_statement_completed` for the test connection, map `object_id` + offsets to statements, and report **statement/line coverage** per module; should always drop the session, even on failure.
- Given Extended Events are unavailable or not permitted, should fall back to object coverage with an `info` finding explaining why, never fail the run.
- Given `--coverage-min PCT`, should express a shortfall as an `error` finding (so `_artifact_exit_code` decides), matching the analyzer contract's rule for wrapper thresholds.
- Given coverage results, should write `coverage.json` and a Cobertura `coverage.xml` beside the envelope, so GitHub Actions / Azure DevOps coverage publishers work without custom YAML.
- Given repository mode, should optionally map module coverage back to the `.sql` files in the `.SQLDatabase` project for file-level annotations.
