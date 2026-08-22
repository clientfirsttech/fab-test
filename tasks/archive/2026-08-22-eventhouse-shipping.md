# Eventhouse Shipping Epic

**Status**: ✅ COMPLETED (2026-08-22) — 9/9 tasks.

> **Verified against a real Eventhouse (2026-08-22).** §5's requirement — that a
> record be confirmed *queryable*, not merely accepted — is met. A `fab-test bpa`
> run against `trd-2r5mk6nt03ycj37zre.z2` delivered one record that became
> queryable with all 19 payload keys and the results envelope nested intact, and a
> `fab-test all` run delivered four more, routed correctly: `pql_test` to
> `fabric_dynamic_analysis`, the rest to `fabric_static_analysis`. Authenticated
> through the `DefaultAzureCredential` fallback with no service principal set, so
> that path is exercised too. `actor` arrived hashed, never as a raw email.
>
> The tables carry a single `Data: dynamic` column with a fixed `fab_test_payload`
> ingestion mapping, so downstream Eventhouse functions own the schema and a new
> payload field is a new key rather than a table alteration. That mapping is what
> the live test added to the implementation: without it Kusto maps by column name,
> matches nothing, and stores empty rows while reporting success — a defect no
> amount of mocking would have surfaced.

**Goal**: Actually ship telemetry to Eventhouse, addressed from `fab-test.yml` and authenticated with the credentials the CLI already has.

## Overview

Today `fab-test` reports that it sent telemetry and sends nothing.
[`publish_to_eventhouse`](../src/fabric_ci_cd_dataops/scripts/eventhouse_logger.py)
prints a banner ending in `✅ TELEMETRY LOGGING SIMULATION COMPLETED` and returns
`True`, so every caller — the analyzer wrapper, the exception handler that would
warn on failure, a pipeline reading the exit code — is told it worked. Nothing
reads `EVENTHOUSE_URI`, the Kusto SDK is not a dependency, and `fab-test.yml` has
no telemetry keys at all: its schema is `additionalProperties: false`, so a
`telemetry:` block today is a validation *error*, not an ignored key.

The [Telemetry Context epic](archive/2026-08-18-telemetry-context-epic.md) built
the payload — git context, CI origin, machine context, PII redaction, schema
validation, a `--dry-run` preview. It never built the wire, and its own wording
("the payload is sent as it is today") was true and concealed that. This epic
builds the wire, gives it an address in the config file, and points it at the
service principal the CLI already resolves.

Enablement follows the precedence rule the project already documents — CLI flag >
env var > config file > packaged default — so **a configured Eventhouse is the
enablement and there is no new flag**. `--no-telemetry` still refuses,
`--telemetry` still forces, `ENABLE_EVENTHOUSE_LOGGING` still works, and
`fab-test config --show` names the layer the URI came from like every other
setting.

The Kusto client ships as an optional extra (`pip install fab-test[telemetry]`).
An egress-capable client does not belong in every install of a tool whose main
job is reading files on a laptop.

