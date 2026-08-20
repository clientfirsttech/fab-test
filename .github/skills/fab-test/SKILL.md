---
name: fab-test
description: fab-test CLI reference for running Fabric artifact analyzers locally. Covers all subcommands, flags, artifact isolation, result locations, and how fab-test differs from pytest. Use when invoking, troubleshooting, or extending local artifact validation.
---

# fab-test

`fab-test` runs analyzers against your `.fabric/artifacts` — the local equivalent of the CI artifact validation gate.
It is **not** `pytest`. Use `pytest` to test the analyzer wrappers; use `fab-test` to test your actual artifacts.

Entry point: `scripts/fab_test.py` (installed as `fab-test` console script via `pip install -e .`).

## Distinction from pytest

| Command | What it tests |
|---------|---------------|
| `pytest -m bpa` | Is the BPA wrapper code correct? (always green, no tools needed) |
| `fab-test bpa` | Do my `.fabric` artifacts pass BPA rules? (requires Tabular Editor) |
| `pytest -m pbir` | Is the PBIR wrapper code correct? (always green, no binary needed) |
| `fab-test pbir` | Do my reports pass PBIR Inspector rules? (requires PBIR Inspector binary) |
| `pytest -m pql_test` | Is the pql-test wrapper code correct? (mocked, always green) |
| `fab-test pql-test` | Do my semantic model DAX tests pass? (requires Power BI Desktop open) |
| `pytest -m pql_lint` | Is the pqlint wrapper code correct? (always green, no tools needed) |
| `fab-test pql-lint` | Do my semantic models pass Power Query lint rules? |
| `pytest -m playwright` | Is the Playwright wrapper code correct? (mocked contract tests) |
| `fab-test playwright` | Do my Power BI reports render without visual-load errors? (requires service-principal credentials) |

## Installation

```bash
pip install -e .
```

This registers the `fab-test` console script. The `.venv` is searched automatically for tool binaries (e.g. `pql-test`) even when not on `PATH`.

## Agent Contract

`fab-test` is built to be called identically by a human, a CI pipeline, and an AI agent.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All artifacts passed (warnings do not fail the build) |
| `1` | An analyzer found error-level findings, or the analyzer process crashed |
| `2` | Invalid CLI arguments (no analyzer was invoked) |
| `126` | Analyzer unsupported on this platform (message names the supported OS) |
| `127` | Required external tool could not be resolved (message names the flag, env var, and config key that would fix it) |

### JSON stdout guarantee

Every subcommand that accepts `--format json` writes **exactly one JSON document to stdout** — nothing else. Progress, banners, warnings, and any analyzer subprocess's own output are narrated to **stderr**. This holds even for `--dry-run`: a single analyzer's dry run emits a small `{"analyzer": ..., "dry_run": true, "artifacts": [...]}` summary rather than leaving stdout empty.

```bash
fab-test bpa --format json 2>/dev/null | jq .   # safe to pipe straight into jq
```

`--format text` (the default) is unaffected — output is unchanged from before this contract existed.

### Discoverability: doctor → list → explain

```bash
fab-test doctor                       # is each analyzer's tool/credential ready?
fab-test doctor --local               # readiness for the local Desktop workflow specifically
fab-test list                         # what subcommands exist, and how many artifacts match?
fab-test explain bpa                  # what command would `fab-test bpa` actually run?
```

`doctor` and `list` both support `--format json`. `doctor --analyzer NAME` checks one analyzer; `list`'s matched-artifact counts respect `--artifact-dir`. `explain ANALYZER` never spawns a subprocess — it only shows the resolved command, tool path, rules path, and output path.

`doctor --local` checks Python version, whether a Desktop instance is running, the Desktop Bridge CLI's presence (path only — never invoked), and each of `fab-test local`'s four analyzers, then states exactly which ones would run:

