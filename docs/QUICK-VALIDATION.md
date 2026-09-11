# Quick validation guide

Validate the `fab-test` package and its analyzers on your local machine before pushing changes to CI.

## Prerequisites

- Python 3.12 or later
- A clone of this repository
- (Optional) External analyzer tools such as Tabular Editor or PBIR Inspector if you plan to run `fab-test` against real artifacts. PBIR Inspector additionally needs the .NET 8 runtime installed (it is a framework-dependent build) — `fab-test doctor --analyzer pbir` reports whether it's present
- Artifacts saved as PBIP projects — semantic models in TMDL, reports in PBIR (see [Assumed project format](../README.md#assumed-project-format)). The wrapper contract tests below need none of this; only the `fab-test` runs against real artifacts do.

## Virtual environments used by this project

This repository uses several local virtual environments. They are all ignored by `.gitignore` and can be recreated at any time.

| Environment | Purpose |
|-------------|---------|
| `.venv`     | General development environment with the package installed in editable mode (`pip install -e .`). |
| `.venv-test`| Fresh, throwaway environment used to install and validate the locally built wheel exactly as a consumer would. |
| `.venv-pkg` | Development/test environment with dev dependencies such as `pytest`, `coverage`, and `playwright`. |

All of these are optional. The only one the walkthrough below depends on is `.venv-test`.

## Build the wheel locally

The project is packaged with `setuptools` and `pyproject.toml`. Build a wheel into `dist/`:

```bash
pip install build
python -m build
```

After the build completes, `dist/` contains both a wheel and a source distribution:

```text
dist/
  fab_test-1.0.0-py3-none-any.whl
  fab_test-1.0.0.tar.gz
```

## Install the wheel in a virtual environment

Create a fresh virtual environment to test the packaged distribution exactly as a consumer would install it:

```bash
python -m venv .venv-test
source .venv-test/bin/activate  # Windows: .venv-test\Scripts\activate
pip install dist/fab_test-*.whl
```

Verify the console scripts are registered:

```bash
fab-test --help
```

## Run wrapper contract tests with pytest

`pytest` validates the analyzer wrappers using mocks and fixtures, so it does not require external tools. Make sure the virtual environment is activated so the installed console scripts are on `PATH`, then install `pytest` and run the test suite from the repository root:

```bash
# Windows
.venv-test\Scripts\activate
# macOS/Linux
# source .venv-test/bin/activate

pip install pytest
pytest
```

Run a subset of tests by marker:

```bash
pytest -m fab_test      # fab-test CLI surface
pytest -m analyzers     # all contract-tier analyzer tests
pytest -m bpa           # BPA wrapper only
pytest -m pbir          # PBIR Inspector wrapper only
pytest -m a11y          # pbir-a11y wrapper only
pytest -m pql_test      # pql-test wrapper only
```

> **Note:** Some wrapper contract tests launch the installed console scripts (`tabular-editor-bpa`, `fab-test`, etc.) as subprocesses. Those scripts must be on `PATH`, so always activate the virtual environment before running `pytest`.

## Run artifact analyzers with fab-test

`fab-test` exercises the actual analyzers against the artifacts it finds under your working directory. Each analyzer has its own tool requirements.

Discovery walks down from where you run the command and treats a folder as an
artifact when its name ends in a Fabric type suffix — at any depth, with or
without a `.pbip` beside it. Nested git checkouts, `.venv`, `node_modules`,
`__pycache__`, `dist`, `build`, and the run's own `--output-dir` are skipped.
An existing `.fabric/artifacts/` layout is found exactly as before, since it
sits inside the working directory.

If you run it one directory too high — in the folder that *holds* your
repositories — everything below is a nested checkout, so nothing is found.
The warning says how many checkouts it skipped and gives you the
`--artifact-dir` to paste; `--format json` carries the same as
`skipped_checkouts`.

### Discover artifacts without running anything

```bash
fab-test bpa --dry-run
fab-test pbir --dry-run
fab-test a11y --dry-run
fab-test pql-test --dry-run
```

### Run a single analyzer

```bash
fab-test bpa --tabular-editor-path "/path/to/TabularEditor.exe"
fab-test pbir --inspector-path "/path/to/PBIRInspectorCLI"
fab-test a11y                            # requires Node.js >= 18 + npm the first time (built from source, then cached)
fab-test pql-test --env DEV
```

### Isolate one artifact

```bash
fab-test bpa SampleModel-PQLAssert
fab-test pql-test SampleModel-PQLAssert --env DEV
```

`--artifact SampleModel-PQLAssert` still works as a deprecated alias.

### Open the HTML report automatically

```bash
fab-test bpa --open-report
```

`--open-report` implies `--report` and opens the produced report (or, whenever more than one artifact ran — `fab-test all`, or one analyzer against several artifacts — the run's `index.html`) in your default browser once the run finishes — skip the "find it in Explorer, double-click" step. This is a local convenience only: it is automatically suppressed under CI (falls back to printing the path), so there is no reason to add it to a pipeline YAML.

### Naming what to test

Every analyzer subcommand takes an optional target. Omit it and `fab-test` discovers everything matching. The grammar matches `pql-test` and the Fabric CLI, so a target pasted from either works unchanged.

| Target | Means |
|--------|-------|
| *(omitted)* | Discover every matching artifact under `--artifact-dir` (default: the working directory) |
| `Sales` | The artifact named `Sales`; the analyzer's own glob picks the type |
| `Sales.SemanticModel` | That name **and** type — `Sales.Report` is not selected |
| `./src/Sales.SemanticModel` | Exactly that folder, wherever it lives (not confined to `--artifact-dir`) |
| `local/Sales` | The copy open in a running Power BI Desktop instance |
| `"Sales Dev.Workspace/Sales.SemanticModel"` | A deployed item in the named Fabric workspace |

Not every analyzer accepts every form. `fab-test list` has a Scopes column; `bpa` and `pbir` refuse a workspace target because reading a deployed item would mean exporting it first. `fab-test all` skips an analyzer that cannot honor the target rather than failing the batch.

### Check which identity you are using

```bash
fab-test auth status                      # verified for real, unlike doctor
fab-test auth status --workspace-id <id>  # also confirm that workspace is reachable
fab-test auth login                       # delegates to `pql-test auth login`
```

`fab-test` stores no credentials of its own. `auth status` exits `0` verified, `127` when nothing resolves, `1` when credentials work but the workspace is unreachable. `doctor` never acquires a token, so it reports an ambient `az login` credential as `unverified` and points here.

### Run the default analyzer set

```bash
fab-test all
```

The default set is configured in `analyzers.json` (resolved via the metadata layers: `.fab-test/metadata/` > `.github/metadata/` > packaged).

### Check readiness before running (doctor)

Before running any analyzer, ask whether its tool or credentials are actually in place:

```bash
fab-test doctor
fab-test doctor --analyzer bpa --format json
```

## Coverage and complexity

Both are enforced, and both are ratchets — they move down, never up.

```bash
pytest -q --cov                      # measure locally, no gate
pytest -q --cov --cov-fail-under=80  # exactly what CI runs
```

The 80% floor is scoped to `src/fab_test` with tests excluded. One module is omitted by explicit path — `validate_fabric_service_client.py` — because it needs a live service to execute, so a unit test could only assert that its argument parser accepts flags. `eventhouse_logger.py` came off that list once its ingest was separable from the validators in front of it. `tests/test_coverage_config.py` fails if one of those entries goes stale or if a core CLI module is ever added to the list.

**Never put a coverage flag in `pytest.ini`.** A granular `pytest -m bpa` run covers a fraction of `src/` by design; gating it would fail every marker run and defeat the point of having them.

Complexity is reported but not gated per-function — blocking a PR because a function grew one branch is a gate people route around. The *total* is ratcheted in `tests/test_complexity_budget.py`, which also names the functions a past epic refactored so one cannot quietly grow back while another improves.

## Configuring fab-test

`fab-test.yml` at the repository root is an entirely optional config-file front door — no file at all means every setting behaves exactly as it always has.

```bash
fab-test init                # scaffold a commented fab-test.yml and .env.example
fab-test config --show       # every effective setting, its value, and where it came from
fab-test config --validate   # confirm the config file's keys and types are valid
```

Precedence, for every setting:

| Priority | Source | Example |
|----------|--------|---------|
| 1 (highest) | CLI flag | `--jobs 4` |
| 2 | Environment variable | `ANALYZER_TIMEOUT=300` |
| 3 | `fab-test.yml` (or `[tool.fab-test]` in `pyproject.toml`) | `jobs: 4` |
| 4 (lowest) | Packaged default | `120` seconds |

`fab-test.yml` is safe to commit — it never holds credentials, only settings and rule overlays. Credentials belong in a `.env` file (auto-discovered at the repository root, gitignored) or, in a pipeline, the CI system's own secrets store:

```yaml
# committed alongside the workflow file:
#   fab-test.yml           <- settings and rule overlays, no secrets
# repository/organization secrets, injected at run time:
#   FABRIC_TENANT_ID, FABRIC_CLIENT_ID, FABRIC_CLIENT_SECRET

- name: Run bpa with a committed rule overlay
  run: fab-test bpa --format json   # fab-test.yml's rules.bpa overlay applies automatically

- name: Run pql-test against the deployed workspace
  env:
    FABRIC_TENANT_ID: ${{ secrets.FABRIC_TENANT_ID }}
    FABRIC_CLIENT_ID: ${{ secrets.FABRIC_CLIENT_ID }}
    FABRIC_CLIENT_SECRET: ${{ secrets.FABRIC_CLIENT_SECRET }}
  run: fab-test pql-test --env PROD --workspace-id ${{ vars.FABRIC_WORKSPACE_ID }} --format json
```

### Overriding metadata in a pipeline

No path flags are needed: commit the files under `.fab-test/metadata/` and every analyzer
picks them up. Only `environments.yml` has no packaged default, so a workflow that deploys or
resolves a deployed item by name has to supply it -- unless a workspace is already resolved
from `--workspace-id`, `FABRIC_WORKSPACE_ID`, or `workspace:` in `fab-test.yml`, in which case
`environments.yml` is never opened at all. The service-principal path below is still the CI
recommendation regardless: it is what actually generates Playwright's embed token, which an
ambient sign-in cannot do.

```yaml
# committed alongside the workflow file, no secrets:
#   .fab-test/metadata/rules/BPARules.json    <- overrides the packaged ruleset
#   .fab-test/metadata/environments.yml       <- required; there is no packaged default

- name: Confirm which ruleset is actually in force
  run: fab-test config --show --format json    # reports each ruleset's origin layer

- name: Fail early if environments.yml is missing or malformed
  run: validate-environments-yaml              # exits 1 naming both candidate paths

- name: Run Playwright against a named report
  env:
    FABRIC_TENANT_ID: ${{ secrets.FABRIC_TENANT_ID }}
    FABRIC_CLIENT_ID: ${{ secrets.FABRIC_CLIENT_ID }}
    FABRIC_CLIENT_SECRET: ${{ secrets.FABRIC_CLIENT_SECRET }}
  run: fab-test playwright --artifact ThinReport --env PROD --format json
```

By default this discovers every page, each page's own bookmarks, and (when RLS
is enabled) every semantic-model role, and tests the full matrix. Beyond the
`Report.Read` / `Dataset.ReadWrite.All`-equivalent grant embedding already
needed, the service principal also needs **`Report.Read.All`** (pages,
bookmarks) and **`SemanticModel.Read.All`** (roles) to discover the matrix — a
missing grant logs a warning and falls back to testing the single default
page/role rather than failing the run. Add `--pages none --roles none` to the
command above to keep the one-case-per-report shape every prior release had.

See the [Configuration section of the fab-test skill](../.github/skills/fab-test/references/configuration.md#configuration) for the full settings list and rule-overlay keys.

### Pipeline snippet: a reviewable report as the build artifact

`run.json` is what a pipeline *parses*; `index.html` is what a person *opens* when the build goes red. Reports are opt-in, so a job that wants one asks for it:

```yaml
- name: Run analyzers with reports
  run: fab-test all --report --format json
  continue-on-error: true      # upload the report even when findings fail the build

- name: Upload the reviewable report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: fab-test-report
    path: |
      fab-test-results/index.html
      fab-test-results/**/report.html
      fab-test-results/**/TestRun.html
      fab-test-results/playwright/test-cases/**
      fab-test-results/run.json
```

`if: always()` matters: the run you most want to read is the one that failed. Colour is automatically off because stdout is not a terminal — set `FORCE_COLOR: "1"` if your CI log viewer renders ANSI and you want it back.

The `test-cases/**` line matters specifically for `playwright`: its `report.html` links to each case's own `screenshot.png`/`console.json`/`network.json` under that directory (plus `event_log.json` and, on a render timeout with a visible error panel, `embed_error_details.txt`), and a link to a file the upload never included opens to nothing once downloaded.

### Pipeline snippet: targeting a deployed item by name

The workspace belongs in committed config; only the credentials come from secrets. With `workspace:` set in `fab-test.yml`, the workflow names the artifact and nothing else:

```yaml
# fab-test.yml — committed, no secrets:
#   workspace: Sales Prod
```

```yaml
- name: Confirm the pipeline identity before doing any work
  env:
    FABRIC_TENANT_ID: ${{ secrets.FABRIC_TENANT_ID }}
    FABRIC_CLIENT_ID: ${{ secrets.FABRIC_CLIENT_ID }}
    FABRIC_CLIENT_SECRET: ${{ secrets.FABRIC_CLIENT_SECRET }}
  run: fab-test auth status --format json

- name: Run DAX tests against the deployed model
  env:
    FABRIC_TENANT_ID: ${{ secrets.FABRIC_TENANT_ID }}
    FABRIC_CLIENT_ID: ${{ secrets.FABRIC_CLIENT_ID }}
    FABRIC_CLIENT_SECRET: ${{ secrets.FABRIC_CLIENT_SECRET }}
  run: fab-test pql-test "Sales Prod.Workspace/Sales.SemanticModel" --env PROD --format json
```

Spell the workspace out in the target when a job spans more than one, and quote it — display names usually contain spaces. A GUID works in the same position and skips the name lookup. `auth status` is worth running first: it exits `127` before any analyzer starts if the service principal is missing or half-configured, which is a clearer failure than an analyzer timing out against an unreachable workspace.

The resolved target lands in `run.json` under `target`, so an uploaded manifest records whether the job read files on disk or hit a workspace — and which one.

### Pipeline snippet: doctor as a gate, run.json as the artifact

A copy-pasteable step for a CI job — gate on readiness, run with `--format json`, upload the manifest instead of globbing result directories:

```yaml
- name: Check fab-test readiness
  run: fab-test doctor --format json

- name: Run bpa
  run: fab-test bpa --format json --artifact-dir .fabric/artifacts

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  with:
    name: fab-test-run-manifest
    path: fab-test-results/run.json
```

**Keep `--artifact-dir` explicit in CI.** Locally the default follows your
working directory, which is what you want at a prompt. A build should not:
pinning the root means the job scans the same tree whichever directory the
runner happens to start in, and a checkout that lands somewhere unexpected
fails loudly instead of quietly analyzing nothing.

`run.json` records `schema_version`, `fab_test_version`, `origin` (`"local"` locally, the detected CI system in a pipeline), `target` (the resolved target, or `null` for a discovery run), the invoked command (credentials redacted), per-artifact status, envelope paths, totals, and the final exit code — see the [Agent Contract](../.github/skills/fab-test/SKILL.md#agent-contract) for the full schema.

**A failed artifact says why, in the manifest.** When an analyzer aborts before it can write an envelope — a missing `--env`, a missing prerequisite, a timeout — that artifact's `detail` carries the remediation message, so the uploaded manifest is self-contained:

```json
{
  "analyzer": "playwright", "artifact": "ThinReport", "status": "failed",
  "envelope_path": null, "errors": 0, "warnings": 0,
  "detail": "No environment given, so there is nothing to resolve 'ThinReport' against. Pass --env, set FABRIC_ENVIRONMENT, or set `environment:` in fab-test.yml."
}
```

This is the case where uploading `run.json` alone still tells you what to fix. It stays `null` when the analyzer *did* write an envelope — then `envelope_path` points at the findings, and those are the reason. Credential values are redacted out of `detail` on the way in, as they are from `command`.

### Pipeline snippet: pbir-a11y accessibility checks (needs Node)

Every other analyzer's CI job is just `fab-test <name>`; `a11y` is the one
that needs a runtime installed first, since `fab-test` builds pbir-a11y
from source on first use rather than downloading a pre-built binary:

```yaml
- name: Set up Node.js
  uses: actions/setup-node@v4
  with:
    node-version: ">=18"

- name: Check readiness (confirms Node/npm before building anything)
  run: fab-test doctor --analyzer a11y --format json

- name: Run pbir-a11y accessibility checks
  run: fab-test a11y --format json --artifact-dir .fabric/artifacts

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: fab-test-a11y-manifest
    path: fab-test-results/run.json
```

The first run builds and caches pbir-a11y under `.fab-test-tools/`; cache
that directory (`actions/cache@v4`, keyed on the analyzers.json checksum)
if the job runs often enough for the ~10s build to matter. `a11y` is not in
`fab_test_all`, so this step is additive to an existing pipeline — nothing
already green starts failing because this snippet was added elsewhere in
the same workflow. See [THIRD-PARTY.md](../THIRD-PARTY.md) before using
this in a commercial pipeline: pbir-a11y is PolyForm Shield-licensed
(source-available, non-compete), not MIT like the other wrapped tools —
running it via `fab-test` to check your own reports is a permitted use.

### Pipeline snippet: shipping telemetry to an Eventhouse

Optional. Configuring a destination is what enables it — there is no separate flag —
so this snippet is the whole setup: install the extra, supply the credentials the
analyzers already use, and commit the address in `fab-test.yml`.

```yaml
- name: Install fab-test with the telemetry extra
  run: pip install 'fab-test[telemetry]'

- name: Run analyzers
  env:
    # The same service principal the analyzers use. There are no
    # EVENTHOUSE_* credential variables.
    FABRIC_TENANT_ID: ${{ secrets.FABRIC_TENANT_ID }}
    FABRIC_SERVICE_PRINCIPAL_ID: ${{ secrets.FABRIC_SERVICE_PRINCIPAL_ID }}
    FABRIC_SERVICE_PRINCIPAL_SECRET: ${{ secrets.FABRIC_SERVICE_PRINCIPAL_SECRET }}
    # Optional: override the committed fab-test.yml address per environment.
    EVENTHOUSE_URI: ${{ vars.EVENTHOUSE_URI }}
    EVENTHOUSE_DATABASE: ${{ vars.EVENTHOUSE_DATABASE }}
  run: fab-test all --format json --artifact-dir .fabric/artifacts

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: fab-test-run-manifest
    path: fab-test-results/run.json
```

```yaml
# fab-test.yml — committed; holds the address, never the credential
telemetry:
  eventhouse:
    uri: https://<cluster>.kusto.fabric.microsoft.com
    database: fabric_ops
```

**No setup step is required.** The job above works against an empty KQL database:
before its first send, `fab-test` checks that the table and its `fab_test_payload`
ingestion mapping exist and creates whatever is missing. A run against a healthy
cluster issues no schema commands. Query the payload through the one column:
`fabric_static_analysis | project Data.analyzer, Data.status, todatetime(Data.timestamp)`.

For a governed cluster where CI may ingest but not alter schema, create them once
by hand — the run prints exactly this when it cannot:

```kusto
.create-merge table fabric_static_analysis (Data: dynamic)
.create-or-alter table fabric_static_analysis ingestion json mapping 'fab_test_payload'
    '[{"column":"Data","path":"$","datatype":"dynamic"}]'

.create-merge table fabric_dynamic_analysis (Data: dynamic)
.create-or-alter table fabric_dynamic_analysis ingestion json mapping 'fab_test_payload'
    '[{"column":"Data","path":"$","datatype":"dynamic"}]'
```

The mapping name is fixed and the mapping is **not optional** — without it Kusto maps
by column name, matches nothing, and stores empty rows while reporting success. That
is why `fab-test` verifies the mapping and not just the table.

**`fab-test` creates tables, never databases or Eventhouses.** A missing database is
reported as such rather than built.

**Grant the credential the Database Ingestor role** on the KQL database (in Fabric:
the Eventhouse item → Manage permissions). Without it the service principal
authenticates perfectly and cannot ingest, which is indistinguishable from a bad
secret unless something says so — `fab-test doctor` does, and so does the failure
message.

**Ingest is queued, not immediate.** A delivered record typically becomes queryable
within a minute or two under the default batching policy, so a query straight after
the run can legitimately return nothing yet. `telemetry delivered` means the cluster
accepted the batch.

The job's exit code is never affected by telemetry. A failed send prints one warning
for the whole run and sets `telemetry_error` in `run.json`, so a pipeline that
uploads only the manifest can still tell that records were dropped:

```json
{ "telemetry_error": "Forbidden (403): ... -- The credential authenticated but is not permitted to ingest. Grant it the Database Ingestor role ..." }
```

To turn it off for a job without touching the config file, set
`ENABLE_EVENTHOUSE_LOGGING=false` or pass `--no-telemetry`. To see what would be sent
without sending it, add `--dry-run` — it prints every configured destination
(Eventhouse's cluster/database/table, Lakehouse's workspace/name) alongside each
payload.

### Pipeline snippet: shipping telemetry to a Lakehouse instead (or as well)

Independent of Eventhouse — configure either, both, or neither. Add a second
`telemetry` key to the same committed `fab-test.yml`, and optionally override it per
environment the same way:

```yaml
# fab-test.yml
telemetry:
  lakehouse:
    workspace: <workspace-name-or-guid>
    lakehouse: <lakehouse-name>
```

```yaml
- name: Install fab-test with the Lakehouse telemetry extra
  run: pip install 'fab-test[telemetry-lakehouse]'

- name: Run analyzers
  env:
    FABRIC_TENANT_ID: ${{ secrets.FABRIC_TENANT_ID }}
    FABRIC_SERVICE_PRINCIPAL_ID: ${{ secrets.FABRIC_SERVICE_PRINCIPAL_ID }}
    FABRIC_SERVICE_PRINCIPAL_SECRET: ${{ secrets.FABRIC_SERVICE_PRINCIPAL_SECRET }}
    # Optional: override the committed fab-test.yml address per environment.
    LAKEHOUSE_WORKSPACE: ${{ vars.LAKEHOUSE_WORKSPACE }}
    LAKEHOUSE_NAME: ${{ vars.LAKEHOUSE_NAME }}
  run: fab-test all --format json --artifact-dir .fabric/artifacts
```

Records land as one JSONL file per table per run under
`Files/fab-test-telemetry/<table>/<run_id>.jsonl` (`<lakehouse-name>.Lakehouse/...`,
or bare `<lakehouse-guid>/...` on a tenant with OneLake friendly names disabled).
The Lakehouse's "Load to Tables" wizard only recognizes CSV/Parquet, not
JSON/JSONL, so load these into a real table with a Spark notebook instead:

```python
table = "fabric_static_analysis"  # or fabric_dynamic_analysis
df = spark.read.json(f"Files/fab-test-telemetry/{table}/")
df.write.format("delta").mode("overwrite").saveAsTable(table)
```

`overwrite` re-reads every JSONL file each run so a rerun never double-counts a
record; schedule the notebook (or run it after each CI job) to keep the table
current. Once loaded, query through the Lakehouse's SQL endpoint, Direct Lake, or
Power BI — no KQL. The credential needs a workspace role (e.g. Contributor) or a
direct share on the Lakehouse item; `fab-test doctor`'s `telemetry-lakehouse` row
names what's missing. If both destinations are configured and one fails, the other
still delivers, and `run.json`'s `telemetry_error` names only the failed one(s).

### Running the local-Desktop analyzer set in CI

`fab-test local` (see [QUICKSTART-LOCAL.md](QUICKSTART-LOCAL.md)) isn't only for a laptop — it runs the same in a pipeline, since it never requires a workspace ID or service principal:

```yaml
- name: Check local-workflow readiness
  run: fab-test doctor --local --format json

- name: Run the local-Desktop analyzer set
  run: fab-test local --format json

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  with:
    name: fab-test-run-manifest
    path: fab-test-results/run.json
```

The difference from running it on a laptop: no Power BI Desktop instance is open in CI, so `pql-test`'s DAX tests connect to nothing rather than binding to a `desktop` port. That artifact reports status `warning` with `0 tests, 0 passed, 0 failed, 0 skipped`, emits a `::warning::` annotation, and exits 0 — never a failure (see vision.md's "platform gaps degrade to skips"), and never a green `passed` either, so the log cannot be misread as "the DAX tests ran and were fine." BPA and PBIR Inspector are unaffected — they don't depend on Desktop at all.

## Clean up

When finished, deactivate the virtual environment:

```bash
deactivate
```

Remove the test environment and build artifacts if desired:

```bash
rm -rf .venv-test dist
```

On Windows:

```powershell
Remove-Item -Recurse -Force .venv-test, dist
```

## Full reference

- [`fab-test` CLI reference](../.github/skills/fab-test/SKILL.md)
- [`pytest.ini`](../pytest.ini) for test markers and configuration