**Non-goal**: creating the Eventhouse, its database, or its tables. The
[reference schema](https://github.com/kerski/pbi-teams-more-analytic-support) is
the system of record and remains so.

---

## Telemetry Has An Address In The Config File  ✅

Add a `telemetry` block to `fab-test.yml` and its published schema, resolved
through the same layer chain and origin tracking as every other setting.

**Requirements**:
- Given a `telemetry.eventhouse.uri` and `.database` in `fab-test.yml`, should resolve them like `artifact_dir` and `timeout` do rather than through a second mechanism
- Given the schema is `additionalProperties: false`, should accept the new block — a `telemetry:` key is a validation error today, so a user following any documentation would be refused
- Given `fab-test config --show`, should list the Eventhouse URI and database with the layer each came from, so a caller can tell a config-file value from an environment variable without guessing
- Given `EVENTHOUSE_URI` is set as an environment variable, should win over the config file, matching the documented flag > env > config > default order
- Given no telemetry block anywhere, should report nothing new in `config --show` — an absent optional section is a default, not a missing file worth naming
- Given the table name is derived from the analyzer (`fabric_static_analysis` / `fabric_dynamic_analysis`), should stay derived and not become a config key — one fewer thing to get wrong, and the derivation already exists

---

## One Rule Decides Whether Telemetry Ships  ✅

Make configuration the enablement, without breaking the two switches that exist.

**Requirements**:
- Given a configured Eventhouse URI and no flags, should ship — the reason to configure a destination is to send to it
- Given `--no-telemetry`, should send nothing regardless of configuration, and build no payload at all
- Given `--telemetry` with no configured URI, should refuse with the config key and environment variable that would fix it, rather than silently doing nothing — an explicit request that quietly no-ops is the failure this epic exists to end
- Given `ENABLE_EVENTHOUSE_LOGGING=true` and no config file, should keep working exactly as it does now
- Given `ENABLE_EVENTHOUSE_LOGGING=false` with a configured URI, should not ship — an explicit off beats an implicit on
- Given `--telemetry --dry-run`, should print the resolved destination (URI, database, table) alongside the payload it already previews, so a caller can confirm where it would go before it goes

---

## The Ingest Client Is An Optional Extra  ✅

Add the Kusto SDK as `fab-test[telemetry]`, imported only when telemetry runs.

**Requirements**:
- Given `pip install fab-test`, should install no Kusto SDK and no new transitive tree — the base install stays a file-reading tool
- Given `pip install fab-test[telemetry]`, should install `azure-kusto-data` and `azure-kusto-ingest`
- Given telemetry is configured but the extra is not installed, should fail with `pip install fab-test[telemetry]` in the message rather than an `ImportError` traceback
- Given telemetry is not configured, should never import the Kusto SDK — import cost is paid by the runs that use it, as `_credentials` and `_target` already do
- Given the extra is declared, should assert it in a test the way `test_packaged_metadata.py` asserts wheel contents: `package-data` entries were declared for months against directories that did not exist

---

## The Credentials It Already Has  ✅

Authenticate ingest with the service principal the CLI already resolves, with the
same ambient fallback.

**Requirements**:
- Given `FABRIC_TENANT_ID`, `FABRIC_SERVICE_PRINCIPAL_ID`/`FABRIC_CLIENT_ID`, and `FABRIC_SERVICE_PRINCIPAL_SECRET`/`FABRIC_CLIENT_SECRET`, should authenticate ingest with them — no `EVENTHOUSE_*` credential variables, no second `.env` convention
- Given no service-principal variables at all, should fall back to `DefaultAzureCredential`, matching `build_fabric_service_client`'s documented rule
- Given a *partially* set service principal, should treat it as a mistake and refuse rather than silently falling back to ambient auth — the same rule, for the same reason
- Given a `.env` file at the repository root, should read it without mutating `os.environ`, as the existing resolution already does
- Given the service principal lacks the **Database Ingestor** role on the KQL database, should report that as the cause rather than a generic auth failure — a valid credential with no grant is the most likely first-run failure and looks identical to a bad secret

---

## The Placeholder Goes  ✅ (live ingest verified 2026-08-22)

Replace the simulation with a real ingest, batched per run.

**Requirements**:
- Given a configured and reachable Eventhouse, should ingest the payload so it is queryable in the target table — verified against a real Eventhouse, not a mock, before this task is called done
- Given a run over N artifacts, should not build a client per artifact: `_send_telemetry` is called from `_run_one_artifact`, so a naive port pays connection setup N times
- Given the run ends, should flush what it batched, including when the run failed — telemetry about failing runs is the telemetry worth having
- Given `publish_to_eventhouse` returns `True` today for a send that never happened, should return `True` only when the ingest was accepted
- Given the banner output (`SIMULATION COMPLETED`, the "to be implemented" block, the emoji preview), should be gone — it is 60 lines of stdout per artifact and it says the opposite of the truth
- Given `eventhouse_logger.py` is on the coverage omit list as needing a live service, should either earn a seam that can be driven without one or stay omitted deliberately — decided in this task, not left to drift

---

## Failure Is Non-Blocking, Never Silent  ✅

Telemetry must not fail a run, and must not claim to have worked.

**Requirements**:
- Given the Eventhouse is unreachable, should warn and let the analyzer's own exit code stand — the existing boundary handler is right and stays
- Given ingest fails, should say so once per run rather than once per artifact — N identical warnings for one unreachable cluster is noise that hides the next problem
- Given `--format json`, should keep every telemetry message on stderr, leaving stdout exactly one JSON document
- Given ingest fails, should record that in `run.json` so a pipeline reading the manifest can tell a run whose telemetry was lost from one whose telemetry landed
- Given a run where telemetry silently did nothing, should be impossible to produce: every path either ships, refuses with a reason, or warns

---

## Doctor Tells The Truth About Telemetry  ✅

`fab-test doctor` reports on every analyzer and says nothing about telemetry.

**Requirements**:
- Given telemetry is configured, should appear in `doctor` with the same ✅/❌ and remediation shape as an analyzer — it is a prerequisite that can be missing in four distinct ways
- Given the `[telemetry]` extra is not installed, should report that with the install command
- Given no credentials resolve, should report that with the variables to set, reusing the wording the analyzers already use
- Given credentials resolve but the ingest role is missing, should not report ready — `doctor` previously reported four cloud analyzers ready with no credentials at all, and that false green is the failure mode to avoid repeating
- Given telemetry is not configured at all, should say so plainly rather than reporting a failure — unconfigured is not broken

---

## Secrets Never Reach The Wire Or The Log  ✅

**Requirements**:
- Given a payload is built, should carry no credential value — the secrets constraint puts telemetry alongside stdout, envelopes, and the run manifest
- Given an ingest error message from the Kusto SDK, should pass through `redact_secrets` before it is printed or recorded, since SDK errors can quote a connection string
- Given `--telemetry --dry-run`, should print the resolved URI and database but never the secret used to reach them
- Given the payload's actor field, should keep the existing PII redaction rather than introduce a second rule

---

## Documentation For All Three Callers  ✅

**Requirements**:
- Given the human, should find the `telemetry` block, what enables shipping, the `[telemetry]` extra, and the Database Ingestor grant in README and `docs/QUICK-VALIDATION.md`
- Given the pipeline, should find a copy-pasteable YAML snippet installing `fab-test[telemetry]` and setting the credentials, next to the existing `run.json` upload snippet
- Given the agent, should read the config keys, the enablement rule, and the failure modes from `.github/skills/fab-test/SKILL.md`
- Given a reader of the archived Telemetry Context epic, should not be left believing telemetry shipped before this epic — that epic's "sent as it is today" is what hid a placeholder for months, so say plainly where the wire actually starts
- Given `docs/RELEASE.md` documents the publish path, should note that the `[telemetry]` extra resolves from the same indexes and needs the same `--extra-index-url` on TestPyPI