```bash
fab-test doctor --local --format json
```
```json
{
  "checks": [
    {"check": "python", "ready": true, "reason": "3.12.10", "resolved_path": "/usr/bin/python3.12", "remediation": null},
    {"check": "desktop", "ready": false, "reason": "no running instance detected", "resolved_path": null, "remediation": "Open a .pbip file in Power BI Desktop"}
  ],
  "would_run": ["bpa", "pbir", "pql_test"]
}
```

### The run manifest (`analyzer-results/run.json`)

Every analyzer invocation (a single subcommand or `all`) writes one `run.json` under `--output-dir` (default `analyzer-results/`), so a caller reads one file instead of globbing result directories:

```json
{
  "schema_version": 1,
  "fab_test_version": "1.0.0",
  "origin": "local",
  "target": {
    "raw": "local/SampleModel-PQLAssert",
    "scope": "desktop",
    "name": "SampleModel-PQLAssert",
    "type": null,
    "workspace": null,
    "workspace_id": null,
    "path": null
  },
  "command": ["fab-test", "bpa", "--format", "json"],
  "artifacts": [
    {
      "analyzer": "bpa",
      "artifact": "SampleModel-PQLAssert",
      "status": "passed",
      "envelope_path": "analyzer-results/bpa/SampleModel-PQLAssert/envelope.json",
      "errors": 0,
      "warnings": 21,
      "detail": null
    }
  ],
  "totals": {"errors": 0, "warnings": 21},
  "exit_code": 0
}
```

Per-artifact `status` is one of `passed` / `failed` / `skipped` / `timeout` / `preflight_failed` (the last two cover an aborted run). `detail` is `null` for a normal completion and carries the human-readable failure reason for the two abort statuses — the resolved remediation message for `preflight_failed`, the exceeded duration for `timeout` — so a caller never has to fall back to stderr to learn what to fix. `origin` is `"local"` when no CI environment variable is detected, or the detected CI system's name (`"github-actions"`, `"gitlab-ci"`, `"circleci"`, `"azure-devops"`) otherwise — the envelope schema, `status` values, and result layout are identical either way; this is the only field that differs between a local run and a CI run. The `command` field is sanitized: known credential flags (`--client-secret`, `--password`, `--token`, `--secret`, `--api-key`) and any `key=value`-shaped token have their value redacted before the file is written — no credential ever appears in the manifest.

`target` is the resolved target as a structured object, or `null` when the run discovered artifacts instead of being pointed at one. Branch on `scope` (`path` / `desktop` / `workspace`) rather than parsing `raw`. Where `origin` says local versus CI, `target` says whether the run read files on disk, a running Desktop instance, or a deployed workspace item — a distinction `origin` alone never answered. `workspace_id` is the GUID resolved from a workspace name; it names a workspace and grants access to nothing, so it is safe to record.

`doctor`, `list`, `explain`, `auth`, and `clean-tools` never write a manifest — they don't run an analyzer.

## Subcommands

```
 fab-test bpa              — Tabular Editor Best Practice Analyzer (SemanticModel artifacts)
 fab-test pbir             — PBIR Inspector static report analysis (Report artifacts)
 fab-test pql-test         — pql-test DAX/PQL test runner (SemanticModel artifacts) [alias: pql_test]
 fab-test playwright       — Playwright visual/error validation (Report artifacts)
 fab-test playwright-impact — Build impacted-report manifest from changed artifacts [alias: playwright_impact]
 fab-test dependencies     — Discover reports that depend on a deployed semantic model
 fab-test all              — Run the analyzers listed in analyzers.json
 fab-test local            — Run pql-lint, BPA, PBIR Inspector, and Desktop-bound pql-test — no cloud required
 fab-test doctor           — Check whether each analyzer's tool/credentials are ready
 fab-test doctor --local   — Check readiness for the local Desktop workflow specifically
 fab-test list             — List subcommands with artifact glob, matched count, and required tool
 fab-test explain ANALYZER — Show the resolved command for one analyzer without running it
 fab-test config --show    — Print every effective setting with its value and origin
 fab-test config --validate — Confirm fab-test.yml's keys and types are valid
 fab-test init             — Scaffold a commented fab-test.yml and .env.example
 fab-test auth status      — Show which identity fab-test would use, verified for real
 fab-test auth login       — Delegate sign-in to the tool that owns the credential
 fab-test clean-tools      — Remove or inspect the .fab-test-tools downloaded-binary cache
```

