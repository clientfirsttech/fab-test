# Operations

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

Result files under `fab-test-results/` are identical regardless of verbosity.

## Result Locations

All results follow the same layout regardless of analyzer:

```
fab-test-results/
  run.json            ← one manifest per invocation
  index.html          ← per-run index, with --report whenever more than one artifact ran
  bpa/
    <artifact-stem>/
      envelope.json   ← standardized result (status, findings, duration_ms)
      native.json     ← raw Tabular Editor output (TRX)
      report.html     ← generated, only with --report
  pbir/
    <artifact-stem>/
      envelope.json
      native.json/
        TestRun.html  ← PBIR Inspector's own report, always written
  pql_test/
    <artifact-stem>/
      envelope.json
      native.json     ← full pql-test JSON (model_path, passed, failed, results[])
      report.html     ← generated, only with --report
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

`envelope.json` required keys: `schema_version`, `analyzer`, `artifact_path`, `status`, `message`, `findings`, `native_output_path`, `duration_ms`.

Optional keys — **absent, never null**, so a consumer tests presence:

| Key | Meaning |
|-----|---------|
| `native_html_output_path` | A readable HTML report for this artifact: PBIR Inspector's own `TestRun.html`, or the one `fab-test` generated under `--report`. |
| `started_at` | UTC ISO-8601 wall-clock time the run started. `duration_ms` says how long; this says when. |


For `pql_test`, the envelope also contains `test_results` (full result array from pql-test, native shape). For `bpa`, it contains one entry per rule TE2 evaluated (`RuleName`/`RuleID`/`Severity`/`Category`/`ObjectName` plus a computed `status` of `pass`/`error`/`warning`), passed and failed alike — unlike `findings`, which stays failure-only. `pbir` matches the same idea in the shared `rule`/`severity`/`object`/`message` shape (each with a `status`), so telemetry can see every rule PBIR Inspector evaluated, not only the ones that failed — `pbir`'s own `TestRun.html` still has its own filter UI, so this field feeds telemetry, not the shared report's full-list filter, for that analyzer specifically. `playwright` uses the pql-test-shaped `test_results` too (one row per generated report x page x bookmark case), plus an `evidence` map per row (`screenshot`/`console`/`network` paths, whichever exist) that the shared renderer turns into links when `--report` is on (see the `playwright` section in [Flags](flags.md)). All four are `[]` when the analyzer produced no per-test breakdown.

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
