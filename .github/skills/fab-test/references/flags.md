# Flags

## Global Flags (all subcommands)

| Flag | Default | Description |
|------|---------|-------------|
| `TARGET` (positional) | (discover all) | What to test — see [Targeting](targeting-and-discovery.md#targeting) for the grammar |
| `--artifact STEM` | (all) | Deprecated alias for `TARGET`; passing both exits `2` |
| `--artifact-dir DIR` | the working directory | Root to discover artifacts under, recursively |
| `--output-dir DIR` | `fab-test-results` | Root directory for result envelopes |
| `--dry-run` | off | List matching artifacts without running any analyzer |
| `--telemetry` / `--no-telemetry` | config-driven | Force/suppress Eventhouse telemetry. A configured destination already enables it; `--telemetry` with none configured exits `2` — see [Telemetry](configuration.md#telemetry) |
| `--report` / `--no-report` | off | Write a readable HTML report beside each envelope [env: `ANALYZER_REPORT`] |
| `--format {text,json}` | `text` | Aggregate summary output format (see the main SKILL.md's Agent Contract section for the stdout guarantee) |
| `-v`, `--verbose` | off | Increase output verbosity (one `-v` = per-finding detail, two `-v` = command + stdout/stderr) |
| `--timeout SECONDS` | `200` | Per-artifact subprocess timeout [env: `ANALYZER_TIMEOUT`] |
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

Runs BPA, PBIR Inspector, and Desktop-bound `pql-test` against every `.pbip` project discovered under `--artifact-dir` — no `.fabric/artifacts` layout required, no Fabric workspace, no service principal. Its subparser doesn't expose `--workspace-id` or `--env` at all, so the remote XMLA path is unreachable from `local`.

| Flag | Default | Description |
|------|---------|-------------|
| `--artifact-dir DIR` | the working directory | Root to discover `.pbip` projects — the same default every subcommand now uses |
| `--tabular-editor-path`, `--bpa-rules-path`, `--inspector-path`, `--rules-path` | same as `bpa`/`pbir` | Passed straight through to those two analyzers |

```bash
fab-test local --dry-run    # see which projects were found and which analyzers would run
fab-test local              # run it
fab-test local --format json
```

A missing prerequisite (`pqlint` not installed, Tabular Editor/PBIR Inspector not resolved) is reported as **skipped** with a remediation hint — it never fails the run. Exit code `1` only means a real finding, never a missing tool. `pql-test` is always ready (it's a pinned `fab-test` dependency); if a Desktop instance has the project's `.pbip` open, `pql-test`'s envelope records a `desktop` field naming the port and model it bound to (see `pql-test` below and the run manifest section in the main SKILL.md's Agent Contract for the full shape).

Discovery walks `--artifact-dir` recursively — see [Discovery](targeting-and-discovery.md#discovery) for the rules, which are the same for every subcommand.

### bpa

| Flag | Env var | Default |
|------|---------|---------|
| `--tabular-editor-path PATH` | `TABULAR_EDITOR_PATH` | `TabularEditor/TabularEditor.exe` |
| `--bpa-rules-path PATH` | — | resolved via the metadata layers (`.fab-test/metadata/rules/BPARules.json` > `.github/metadata/...` > packaged) |

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
| `--rules-path PATH` | — | resolved via the metadata layers (`.fab-test/metadata/rules/pbi-inspector-custom-rules.json` > `.github/metadata/...` > packaged) |

### a11y

Accessibility checks for `.Report` artifacts — contrast, alt text, tab order, target size, page/visual titles, font scaling, and more — via [pbir-a11y](https://github.com/Juls-BI/pbir-a11y), a Node CLI built from source at a pinned ref rather than downloaded pre-built (see [Node toolchain and the pbir-a11y build cache](#node-toolchain-and-the-pbir-a11y-build-cache) below). **Requires Node.js >= 18 and npm** the first time it runs; `fab-test doctor --analyzer a11y` reports whether both are present before anything is built.

**Deliberately not run by `fab-test all`** — it is not in the default `fab_test_all` list in `analyzers.json`, so an existing pipeline's behavior is unchanged by this analyzer's existence. Opting in is a one-line metadata edit: add `"a11y"` to `fab_test_all` in `analyzers.json`.

| Flag | Env var | Default |
|------|---------|---------|
| `--a11y-path PATH` | `PBIR_A11Y_PATH` | `pbir-a11y/dist/cli.js`, or the cached build under `.fab-test-tools/pbir_a11y/` once one exists |
| `--fail-on SEVERITY` | — | Forwarded to pbir-a11y's own `--fail-on` (`warn`\|`fail`; pbir-a11y's own default is `fail`, so a warning is reported but does not fail the run unless tightened) |

```bash
fab-test a11y                          # every discovered .Report artifact
fab-test a11y SalesReport               # one artifact by name
fab-test a11y --fail-on warn            # tighten: a warn-level finding now fails the run
fab-test a11y --format json             # machine-readable
```

**Envelope status and exit code**: `pbir-a11y`'s own exit code decides the envelope's `status`, not a re-derivation from severities alone — `2` (a bad or unreadable project path) is a **tool error** (`status: "error"`), always distinct from `1` (a real accessibility finding at or above `--fail-on`'s threshold, `status: "failed"`) or `0` with findings still present below that threshold (`status: "warning"`). Findings carry the same four-column shape every analyzer's envelope does (`rule`/`severity`/`object`/`message`), plus three additive keys `pbir-a11y`'s output has and no other analyzer does — `category` (e.g. `altText`, `contrast`, `tabOrder`), `page`, and `visual` (`null` for a page-level finding) — useful to a caller filtering the raw envelope JSON; the shared summary table and `--report` HTML page read only the canonical four, with `category` folded into the `message` text (`[altText] Missing alt text: ...`) so a category is still findable there via the report's search box or by sorting the Message column.

### Node toolchain and the pbir-a11y build cache

Every other bootstrapped analyzer (`bpa`, `pbir`) downloads a pre-built binary and caches it. `a11y` is the one exception: pbir-a11y ships no pre-built release artifact, only source, so the first run clones its pinned tag, runs `npm install` and `npm run build` inside `.fab-test-tools/pbir_a11y/<platform>/<version>/`, and caches the resulting `dist/cli.js` — after that, resolution is instant and touches no network, exactly like the other two. A version bump in `analyzers.json` forces a fresh build the same way it forces a fresh download for `bpa`/`pbir`; nothing has to be cleared by hand (`fab-test clean-tools` still works if you want to).

If `npm` or `node` is missing, `doctor` says which one distinctly (Node absent vs. npm absent are different remediations) rather than a generic "tool not found." If a build is already cached but the *current* machine running the check lacks `node` — a cache copied from elsewhere, or Node uninstalled after the fact — the wrapper reports a clear envelope error rather than a traceback, the same way a missing binary is handled for every other analyzer.

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

### playwright

Playwright validation can run in three modes: static `.env` mode, service-resolved mode, or impact-manifest mode.

| Flag | Description |
|------|-------------|
| `--env-file PATH` | Path to `.env` file with service-principal credentials and optional behavior settings |
| `--artifact NAME` | Resolve the deployed report from this artifact name and the target environment |
| `--env ENV` | Target environment label (e.g. `dev`, `test`, `prod`) [env: `FABRIC_ENVIRONMENT`] |
| `--workspace-id ID` | Explicit workspace ID override [env: `FABRIC_WORKSPACE_ID`] |
| `--dataset-id ID` | Explicit dataset / semantic-model ID override |
| `--dataset-workspace-id ID` | Workspace ID the dataset lives in, when different from the report's own workspace [env: `PLAYWRIGHT_DATASET_WORKSPACE_ID`] |
| `--impact-manifest PATH` | Validate every report listed in the impacted-report manifest once, regardless of local `.Report` artifacts |
| `--pages {auto,none}` | Discover every report page and its own bookmarks (default: `auto`); `none` tests only the default page |
| `--roles {auto,none}` | Discover RLS/OLS roles from the semantic model and test the page matrix under each one when RLS is enabled (default: `auto`); `none` tests only `PLAYWRIGHT_ROLE` |
| `--workers N` | Max `pytest-xdist` workers for running generated cases concurrently (default: `4`) [env: `PLAYWRIGHT_XDIST_WORKERS`] |

**By default, `playwright` tests every page, every page's own bookmarks, and every
RLS role — not just the default tab.** `--pages none`/`--roles none` (or `PLAYWRIGHT_PAGE_IDS`/
`--page-ids`, which skip discovery entirely as an explicit override) fall back to the
one-case shape every prior release had. Discovery needs `Report.Read.All` (pages,
bookmarks) and `SemanticModel.Read.All` (roles) on the service principal beyond what
embedding already required; a missing grant logs a warning and falls back to the
single-case shape rather than failing the run. Each role gets its own embed token —
a token carries its RLS identity, so one token cannot cover two roles — and
discovered roles with no `PLAYWRIGHT_USER_NAME` abort before any token is minted
rather than silently testing no role at all (`GenerateToken` drops the identity
entry with an empty username). Case ids and `test_results` rows now carry page,
bookmark, and role, so two roles of the same page write to different evidence
directories instead of overwriting each other's `screenshot.png`.

**`playwright` always needs a full service principal — unlike every other analyzer.**
`get_embed_context` calls MSAL with a client secret to generate the embed token; an
ambient `az login` (which `pql-test` and workspace discovery both accept) cannot do
that. With `FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`/`FABRIC_SERVICE_PRINCIPAL_ID`, or
`FABRIC_CLIENT_SECRET`/`FABRIC_SERVICE_PRINCIPAL_SECRET` incomplete, the command
refuses **before** building a client or making any network call, exits `127` (a
missing prerequisite, not a run failure), and names every missing variable and where
to set it:

```
::error::Playwright needs a full service principal to generate an embed token;
missing: FABRIC_TENANT_ID, FABRIC_CLIENT_ID (or FABRIC_SERVICE_PRINCIPAL_ID),
FABRIC_CLIENT_SECRET (or FABRIC_SERVICE_PRINCIPAL_SECRET). Set them in the
environment, in a .env file, or pass --env-file.
```

`fab-test doctor` reports `playwright` as not ready for the same reason rather than
a false green when only an ambient credential is available — `playwright-impact` and
`dependencies`, which never call the embed-token API, are unaffected and accept
ambient auth like every other cloud-backed analyzer.

**Generated cases run concurrently, up to a bounded worker cap.** A report's
page/bookmark/role matrix can generate many cases; they run across `pytest-xdist`
workers (`-n`) rather than one after another, and the outer subprocess timeout scales
with the real generated count instead of a flat number sized for one case (both
transparent — nothing to configure to get them). The worker count itself defaults to
`4` (each worker opens its own browser instance, so it isn't unconditionally maximal
the way `pytest-xdist`'s own `-n auto` would be) and is the one part of this that is
configurable: `--workers N` on the CLI, or `PLAYWRIGHT_XDIST_WORKERS` as an env var
when you'd rather not pass a flag on every invocation — raise it on a machine (e.g. a
CI runner or VM) that can safely hold more concurrent browser instances than a
laptop.

Any other exception while acquiring the embed context (a malformed tenant, an
unreachable API) is also caught: it never reaches the console as a traceback. It
writes an error envelope, emits `::error::` to stderr, and returns `1` — and in a
`--impact-manifest` run, one report's failure does not stop the others.

**`environments.yml` is optional once a workspace is already resolved.** When
`--workspace-id`, `FABRIC_WORKSPACE_ID`, or `workspace:` in `fab-test.yml` already
supplies a workspace, `environments.yml` is never opened — a missing file or an
absent `dev:` entry no longer fails a run whose workspace was never in question. It
is read exactly as before only when no workspace resolves from any of those sources;
a repository that already pins its workspace there is unaffected. `workspace:` is
discoverable: `fab-test init` scaffolds a commented line for it, and
`fab-test config --show` lists its effective value and origin (`fab-test.yml:workspace`,
`env:FABRIC_WORKSPACE_ID`, etc.) alongside every other setting.

**Every generated case gets its own accurate result, not the run's outcome copy-pasted.**
`fab-test-results/playwright/test-cases/<case>/result.json` (written by the pytest
spec itself, per case) records that case's real `status` (`pass`/`error`) and, on
failure, the actual detail -- the embed error, a render timeout, or an RDL error
modal -- rather than the fixed string every case used to share. The envelope's
`test_results` carries one row per case built from that file (falling back to the
run's overall outcome only for a case the process never reached), so `findings`
now names only the case that actually failed, with its own message -- a report
with 5 pages and 1 real failure reports 1 finding, not 5 identical ones. Each row
also carries an `evidence` map (`screenshot`/`console`/`network`, whichever files
exist for that case) and a `report_link` (`{label, href}` back to the exact
report page/bookmark/report the case validated, on `app.powerbi.com` -- omitted
for paginated reports and for a case that never resolved a workspace/report id);
`--report`'s generated `report.html` renders both as an Evidence column and a
Report Page column (present only when at least one row actually carries that
field), and `--output-path`'s `envelope.json` -- what `output_path` in
`--format json` output already points an agent at -- carries the same paths and
link, so nothing beyond reading that one file is needed to reach either.

**Paginated (RDL) reports are validated with a different check than interactive
reports.** Set `PLAYWRIGHT_REPORT_TYPE=paginated` (default `report`) to switch
targets. A paginated report is resolved against Fabric item type
`PaginatedReport` instead of `Report`. Page/bookmark/role discovery is skipped
entirely (RDL reports have neither dimension), and exactly one test case is
generated, with no `page_name`/`bookmark_name` and a `report_link` that stays
`{}` (RDL reports use a different URL shape in the Fabric portal, not yet
linked). The embed configuration itself carries no `pageName`/`bookmark` key
at all, rather than empty values that would mimic a real page or bookmark.
Because a paginated report never fires the interactive embed SDK's
`rendered`/`error` events, the pytest spec does not race them for this case:
it embeds, waits `PLAYWRIGHT_RENDER_WAIT_SECONDS` (default `20`; also settable
per case via `render_wait_seconds` if you generate test cases yourself), lets
in-flight network activity settle (`networkidle`, bounded to 5s, best-effort),
and then scans the page and every iframe for Power BI's own `ms-Dialog-content`
error-modal marker -- found means the case fails, absent means it passes.
Evidence (screenshot, console, network) is captured the same way as an
interactive-report failure either way.

```bash
PLAYWRIGHT_REPORT_TYPE=paginated fab-test playwright --artifact "Invoice RDL" --env dev --env-file .env
```

**A paginated report's embed token payload is deliberately different from an
interactive report's, and needs a dataset ID more often than not.** `resolve_report`
looks up a bound dataset the same way for either report type (Power BI's
`GET /reports/{id}` metadata endpoint), but that lookup commonly comes back
empty for an RDL report even when it queries one or more Power BI datasets as
data sources -- confirmed live against real RDL reports. When that happens,
`GenerateToken` itself rejects the request with `"At least one dataset is
required"`, so pass the dataset explicitly with `--dataset-id`/`PLAYWRIGHT_DATASET_ID`.
When that dataset lives in a *different* workspace than the report -- common
practice for a dataset shared across several reports -- also pass
`--dataset-workspace-id`/`PLAYWRIGHT_DATASET_WORKSPACE_ID`; naming only the
report's workspace produces a misleading `"Cannot connect to dataset ... because
XMLA permissions are off"` 400 that has nothing to do with any XMLA setting
(confirmed live: the identical error persisted across several payload shapes
until the dataset's actual workspace was named). Once named, a paginated
report's `GenerateToken` payload is otherwise minimal -- `reports`/`datasets`
only, no `targetWorkspaces`/`accessLevel` -- matching a validated reference
implementation exactly; an interactive report's payload is unchanged (it keeps
`targetWorkspaces`/`accessLevel`, and gains the same cross-workspace
`--dataset-workspace-id` support).

```bash
PLAYWRIGHT_REPORT_TYPE=paginated fab-test playwright --artifact "Invoice RDL" --env dev \
  --dataset-id 4c353b5c-d311-4e90-b9d1-5766b87f59dc \
  --dataset-workspace-id c4698d28-b05c-40bc-926c-707563ac85e7
```

**`--artifact NAME --env ENV` now resolves live even with no matching local
folder.** Previously `fab-test playwright --artifact NAME --env ENV` silently
required a local folder named `NAME.Report` under `--artifact-dir` to exist --
the folder was never read for playwright (it validates the *deployed* report,
never local file content), but discovery still needed one to find before
dispatching. That made a purely-remote report -- any paginated (RDL) report,
since this project's `.fabric/artifacts/` tree only ever holds PBIR-format
interactive reports checked in from Desktop -- undiscoverable through the real
CLI, previously working only by coincidence when a same-named local folder
happened to exist. `fab-test playwright` now falls back to resolving the named
target live whenever local discovery finds nothing and an environment was
given; a real filesystem path (`./src/Sales.Report`) is unaffected -- naming a
specific location and finding nothing there is still a real miss, not a
service-resolution signal.

**A render timeout or a broken visual names the real cause, not just a bare
timeout.** The spec races `rendered` against `error` by listening on
`document.body` (not `report.on(...)` on the embed object, which never sees a
per-visual error event) -- an `error` is always authoritative, and a `rendered`
that arrives first still waits out a `PLAYWRIGHT_VISUAL_ERROR_GRACE_MS`
(default `5000`) grace window in case a delayed per-visual `error` overwrites
it. Every SDK event seen is written to that case's `event_log.json` regardless
of outcome. When neither event ever fires (`result is None`), the spec makes a
best-effort scan of every frame for Power BI's own "Something went wrong"
panel, clicks "Show details" if present, and folds any text found into both
the failure message and a new `embed_error_details.txt` -- with no such panel,
it falls back to the plain "did not render within Xms" message and writes no
extra file. The render-wait budget itself is `PLAYWRIGHT_TIMEOUT_SECONDS`
(default `180`), sized under the per-artifact subprocess timeout (`--timeout`/
`ANALYZER_TIMEOUT`, default `200`) so a genuinely slow render is not killed by
the outer timeout before its own budget expires.

Static `.env` mode uses workspace, report, dataset IDs directly from the env file:

```bash
fab-test playwright --env-file .env
fab-test playwright --env-file .env --dry-run
```

Service-resolved mode resolves the deployed report from the artifact name and an
already-known workspace (`workspace:` in `fab-test.yml`, `FABRIC_WORKSPACE_ID`, or
`--workspace-id`), falling back to `environments.yml` only when none of those
resolve one:

```bash
fab-test playwright --artifact "Not Working Visuals" --env dev --env-file .env
fab-test playwright --artifact SalesReport --env test --env-file .env
```

When [`resolve_item`](../../../../src/fabric_ci_cd_dataops/scripts/playwright_validation/resolver.py)
finds no match, the message names the closest candidates the workspace actually has
(capped for an 80-column terminal), says plainly when the workspace has no items of
that type at all, and lists the workspace once rather than twice:

```
No Report matching 'ThinReport' in workspace 33333333-3333-3333-3333-333333333333.
Closest candidates: Sales Report, Marketing Report, and 3 more.
```

Impact-manifest mode validates every report impacted by changed artifacts. It is repository-scoped and runs once:

```bash
fab-test playwright-impact --changed-artifacts changed-artifacts.json --env dev --env-file .env
fab-test playwright --impact-manifest fab-test-results/playwright/impact-manifest.json --env dev --env-file .env
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

Runs the analyzer names listed in `analyzers.json` (resolved via the metadata layers) under the `fab_test_all` key. This keeps the local command aligned with the same metadata that drives CI.

Current default list:

```json
{
  "fab_test_all": ["bpa", "pbir", "pql_test"]
}
```

`playwright` is excluded from `fab-test all` by default but remains available as a direct subcommand.

Accepts the union of flags from `bpa`, `pbir`, and `pql-test`, plus `--playwright-env-file` for Playwright support.

```bash
fab-test all \
  --tabular-editor-path "C:\..." \
  --env DEV \
  --playwright-env-file .env
```

After all analyzers finish, `fab-test all` prints an aggregate summary table showing analyzer, artifact, status, errors, warnings, and output path, plus total errors and warnings across the run.