### Hidden subcommands

`pql-lint` is **hidden from the advertised surface**: it is absent from `--help`, `fab-test list`, and the default `doctor` report. It remains fully invocable — `fab-test pql-lint`, its `pql_lint` alias, `fab-test pql-lint --help`, `fab-test explain pql_lint`, and `fab-test doctor --analyzer pql_lint` all work exactly as before, and `fab-test local` still runs it. Hiding is a visibility state, never a removal: the backward-compatibility constraint in [vision.md](../../../vision.md) means existing commands keep working.

Underscore spellings (`pql_test`, `pql_lint`, `playwright_impact`) still work silently as aliases —
existing scripts and muscle memory keep working. Result directories under `analyzer-results/`
use the original underscore names regardless of which spelling you invoke.

## Targeting

Every analyzer subcommand takes an optional positional `TARGET` naming what to test. Omit it and `fab-test` discovers every matching artifact, exactly as before. The grammar is the one `pql-test` and the Fabric CLI already use, so a target pasted from either means the same thing here.

| Target | Means |
|--------|-------|
| *(omitted)* | Discover every matching artifact under `--artifact-dir` |
| `Sales` | The artifact named `Sales`; the analyzer's own glob picks the type |
| `Sales.SemanticModel` | That name **and** type — `Sales.Report` is not selected |
| `./src/Sales.SemanticModel` | Exactly that folder, wherever it lives (not confined to `--artifact-dir`) |
| `local/Sales` | The copy open in a running Power BI Desktop instance |
| `"Sales Dev.Workspace/Sales.SemanticModel"` | A deployed item in the named Fabric workspace |

Quote any target containing spaces. `./local/Sales` addresses a directory genuinely named `local` rather than the Desktop scheme.

### Which scopes each analyzer accepts

Run `fab-test list` for this table at any time — it has a Scopes column.

| Analyzer | path / name | `local/` | `WORKSPACE.Workspace/` |
|----------|-------------|----------|------------------------|
| `bpa`, `pbir`, `pql-lint` | yes | yes | **no** |
| `pql-test` | yes | yes | yes |
| `playwright`, `playwright-impact`, `dependencies` | yes | **no** | yes |

The file-reading analyzers accept `local/` because the artifact is on disk either way — only `pql-test` actually *binds* to the running instance. They refuse a workspace target because reading a deployed item would mean exporting its definition first, which belongs to `fabric-cicd-deployment`, not here. Asking for one exits `2` and names the forms that work:

```
$ fab-test bpa "Sales Dev.Workspace/Sales.SemanticModel"
  ✗ fab-test: bpa reads artifact files on disk and cannot fetch a deployed item.
    Use local/NAME for a running Power BI Desktop instance; a path
    (./src/Sales.SemanticModel) or a name (Sales.SemanticModel)
```

`fab-test all` **skips** an analyzer that cannot honor the target and says so, rather than failing the batch — so `fab-test all local/Sales` still runs everything that reads files.

### Scope-specific behavior

- `local/NAME` states the Desktop binding, so an ambient `FABRIC_WORKSPACE_ID` will **not** quietly turn the run remote. No running instance has that artifact open → exit `127`.
- A workspace name resolves to its ID before the analyzer runs. A GUID is used verbatim with no lookup. No match exits `1` and lists the workspaces the identity can see; an ambiguous name exits `2` and lists the candidate IDs.
- A `workspace:` key in `fab-test.yml` supplies a default; a positional workspace-qualified target overrides it. Passing both `--workspace-id` and a workspace-qualified target that disagree exits `2` naming both.
- `--artifact STEM` is a deprecated alias for `TARGET` and still works. Passing both exits `2`.

