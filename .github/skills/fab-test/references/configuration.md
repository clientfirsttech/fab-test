# Configuration

`fab-test.yml` at the repository root is an entirely optional config-file front door. No file at all means every setting resolves exactly as it did before this file existed.

```bash
fab-test --config custom.yml bpa   # --config must come before the subcommand: it's a top-level flag
fab-test init                      # scaffold fab-test.yml, .fab-test/.gitignore, .fab-test/.env.example
fab-test init --dry-run            # see what init would create without writing anything
fab-test config --show             # every effective setting, its value, and where it came from
fab-test config --validate         # confirm the config file's keys and types are valid
```

## Precedence

| Priority | Source | Example |
|----------|--------|---------|
| 1 (highest) | CLI flag | `--jobs 4` |
| 2 | Environment variable | `ANALYZER_TIMEOUT=300` |
| 3 | `fab-test.yml` (or `[tool.fab-test]` in `pyproject.toml`) | `jobs: 4` |
| 4 (lowest) | Packaged default | `200` seconds |

If both `fab-test.yml` and `[tool.fab-test]` are present, `fab-test.yml` wins per key and the CLI warns once about the duplicate source. `fab-test config --show --format json` reports each setting's origin as one of `flag`, `env:NAME`, `fab-test.yml:key`, or `default`.

## Settings

| Key | Type | Env var | Default |
|-----|------|---------|---------|
| `artifact_dir` | string | — | the working directory |
| `output_dir` | string | — | `fab-test-results` |
| `jobs` | integer | — | `1` |
| `format` | string (`text`\|`json`) | — | `text` |
| `timeout` | integer | `ANALYZER_TIMEOUT` | `200` |
| `environment` | string | `FABRIC_ENVIRONMENT` | (none) |
| `workspace` | string | `FABRIC_WORKSPACE_ID` | (none) — display name or GUID |
| `report` | boolean | `ANALYZER_REPORT` | `false` — see [Reports](reports.md) |
| `rules` | object | — | (none) — see Rule Overlays below |
| `telemetry` | object | — | (none) — see Telemetry below |

An unknown key exits `2` naming the key and the closest valid key (e.g. `artifac_dir` → "did you mean 'artifact_dir'?"); a key with the wrong type exits `2` naming the expected type.

## Telemetry

Optional. `fab-test` ships one record per analyzer/artifact to a Fabric Eventhouse.

```yaml
telemetry:
  eventhouse:
    uri: https://<cluster>.kusto.fabric.microsoft.com   # env: EVENTHOUSE_URI
    database: fabric_ops                                 # env: EVENTHOUSE_DATABASE
```

**Configuring a complete destination is what enables shipping.** There is no separate on switch. `eventhouse.table` is not a key — the table is derived from the analyzer (`pql-test` → `fabric_dynamic_analysis`, everything else → `fabric_static_analysis`).

`fab-test init` scaffolds this block commented out in the generated `fab-test.yml`, alongside the `rules:` example, so it's discoverable without reading this skill.

Resolution order for whether a run ships, highest first:

| Precedence | Signal | Effect |
|---|---|---|
| 1 | `--no-telemetry` | Never ships; no payload is built |
| 2 | `--telemetry` | Ships — or exits `2` if no destination is configured |
| 3 | `ENABLE_EVENTHOUSE_LOGGING=false` | Never ships, even with a destination configured |
| 4 | `ENABLE_EVENTHOUSE_LOGGING=true` | Ships if a destination is configured; warns if not |
| 5 | A complete `telemetry.eventhouse` | Ships |
| 6 | Nothing | Does not ship, and says nothing about it |

**Table setup is automatic.** Before each run's first send, `fab-test` checks that the target table and its `fab_test_payload` ingestion mapping exist and creates whatever is missing — once per table per run, against the *query* endpoint. A run against a healthy destination issues no schema commands.

| Object | Created by `fab-test`? |
|---|---|
| Eventhouse | No — create it in Fabric |
| KQL database | No — a missing one is reported, not built |
| `fabric_static_analysis` / `fabric_dynamic_analysis` | Yes, as `(Data: dynamic)` |
| `fab_test_payload` ingestion mapping | Yes, `[{"column":"Data","path":"$","datatype":"dynamic"}]` |

Ingesting needs **Database Ingestor**; creating a table needs more than that. When the credential may ingest but not create, the run reports it and prints the KQL to run by hand:

