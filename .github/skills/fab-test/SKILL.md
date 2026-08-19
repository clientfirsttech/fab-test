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
fab-test list                         # what subcommands exist, and how many artifacts match?
fab-test explain bpa                  # what command would `fab-test bpa` actually run?
```

`doctor` and `list` both support `--format json`. `doctor --analyzer NAME` checks one analyzer; `list`'s matched-artifact counts respect `--artifact-dir`. `explain ANALYZER` never spawns a subprocess — it only shows the resolved command, tool path, rules path, and output path.

### The run manifest (`analyzer-results/run.json`)

Every analyzer invocation (a single subcommand or `all`) writes one `run.json` under `--output-dir` (default `analyzer-results/`), so a caller reads one file instead of globbing result directories:

```json
{
  "schema_version": 1,
  "fab_test_version": "1.0.0",
  "command": ["fab-test", "bpa", "--format", "json"],
  "artifacts": [
    {
      "analyzer": "bpa",
      "artifact": "SampleModel-PQLAssert",
      "status": "passed",
      "envelope_path": "analyzer-results/bpa/SampleModel-PQLAssert/envelope.json",
      "errors": 0,
      "warnings": 21
    }
  ],
  "totals": {"errors": 0, "warnings": 21},
  "exit_code": 0
}
```

Per-artifact `status` is one of `passed` / `failed` / `skipped` / `timeout` / `preflight_failed` (the last two cover an aborted run). The `command` field is sanitized: known credential flags (`--client-secret`, `--password`, `--token`, `--secret`, `--api-key`) and any `key=value`-shaped token have their value redacted before the file is written — no credential ever appears in the manifest.

`doctor`, `list`, `explain`, and `clean-tools` never write a manifest — they don't run an analyzer.

## Subcommands

```
 fab-test bpa              — Tabular Editor Best Practice Analyzer (SemanticModel artifacts)
 fab-test pbir             — PBIR Inspector static report analysis (Report artifacts)
 fab-test pql-test         — pql-test DAX/PQL test runner (SemanticModel artifacts) [alias: pql_test]
 fab-test pql-lint         — pqlint Power Query linter (SemanticModel artifacts) [alias: pql_lint]
 fab-test playwright       — Playwright visual/error validation (Report artifacts)
 fab-test playwright-impact — Build impacted-report manifest from changed artifacts [alias: playwright_impact]
 fab-test dependencies     — Discover reports that depend on a deployed semantic model
 fab-test all              — Run the analyzers listed in analyzers.json
 fab-test doctor           — Check whether each analyzer's tool/credentials are ready
 fab-test list             — List subcommands with artifact glob, matched count, and required tool
 fab-test explain ANALYZER — Show the resolved command for one analyzer without running it
 fab-test clean-tools      — Remove or inspect the .fab-test-tools downloaded-binary cache
```

Underscore spellings (`pql_test`, `pql_lint`, `playwright_impact`) still work silently as aliases —
existing scripts and muscle memory keep working. Result directories under `analyzer-results/`
use the original underscore names regardless of which spelling you invoke.

## Global Flags (all subcommands)

| Flag | Default | Description |
|------|---------|-------------|
| `--artifact STEM` | (all) | Only analyze the artifact whose stem matches STEM exactly |
| `--artifact-dir DIR` | `.fabric/artifacts` | Root directory to discover artifacts |
| `--output-dir DIR` | `analyzer-results` | Root directory for result envelopes |
| `--dry-run` | off | List matching artifacts without running any analyzer |
| `--telemetry` / `--no-telemetry` | env-driven | Stream/suppress Eventhouse telemetry when configured |
| `--format {text,json}` | `text` | Aggregate summary output format (see Agent Contract above for the stdout guarantee) |
| `-v`, `--verbose` | off | Increase output verbosity (one `-v` = per-finding detail, two `-v` = command + stdout/stderr) |
| `--timeout SECONDS` | `120` | Per-artifact subprocess timeout [env: `ANALYZER_TIMEOUT`] |
| `--jobs N` | `1` | Run up to N artifacts in parallel for the same analyzer |

### Isolating a single artifact

```bash
fab-test pql-test --artifact SampleModel-PQLAssert
fab-test bpa --artifact SampleModel-PQLAssert
fab-test all --artifact SampleModel-PQLAssert
```

The stem is the artifact folder name without its extension (`.SemanticModel`, `.Report`).

## Subcommand-Specific Flags

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

For local runs, Power BI Desktop must be open with the model loaded. `pql-test` connects via XMLA on `localhost`.

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