## Credentials

**`fab-test` stores no credentials of its own** — no token, no cache, no credential file anywhere. It reads whatever the environment already provides, and delegates sign-in to the tool that owns the credential. There is no `fab-test` token cache to look for.

### `fab-test auth status`

Reports which identity would be used, and unlike `doctor` it verifies for real — this is the one command allowed to acquire a token.

```bash
fab-test auth status                      # readable table
fab-test auth status --format json        # one JSON document on stdout
fab-test auth status --workspace-id <id>  # also check that workspace is reachable
```

| Code | Meaning |
|------|---------|
| `0` | An identity resolved and was verified |
| `1` | Credentials are fine, but the named workspace is not reachable with them |
| `127` | Nothing resolvable, or an ambient credential that failed to acquire a token |

Resolution order matches what actually authenticates: environment variables → `.env` file → ambient Azure credential (`az login`, managed identity, VS Code sign-in). A *partially* configured service principal is reported as a mistake rather than silently falling through to ambient auth.

`doctor` uses the same chain but never acquires a token, so it reports an ambient credential as `unverified` and points here. That is expected, not a failure.

### `fab-test auth login`

Mints nothing. It runs the underlying tool's login, printing the exact command first so you can reproduce it without `fab-test`:

```bash
fab-test auth login                # delegates to `pql-test auth login`
fab-test auth login --cloud USGov  # sovereign cloud
```

With no delegable tool on PATH it exits `127` naming `az login` and the service-principal variables.

> **`--env` is not `--cloud`.** In `fab-test`, `--env` is the *test environment label* (`DEV`, `PROD`, `ANY`) and exists on the analyzer subcommands. `--cloud` selects the *Azure cloud* and exists only on `auth login`. `pql-test` spells its cloud flag `--environment`; the names are deliberately kept apart here so the two never collide.

## Configuration

`fab-test.yml` at the repository root is an entirely optional config-file front door. No file at all means every setting resolves exactly as it did before this file existed.

```bash
fab-test --config custom.yml bpa   # --config must come before the subcommand: it's a top-level flag
fab-test init                      # scaffold a commented fab-test.yml and .env.example
fab-test init --dry-run            # see what init would create without writing anything
fab-test config --show             # every effective setting, its value, and where it came from
fab-test config --validate         # confirm the config file's keys and types are valid
```

### Precedence

| Priority | Source | Example |
|----------|--------|---------|
| 1 (highest) | CLI flag | `--jobs 4` |
| 2 | Environment variable | `ANALYZER_TIMEOUT=300` |
| 3 | `fab-test.yml` (or `[tool.fab-test]` in `pyproject.toml`) | `jobs: 4` |
| 4 (lowest) | Packaged default | `120` seconds |

If both `fab-test.yml` and `[tool.fab-test]` are present, `fab-test.yml` wins per key and the CLI warns once about the duplicate source. `fab-test config --show --format json` reports each setting's origin as one of `flag`, `env:NAME`, `fab-test.yml:key`, or `default`.

### Settings

| Key | Type | Env var | Default |
|-----|------|---------|---------|
| `artifact_dir` | string | — | `.fabric/artifacts` (repository root for `fab-test local`) |
| `output_dir` | string | — | `analyzer-results` |
| `jobs` | integer | — | `1` |
| `format` | string (`text`\|`json`) | — | `text` |
| `timeout` | integer | `ANALYZER_TIMEOUT` | `120` |
| `environment` | string | `FABRIC_ENVIRONMENT` | (none) |
| `rules` | object | — | (none) — see Rule Overlays below |

An unknown key exits `2` naming the key and the closest valid key (e.g. `artifac_dir` → "did you mean 'artifact_dir'?"); a key with the wrong type exits `2` naming the expected type.

### Rule Overlays