```kusto
.create-merge table fabric_static_analysis (Data: dynamic)
.create-or-alter table fabric_static_analysis ingestion json mapping 'fab_test_payload'
    '[{"column":"Data","path":"$","datatype":"dynamic"}]'
```

The mapping name is fixed and the mapping is **not optional**: without it Kusto maps by column name, matches nothing, and stores empty rows while reporting success — which is why an existing table is not assumed usable until its mapping is confirmed. Query the payload with `Data.analyzer`, `Data.status`, `todatetime(Data.timestamp)`, and so on.

A destination that cannot be reached or built is a **failed** flush, never a delivered one: queued ingest accepts a batch aimed at a missing table and drops it later, so `fab-test` refuses to send rather than report a delivery that cannot land.

**What a record identifies.** `Data.actor` carries the identity as given — `GITHUB_ACTOR` in CI, otherwise `git config user.email` — so a row can be grouped by who produced it. It is not hashed: the repository already stores that address in plaintext on every commit, and an opaque digest answered "was this the same person as last time" and nothing else. `Data.repository` follows the same CI-env-var-first, local-git-fallback pattern: `GITHUB_REPOSITORY` in CI, otherwise `owner/repo` parsed from the local `origin` remote (HTTPS or SSH); empty when neither resolves.

Filesystem paths in the payload, including those inside the embedded `results` envelope, are rewritten **repository-relative** (`.fabric\artifacts\Sales.SemanticModel`, not `C:\Users\<name>\...`). A path outside the repository is reduced to its final component rather than a `../../..` traversal. This is deliberate and worth knowing when querying: `Data.results.artifact_path` is relative, while the same field in the envelope on disk stays absolute, because a human clicking a result wants the full path and an Eventhouse row does not.

Prerequisites, all reported by `fab-test doctor`'s `telemetry` row:

- `pip install 'fab-test[telemetry]'` — the Kusto ingest client is **not** in the base package.
- Credentials: the same `FABRIC_TENANT_ID` / `FABRIC_SERVICE_PRINCIPAL_ID` / `FABRIC_SERVICE_PRINCIPAL_SECRET` the analyzers use, falling back to `DefaultAzureCredential` when none are set. A *partially* set principal is refused rather than silently falling back. There are no `EVENTHOUSE_*` credential variables.
- The **Database Ingestor** role on the KQL database. `doctor` never reports telemetry as ✅ ready — a resolvable credential is not proof it may ingest, so the row shows `ℹ` with `configured; ingest permission unverified`.

Failure modes an agent should expect:

| Situation | What happens |
|---|---|
| `--telemetry`, nothing configured | Exit `2` before any analyzer runs, naming the config key and the env var |
| Requested, nothing configured (via `ENABLE_EVENTHOUSE_LOGGING=true`) | Runs normally; one `::warning::`; `run.json` `telemetry_error` set |
| Extra not installed | One warning naming `pip install 'fab-test[telemetry]'`; exit code unchanged |
| Ingest rejected (403) | One warning naming the Database Ingestor role; exit code unchanged |
| Cluster unreachable | One warning per **run**, not per artifact; exit code unchanged |
| Table or mapping missing and uncreatable | Flush reported **failed**, nothing sent, error carries the KQL; exit code unchanged |

**What a record identifies.** `actor` is the git email (`git config user.email`, or `GITHUB_ACTOR` in a pipeline), recorded as given — the same address the repository stores on every commit — or an empty string when nothing resolves. Every filesystem path in the payload, including those inside the embedded `results` envelope, is rewritten relative to the repository root; a path outside the repository is reduced to its final component. Neither is cosmetic: an absolute path on a laptop is `C:\Users\<name>\…`, so before this the operating-system username shipped in plaintext in every record while `actor` was hashed into something nobody could resolve — identifying people by accident and failing to identify them on purpose.

Telemetry never changes a run's exit code, never writes to stdout under `--format json`, and never carries a credential value into the payload, the log, or `run.json` — failure text is redacted before it is reported. `--dry-run` prints the resolved cluster, database, and table alongside each payload without sending anything.

## Rule Overlays

Tune one Best Practice Analyzer or PBIR Inspector rule without forking the packaged rules file:

