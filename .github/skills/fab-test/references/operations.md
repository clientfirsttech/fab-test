# Operations

## Dry Run (discover artifacts without running)

```bash
fab-test bpa --dry-run
fab-test pql-test --dry-run
fab-test all --dry-run --artifact SampleModel-PQLAssert
```

## Output Verbosity

`fab-test` has one verbosity ladder. Three flags, an environment variable, and a config key all name a rung of it:

| Level | Flag | `ANALYZER_VERBOSITY` / `verbosity:` | What it prints |
|-------|------|-------------------------------------|----------------|
| `summary` | `-q`, `--quiet` | `summary` | One line per artifact — see below |
| `default` | (none) | `default` | Banner, result line, and summary per artifact. The Rules and Tool paths, which are the same for every artifact and already in the envelope, are left out |
| `verbose` | `-v`, `--verbose` | `verbose` | Default plus the Rules and Tool paths and per-finding detail |
| `debug` | `-vv` | `debug` | Verbose plus the resolved command and the analyzer's stdout/stderr |

```bash
fab-test bpa -q              # one line per artifact
fab-test rdl -q              # the same line for a paginated report: `rdl failed e=3 w=3 <envelope>`
fab-test bpa -v              # per-finding detail
fab-test pbir -vv            # resolved command + stdout/stderr
fab-test rdl -v              # findings table (wrapped, never cut); -vv adds the active/planned rule counts (rdl runs no subprocess, so there is no command or stdout to show)
fab-test all --verbose       # same as -v
```

Precedence is the same as every other setting: flag > `ANALYZER_VERBOSITY` > `verbosity:` in `fab-test.yml` > default. `-q` and `-v` together exit `2`. `ANALYZER_VERBOSITY` is case-insensitive; the `verbosity:` config value must be lowercase, like `format`, and an unknown value exits `2` naming the four levels.

Result files under `fab-test-results/` are identical regardless of verbosity.

### The `-q` line

```
<analyzer> <status> e=<errors> w=<warnings> <where>
```

```
bpa warning e=0 w=103 fab-test-results/bpa/SampleModel-PQLAssert/envelope.json
pbir failed e=29 w=1 fab-test-results/pbir/SampleModel-PQLAssert/envelope.json
playwright failed e=0 w=0 ThinReport
```

`<analyzer>` is the registry name (`pql_test`, not `pql-test`). `<status>` is `passed`, `warning`, `failed`, or `skipped`. `<where>` is the envelope path relative to the working directory, or the artifact name when the analyzer wrote no envelope — it is last because artifact names contain spaces. Exit codes are unchanged, and a failure the findings cannot explain still prints its remediation above the lines: a missing credential, a timeout, or a crash with no findings. In CI the analyzer's `::error::`/`::warning::` annotations still pass through. When every artifact fails the same check, its message is printed once.

Under `fab-test all`, each analyzer prints its own lines as it finishes and the aggregate table is left out.

To pin it for a repository:

```yaml
# fab-test.yml
verbosity: summary
```

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
  rdl/
    <artifact-stem>/
      envelope.json
      native.json     ← the raw findings list, before test_results is built
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
| `timings` | `playwright` only: where the report's time went. `discovery_ms` (resolving pages, roles, parameters, and generating cases), `token_ms` (minting embed tokens), `render_ms` (the pytest session), `total_ms`, `browser_setup_ms` (fixture setup summed across cases: the browser launch or Azure connection on each worker's first case, plus context and page creation), `backend`, and the `workers` the report actually used. `duration_ms` stays the render phase alone. |


For `pql_test`, the envelope also contains `test_results` (full result array from pql-test, native shape). For `bpa`, it contains one entry per rule TE2 evaluated (`RuleName`/`RuleID`/`Severity`/`Category`/`ObjectName` plus a computed `status` of `pass`/`error`/`warning`), passed and failed alike — unlike `findings`, which stays failure-only. `pbir` matches the same idea in the shared `rule`/`severity`/`object`/`message` shape (each with a `status`), so telemetry can see every rule PBIR Inspector evaluated, not only the ones that failed — `pbir`'s own `TestRun.html` still has its own filter UI, so this field feeds telemetry, not the shared report's full-list filter, for that analyzer specifically. `rdl` matches `pbir`'s shape: one row per active rule that passed or is disabled, and one row per hit for a rule that fired (so a rule firing on four datasets has four rows), `status` one of `pass`/`skip`/`warning`/`error` — `skip` means disabled in the overlay. Planned rules (`status: planned` in the catalog) have no row at all; they do not run and never show in a user's results. `playwright` uses the pql-test-shaped `test_results` too (one row per generated report x page x bookmark case), plus an `evidence` map per row (`screenshot`/`console`/`network` paths, whichever exist) that the shared renderer turns into links when `--report` is on (see the `playwright` section in [Flags](flags.md)). All five are `[]` when the analyzer produced no per-test breakdown.

`status` values: `passed` | `failed` | `warning` | `skipped` | `error` | `timeout` | `dry-run`.

`warning` and `skipped` both mean "no finding to report", and both exit 0 — they
differ in whether the analyzer ran:

| Status | Meaning | Exit code | CI annotation |
|--------|---------|-----------|---------------|
| `passed` | Ran, nothing failed | 0 | — |
| `warning` | Ran nothing, or findings below the fail threshold | 0 | `::warning::` |
| `skipped` | A prerequisite was absent, so the analyzer never ran | 0 | — |
| `failed` | Real findings at or above the fail threshold | 1 | `::error::` |
| `error` | The wrapped tool itself failed | 1 | `::error::` |
| `timeout` | The tool exceeded `ANALYZER_TIMEOUT` | 1 | `::error::` |
| `dry-run` | `--dry-run`: the plan only, nothing executed | 0 | — |

A run that executed no tests is `warning`, never `passed`: zero tests passing is
not a pass, and a green check is how a caller comes to believe tests ran when
none did.

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