Tune one Best Practice Analyzer or PBIR Inspector rule without forking the packaged rules file:

```yaml
rules:
  bpa:
    disable: [AVOID_FLOATING_POINT_DATA_TYPES]   # remove a rule from the effective ruleset
    severity: {SOME_RULE_ID: warning}            # info | warning | error
    extend: path/to/extra-bpa-rules.json         # append rules from another file
  pbir:
    disable: [REMOVE_UNUSED_CUSTOM_VISUALS]
    severity: {SOME_RULE_ID: warning}            # warning | error (PBIR Inspector has no "info" level)
```

An overlay naming a rule ID that doesn't exist upstream exits `2` listing every unmatched ID. When any overlay is configured, the resolved ruleset is written to `<output_dir>/{bpa,pbir}/_resolved-rules.json` and passed to the tool; the envelope's `rules_file` field always names whichever rules file was actually used, so a finding is traceable back to the resolved ruleset it came from. Passing `--bpa-rules-path`/`--rules-path` explicitly bypasses the overlay entirely — that file is used verbatim.

The full schema ships with the package at `schemas/fab-test.schema.json` (draft 2020-12) for editor completion.

### What belongs in `fab-test.yml` vs. repository secrets

`fab-test.yml` is meant to be committed — it holds no credentials. Service-principal credentials (`FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`) belong in a `.env` file (auto-discovered at the repository root, gitignored) or, in a pipeline, in the CI system's own secrets store — never in `fab-test.yml`. With no service-principal variables set at all, Fabric REST calls fall back to `DefaultAzureCredential` (`az login`, a managed identity, VS Code sign-in, ...).

## Global Flags (all subcommands)