```yaml
rules:
  bpa:
    disable: [AVOID_FLOATING_POINT_DATA_TYPES]   # remove a rule from the effective ruleset
    severity: {SOME_RULE_ID: warning}            # info | warning | error
    extend: path/to/extra-bpa-rules.json         # append rules from another file
  pbir:
    disable: [REMOVE_CUSTOM_VISUALS_NOT_USED]
    severity: {SOME_RULE_ID: warning}            # warning | error (PBIR Inspector has no "info" level)
```

An overlay naming a rule ID that doesn't exist upstream exits `2` listing every unmatched ID. When any overlay is configured, the resolved ruleset is written to `<output_dir>/{bpa,pbir}/_resolved-rules.json` and passed to the tool; the envelope's `rules_file` field always names whichever rules file was actually used, so a finding is traceable back to the resolved ruleset it came from. Passing `--bpa-rules-path`/`--rules-path` explicitly bypasses the overlay entirely — that file is used verbatim.

The full schema ships with the package at `schemas/fab-test.schema.json` (draft 2020-12) for editor completion.

## Metadata files and where they come from

Five files drive the CLI. Each resolves through the same three layers, first match wins:

| Layer | Path | Create it? |
|-------|------|------------|
| 1 (highest) | `.fab-test/metadata/` | Yes — the documented place for your own copies |
| 2 | `.github/metadata/` | No — legacy; still searched so existing repositories keep working |
| 3 (lowest) | packaged with the distribution | n/a — ships inside the wheel |

| File | Packaged fallback |
|------|-------------------|
| `rules/BPARules.json` | Yes |
| `rules/pbi-inspector-custom-rules.json` | Yes |
| `analyzers.json` | Yes |
| `artifact-map.json` | Yes |
| `environments.yml` | **No** |

An absent override is a default, not a problem: nothing warns when a file falls through to
the packaged copy. `fab-test config --show` reports which layer each ruleset came from, so an
override is distinguishable from the packaged copy without guessing from the path.

`environments.yml` is the deliberate exception. It carries workspace GUIDs and branch policy,
so a copy shipped in the wheel would aim a `prod` deployment at whatever workspace happened to
be packaged — and report success doing it. It is also only consulted once no workspace has
already resolved from `--workspace-id`, `FABRIC_WORKSPACE_ID`, or `workspace:` in
`fab-test.yml` — with none of those set either, the command fails naming every route, not
only the metadata file:

```
environments.yml not found. Create it at /repo/.fab-test/metadata/environments.yml or /repo/.github/metadata/environments.yml. Alternatively, set `workspace:` in fab-test.yml, FABRIC_WORKSPACE_ID, or pass --workspace-id -- any of those resolves a workspace without environments.yml.
```

`playwright` needs an environment as well as the file, because it resolves an artifact name
against a deployed item. With none set it fails *before* authenticating, so the message names
the missing flag rather than a credential problem:

```
::error::No environment given, so there is nothing to resolve 'ThinReport' against. Pass --env, set FABRIC_ENVIRONMENT, or set `environment:` in fab-test.yml.
```

Exit code `1`, one `::error::` line on stderr, no traceback. The same sentence reaches
`run.json` as the artifact's `detail`, so an agent reading only the manifest gets the
remediation without parsing the log.

## What belongs in `fab-test.yml` vs. repository secrets

`fab-test.yml` is meant to be committed — it holds no credentials. Service-principal credentials (`FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`) belong in a `.env` file or, in a pipeline, in the CI system's own secrets store — never in `fab-test.yml`. With no service-principal variables set at all, Fabric REST calls fall back to `DefaultAzureCredential` (`az login`, a managed identity, VS Code sign-in, ...) for every command except `fab-test playwright`, which always needs the full service principal (see the `playwright` subcommand section in [Flags](flags.md)).

**`.env` discovery order**, defined once and shared by `_credentials.py` and the Playwright config loader so they cannot disagree: `--env-file` > `PLAYWRIGHT_ENV_FILE` > `.fab-test/.env` > `./.env`. `.fab-test/.env` is preferred when both exist. `fab-test init` scaffolds `.fab-test/.gitignore` (containing `.env`) and `.fab-test/.env.example` alongside it, so a real `.env` in the same directory as the committed `.fab-test/metadata/` is protected by fab-test's own scaffolding rather than depending on a consumer's root `.gitignore` already covering it. A root `.env` keeps working unchanged when no `.fab-test/.env` exists. `fab-test auth status` reports which one actually supplied a credential (`.fab-test/.env`, `.env`, or `environment`).