| Flag | Default | Description |
|------|---------|-------------|
| `TARGET` (positional) | (discover all) | What to test — see [Targeting](#targeting) for the grammar |
| `--artifact STEM` | (all) | Deprecated alias for `TARGET`; passing both exits `2` |
| `--artifact-dir DIR` | `.fabric/artifacts` (repository root for `local`) | Root directory to discover artifacts |
| `--output-dir DIR` | `analyzer-results` | Root directory for result envelopes |
| `--dry-run` | off | List matching artifacts without running any analyzer |
| `--telemetry` / `--no-telemetry` | env-driven | Stream/suppress Eventhouse telemetry when configured |
| `--format {text,json}` | `text` | Aggregate summary output format (see Agent Contract above for the stdout guarantee) |
| `-v`, `--verbose` | off | Increase output verbosity (one `-v` = per-finding detail, two `-v` = command + stdout/stderr) |
| `--timeout SECONDS` | `120` | Per-artifact subprocess timeout [env: `ANALYZER_TIMEOUT`] |
| `--jobs N` | `1` | Run up to N artifacts in parallel for the same analyzer |

### Isolating a single artifact

```bash
fab-test pql-test SampleModel-PQLAssert
fab-test bpa SampleModel-PQLAssert.SemanticModel   # name and type
fab-test all SampleModel-PQLAssert
```

The stem is the artifact folder name without its extension (`.SemanticModel`, `.Report`). Adding the type makes the selection explicit, which matters under `all`: `fab-test all Sales.SemanticModel` never picks up `Sales.Report`.

The older spelling still works: `fab-test bpa --artifact SampleModel-PQLAssert`.

## Subcommand-Specific Flags

### local

Runs `pql-lint`, BPA, PBIR Inspector, and Desktop-bound `pql-test` against every `.pbip` project discovered under `--artifact-dir` — no `.fabric/artifacts` layout required, no Fabric workspace, no service principal. Its subparser doesn't expose `--workspace-id` or `--env` at all, so the remote XMLA path is unreachable from `local`.

| Flag | Default | Description |
|------|---------|-------------|
| `--artifact-dir DIR` | repository root | Root to discover `.pbip` projects — broader default than other subcommands, since local mode's point is "wherever the `.pbip` lives" |
| `--tabular-editor-path`, `--bpa-rules-path`, `--inspector-path`, `--rules-path` | same as `bpa`/`pbir` | Passed straight through to those two analyzers |

```bash
fab-test local --dry-run    # see which projects were found and which analyzers would run
fab-test local              # run it
fab-test local --format json
```

A missing prerequisite (`pqlint` not installed, Tabular Editor/PBIR Inspector not resolved) is reported as **skipped** with a remediation hint — it never fails the run. Exit code `1` only means a real finding, never a missing tool. `pql-test` is always ready (it's a pinned `fab-test` dependency); if a Desktop instance has the project's `.pbip` open, `pql-test`'s envelope records a `desktop` field naming the port and model it bound to (see `pql-test` below and the run manifest section for the full shape).

Discovery walks `--artifact-dir` recursively and skips anything inside a separate git checkout (a worktree, a vendored clone) so a broad repo-root walk never double-counts the same fixture living in two checkouts.

### bpa

| Flag | Env var | Default |
|------|---------|---------|
| `--tabular-editor-path PATH` | `TABULAR_EDITOR_PATH` | `TabularEditor/TabularEditor.exe` |
| `--bpa-rules-path PATH` | — | `.github/metadata/rules/BPARules.json` |

```bash
fab-test bpa --tabular-editor-path "C:\Program Files (x86)\Tabular Editor\TabularEditor.exe"
# or set env var:
$env:TABULAR_EDITOR_PATH = "C:\..."
fab-test bpa
```

### pbir

| Flag | Env var | Default |
|------|---------|---------|
| `--inspector-path PATH` | `PBIR_INSPECTOR_PATH` | `PBIR-Inspector/PBIRInspectorCLI` |
| `--rules-path PATH` | — | `.github/metadata/rules/pbi-inspector-custom-rules.json` |

### pql-test

| Flag | Env var | Description |
|------|---------|-------------|
| `--env ENV` | `FABRIC_ENVIRONMENT` | Filter to a single environment label (e.g. `DEV`, `PROD`, `ANY`) |
| `--workspace-id ID` | `FABRIC_WORKSPACE_ID` | Fabric workspace GUID for remote XMLA |

```bash
fab-test pql-test --env DEV
fab-test pql-test --env PROD --workspace-id <guid>
```

`pql-test` is resolved in order: `PATH` → `.venv/Scripts/pql-test.exe` (Windows) / `.venv/bin/pql-test` (Unix) → `python -m pql_test`.

For local runs, `pql-test` connects to a locally-open Power BI Desktop instance automatically when given the artifact's filesystem path — no `--workspace-id` needed. When exactly one Desktop instance has the artifact's `.pbip` open, `fab-test` resolves its local XMLA port and adds it to the envelope as a `desktop` field:

```json
"desktop": {"port": 51234, "model_name": "SampleModel-PQLAssert"}
```

`desktop` is absent from the envelope when nothing is bound (no Desktop instance running, or more than one running — `fab-test` never guesses which one). Passing `--workspace-id` skips this Desktop-matching step entirely and uses the remote XMLA path instead.

### pql-lint

No additional flags beyond the global ones.

### playwright

Playwright validation can run in three modes: static `.env` mode, service-resolved mode, or impact-manifest mode.

| Flag | Description |
|------|-------------|
| `--env-file PATH` | Path to `.env` file with service-principal credentials and optional behavior settings |
| `--artifact NAME` | Resolve the deployed report from this artifact name and the target environment |
| `--env ENV` | Target environment label (e.g. `dev`, `test`, `prod`) [env: `FABRIC_ENVIRONMENT`] |
| `--workspace-id ID` | Explicit workspace ID override [env: `FABRIC_WORKSPACE_ID`] |
| `--dataset-id ID` | Explicit dataset / semantic-model ID override |
| `--impact-manifest PATH` | Validate every report listed in the impacted-report manifest once, regardless of local `.Report` artifacts |

Static `.env` mode uses workspace, report, dataset IDs directly from the env file:

```bash
fab-test playwright --env-file .env
fab-test playwright --env-file .env --dry-run
```

Service-resolved mode resolves the deployed report from the artifact name and environment metadata in `.github/metadata/environments.yml`, so the env file is only needed for credentials:

```bash
fab-test playwright --artifact "Not Working Visuals" --env dev --env-file .env
fab-test playwright --artifact SalesReport --env test --env-file .env
```

Impact-manifest mode validates every report impacted by changed artifacts. It is repository-scoped and runs once:

```bash
fab-test playwright-impact --changed-artifacts changed-artifacts.json --env dev --env-file .env
fab-test playwright --impact-manifest analyzer-results/playwright/impact-manifest.json --env dev --env-file .env
```

Browser setup:

```bash
playwright install chromium
pip install pytest-html
```

### playwright-impact

Build a service-resolved impacted-report manifest from a `changed-artifacts.json` payload. The manifest is consumed by `fab-test playwright --impact-manifest ...`.

| Flag | Description |
|------|-------------|
| `--changed-artifacts PATH` | Path to `changed-artifacts.json` (default: `changed-artifacts.json`) |
| `--output PATH` | Path to write the JSON impact manifest |
| `--env-file PATH` | Path to `.env` file with service-principal credentials |
| `--env ENV` | Target environment label [env: `FABRIC_ENVIRONMENT`] |
| `--workspace-id ID` | Explicit workspace ID override [env: `FABRIC_WORKSPACE_ID`] |

```bash
fab-test playwright-impact --changed-artifacts changed-artifacts.json --env dev --env-file .env
```

### dependencies

Discover reports that depend on a deployed semantic model. The command queries the Power BI / Fabric REST APIs directly with service-principal authentication.

| Flag | Description |
|------|-------------|
| `--semantic-model NAME` | Name of the deployed semantic model (required) |
| `--env-file PATH` | Path to `.env` file with service-principal credentials |
| `--output PATH` | Path to write the JSON dependency manifest |
| `--env ENV` | Target environment label [env: `FABRIC_ENVIRONMENT`] |
| `--workspace-id ID` | Explicit workspace ID override [env: `FABRIC_WORKSPACE_ID`] |

```bash
fab-test dependencies --semantic-model SalesModel --env dev --env-file .env
fab-test dependencies --semantic-model "Working Visuals" --env dev --env-file .env --output deps.json
```

### all

Runs the analyzer names listed in `.github/metadata/analyzers.json` under the `fab_test_all` key. This keeps the local command aligned with the same metadata that drives CI.

Current default list:

```json
{
  "fab_test_all": ["bpa", "pbir", "pql_test"]
}
```

`pql-lint` and `playwright` are excluded from `fab-test all` by default but remain available as direct subcommands.

Accepts the union of flags from `bpa`, `pbir`, `pql-test`, and `pql-lint`, plus `--playwright-env-file` for Playwright support.

```bash
fab-test all \
  --tabular-editor-path "C:\..." \
  --env DEV \
  --playwright-env-file .env
```

After all analyzers finish, `fab-test all` prints an aggregate summary table showing analyzer, artifact, status, errors, warnings, and output path, plus total errors and warnings across the run.

## Dry Run (discover artifacts without running)

```bash
fab-test bpa --dry-run
fab-test pql-test --dry-run
fab-test all --dry-run --artifact SampleModel-PQLAssert
```

## Output Verbosity

`fab-test` honors `-v` / `--verbose` (mirrors `ANALYZER_VERBOSITY`):

```bash
fab-test bpa -v              # per-finding detail
fab-test pbir -vv            # resolved command + stdout/stderr
fab-test all --verbose       # same as -v
```

Result files under `analyzer-results/` are identical regardless of verbosity.

## Result Locations

All results follow the same layout regardless of analyzer:

```
analyzer-results/
  bpa/
    <artifact-stem>/
      envelope.json   ← standardized result (status, findings, duration_ms)
      native.json     ← raw Tabular Editor output
  pbir/
    <artifact-stem>/
      envelope.json
      native.json
  pql_test/
    <artifact-stem>/
      envelope.json
      native.json     ← full pql-test JSON (model_path, passed, failed, results[])
  pql_lint/
    <artifact-stem>/
      envelope.json
  playwright/
    <artifact-stem-or-report-name>/
      envelope.json
      test-cases/
        <report-name>/
          screenshot.png
          console.json
          network.json
      report/
        index.html
        results.xml
```

`envelope.json` schema keys: `schema_version`, `analyzer`, `artifact_path`, `status`, `message`, `findings`, `native_output_path`, `duration_ms`.

For `pql_test`, the envelope also contains `test_results` (full result array from pql-test).

`status` values: `passed` | `failed` | `error` | `timeout`.

## Tool Resolution and Local Caching

External binaries are resolved in this order:

1. CLI flag (`--tabular-editor-path`, `--inspector-path`)
2. Environment variable (`TABULAR_EDITOR_PATH`, `PBIR_INSPECTOR_PATH`)
3. Default relative path (`./TabularEditor/TabularEditor.exe`, `./PBIR-Inspector/PBIRInspectorCLI`)
4. Cached executable in `.fab-test-tools/<analyzer>/`
5. Install URL from environment variable (`TABULAR_EDITOR_INSTALL_URL`, `PBIR_INSPECTOR_INSTALL_URL`)
6. Committed install URL from `analyzers.json` (`tool_install.install_url`)

The committed `install_url` is useful for local development because it lets a team share a local tool URL (for example, `file:///shared/tools/TabularEditor.zip`) without requiring every developer to set environment variables. CI can still override it with the env var.

Downloaded tools are extracted into `.fab-test-tools/<analyzer>/`, recorded in a marker file, and reused on subsequent runs. This directory is ignored by git so executables are never committed.

## Pre-flight Checks

`fab-test` performs tool existence checks before running subprocesses:

- **bpa**: errors with download hint if `TabularEditor.exe` is missing
- **pbir**: errors with path hint if `PBIRInspectorCLI` is missing
- **pql_test**: silently falls back to `python -m pql_test` if `pql-test` is not on PATH; then checks `.venv`

## Source Files

| File | Purpose |
|------|---------|
| `scripts/fab_test.py` | CLI entry point — argument parser, artifact discovery, subprocess dispatch |
| `scripts/fab_test_registry.py` | Analyzer registry, artifact discovery, and command builders |
| `scripts/invoke_tabular_editor_bpa.py` | BPA subprocess wrapper |
| `scripts/invoke_pbir_inspector.py` | PBIR Inspector subprocess wrapper |
| `scripts/invoke_pql_test.py` | pql-test subprocess wrapper (venv-aware lookup, native JSON parsing) |
| `scripts/invoke_pqlint.py` | pqlint subprocess wrapper |
| `scripts/invoke_playwright.py` | Playwright validation wrapper |
| `scripts/invoke_playwright_impact.py` | Playwright impact manifest builder |
| `scripts/invoke_playwright_dependencies.py` | Semantic-model dependency discovery wrapper |
| `scripts/playwright_validation/config.py` | `.env` / environment configuration loader |
| `scripts/playwright_validation/test_cases.py` | Report × page × bookmark case expansion |
| `scripts/playwright_validation/embed_config.py` | Power BI JavaScript embed config builder |
| `scripts/playwright_validation/power_bi_api.py` | Power BI REST API token helpers |
| `scripts/playwright_validation/fabric_service_client.py` | Azure Identity service client for Fabric/Power BI REST APIs |
| `scripts/playwright_validation/resolver.py` | Environment/workspace/report resolution |
| `tests/test_playwright_visual.py` | pytest-playwright spec that embeds reports |
| `scripts/_analyzer_envelope.py` | Shared envelope schema builder |
