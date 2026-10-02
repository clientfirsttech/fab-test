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
| `--open-report` | off | Open the produced report/index in the default browser after the run; implies `--report`; a no-op under CI [env: `ANALYZER_OPEN_REPORT`] — see [Reports](reports.md#open-report) |
| `--format {text,json}` | `text` | Aggregate summary output format (see the main SKILL.md's Agent Contract section for the stdout guarantee) |
| `-v`, `--verbose` | off | Increase output verbosity (one `-v` = per-finding detail, two `-v` = command + stdout/stderr). Cannot be combined with `-q` (exit `2`) |
| `-q`, `--quiet` | off | Print one line per artifact and nothing else on a passing run — see [Output Verbosity](operations.md#output-verbosity) [env: `ANALYZER_VERBOSITY=summary`, config: `verbosity: summary`] |
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

**Requires the .NET 8 runtime.** The `fab-inspector` release is a framework-dependent build (`.NET 8.0 dependency not included`, per its release notes) — the binary can be present, executable, and correctly versioned and still be unable to run. `fab-test doctor --analyzer pbir` checks for an installed .NET 8+ runtime (via `dotnet --list-runtimes`) and reports not-ready, with a link to the .NET download page, rather than reporting the binary alone as sufficient. If the runtime check somehow passes on a machine where the tool still can't run, the wrapper's own exit code and stderr are surfaced as an `error` envelope status (never a silent `passed` with zero findings) — see [Envelope schema keys](operations.md) for how `error` differs from `passed`.

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

If `npm` or `node` is missing before the first build, `doctor` says which one distinctly (Node absent vs. npm absent are different remediations) rather than a generic "tool not found." `doctor` also checks for Node.js >= 18 on every run, not only the first — a cache copied from elsewhere, or Node uninstalled after the fact, is reported as not-ready by `doctor` itself rather than only surfacing once `fab-test a11y` is actually run. If it somehow still runs without Node present, the wrapper reports a clear envelope error rather than a traceback, the same way a missing binary is handled for every other analyzer.

### rdl

Static analysis for paginated (`.rdl`) reports: the active rules (Tier A rules are enabled once a real fixture verifies each; `status` in the catalog, listed in `docs/RDL-RULES.md`) covering structure/schema, data sources, query pushdown, parameters, layout/subreports, and accessibility — see [plan/rdl-rule-set.md](../../../../plan/rdl-rule-set.md) for what each rule ID checks. Pure Python on the standard library; **no external tool, no install step** — `doctor` always reports it ready. Every finding and `test_results` row carries `source_urls`, the guidance links for its rule (`docs/RDL-RULES.md` lists them all). A finding's `object` is a path (`Dataset › Field`, `Tablix › Textbox`) and its `message` quotes the offending query or expression, so the message alone identifies the offender; a rule that fires on several elements has one `test_results` row per hit. `--verbose` prints a Rule/Severity/Object/Message findings table.

| Flag | Default |
|------|---------|
| `--rules-path PATH` | resolved via the metadata layers (`.fab-test/metadata/rules/rdl-rules.json` > `.github/metadata/...` > packaged) |

```bash
fab-test rdl                     # every discovered .rdl file
fab-test rdl Sales                # one artifact by name (a flat .rdl file, not a folder)
fab-test rdl Sales.rdl            # name and type, explicit
fab-test rdl --format json
```

A `.rdl` file is discovered the same way a folder artifact is — by suffix, recursively under `--artifact-dir` — except the suffix is a file extension, not a folder name, so `discover_artifacts` matches it with `find_files_by_suffix` instead of the directory-suffix scan every other analyzer uses (see [Discovery](targeting-and-discovery.md#discovery)). Every finding carries `rule`/`severity`/`object`/`message`; `test_results` (in the same rule shape as `pbir`, see [Reports](reports.md)) covers every active rule, passed or fired (one row per hit) — `status` is `pass`, `skip` (disabled in the overlay), `warning`, or `error` per row; planned rules never appear. Tune a rule with a `rules.rdl` overlay in `fab-test.yml` — see [Rule Overlays](configuration.md#rule-overlays).

`LAY-03` and `SUB-01` both name "a Subreport nested in a Tablix" — the same check produces one finding tagged `"LAY-03/SUB-01"` rather than two separate findings for the same gap; both catalog rows in `test_results` show that one finding.

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

**When the model is unreachable, nothing ran — and that is a `warning`, not a
pass or a failure.** `pql-test` enumerates its tests statically from the
`.SemanticModel`'s TMDL and `DAXQueries`, so it reports a test count even with
no connection, then fails each one with an ADOMD "a connection cannot be made"
error. `fab-test` recognizes that signature and does not let it read as either
outcome:

```
Constraints {
  (exit 0, zero tests discovered)          => "warning", "pql-test found no tests to run in this model"
  (exit non-zero, zero tests discovered)   => "warning", "pql-test ran no tests"
  (every failure is a connection error)    => "warning", "pql-test ran no tests: could not connect to the model"
  (any failure is a real assertion)        => "failed"   // never hidden behind a platform skip
  (every test reported skipped)            => "skipped"
  (tests ran, none failed)                 => "passed"
}
```

Each `warning` case reports `0 tests, 0 passed, 0 failed, 0 skipped` in the
envelope's `test_summary` — the statically-discovered count would overstate what
happened — renders as `⚠️` in the per-artifact line and the aggregate table,
emits `::warning::` on stderr, and exits 0, so a closed Desktop session does not
turn CI red. `native.json` keeps `pql-test`'s own unmodified numbers. One genuine
assertion failure among connection errors still fails the run.

### playwright

Playwright validation can run in three modes: static `.env` mode, service-resolved mode, or impact-manifest mode.

| Flag | Description |
|------|-------------|
| `--env-file PATH` | Path to `.env` file with service-principal credentials and optional behavior settings |
| `--artifact NAME` | Resolve the deployed report from this artifact name and the target environment |
| `--env ENV` | Target environment label (e.g. `dev`, `test`, `prod`) [env: `FABRIC_ENVIRONMENT`] |
| `--workspace NAME_OR_ID` | Explicit workspace override, a name or a GUID. `--workspace-id` and `--from-workspace` are accepted aliases for the same value; prefer `--workspace` [env: `FABRIC_WORKSPACE_ID`] |
| `--dataset-id ID` | Dataset / semantic-model ID. With `--artifact`, overrides that report's binding; with no report named, tests every report built on this dataset (see below) |
| `--dataset-workspace-id ID` | Workspace ID the dataset lives in, when different from the report's own workspace [env: `PLAYWRIGHT_DATASET_WORKSPACE_ID`] |
| `--report-type {report,paginated}` | Force the report type instead of auto-detecting it [env: `PLAYWRIGHT_REPORT_TYPE`] |
| `--impact-manifest PATH` | Validate every report listed in the impacted-report manifest once, regardless of local `.Report` artifacts |
| `--pages {auto,none}` | Discover every report page and its own bookmarks (default: `auto`); `none` tests only the default page |
| `--roles {auto,none}` | Discover RLS/OLS roles from the semantic model and test the page matrix under each one whenever RLS is in play — `PLAYWRIGHT_USE_RLS`, **or** an effective-identity user being configured at all (default: `auto`); `none` tests only `PLAYWRIGHT_ROLE` |
| `--plan-only` | Discover the matrix, write `test-cases.csv`/`.json`, and stop — no embed token, no browser. Unlike `--dry-run`, which only lists matching artifacts, this resolves each one |
| `--workers N` | Max `pytest-xdist` workers for running generated cases concurrently (default: `4`) [env: `PLAYWRIGHT_XDIST_WORKERS`] |
| `--playwright-config PATH` | Optional validated local/Azure browser YAML [env: `PLAYWRIGHT_CONFIG_PATH`; config: `playwright_config`]. Not the global `--config` flag |
| `--headed` | Show the local browser windows; off by default. Overrides `launch.headless` in the YAML and `PLAYWRIGHT_HEADLESS`. Ignored with a warning on Azure-hosted browsers |
| `--slow-mo MS` | Pause MS milliseconds between browser actions (nonnegative; local browsers only; overrides `launch.slow_mo`). A negative value exits `2` |

The execution selector resolves flag > process environment > fab-test config >
local default. Flag/environment paths are relative to the invocation directory;
`playwright_config` paths are relative to their owning YAML or pyproject file.
`config --show` reports the selection and origin; dry-run makes no browser
connection. Worker limits resolve `--workers` > `PLAYWRIGHT_XDIST_WORKERS` >
execution YAML > `4` and are bounded by the current report's case count.

Execution YAML permits only `backend` (`local`/`azure`), positive `workers`,
`launch` (`headless`, string-list `args`, nonnegative `slow_mo`), `context`
(`viewport` width/height, `locale`, `timezone_id`, `color_scheme`,
`ignore_https_errors`), and Azure `connection` (`os` linux/windows,
positive `timeout_ms`, `expose_network`). Defaults are Linux, 30000 ms,
and `<loopback>`. Report-render timeout remains `PLAYWRIGHT_TIMEOUT_SECONDS`.

Browser visibility resolves `--headed` > YAML `launch.headless` > `PLAYWRIGHT_HEADLESS=false` > headless
(default). `PLAYWRIGHT_HEADLESS=false` applies to local browsers only and is ignored with a warning on Azure.
No custom tests, plugins, reporters, or executable config are accepted.

Azure requires `PLAYWRIGHT_SERVICE_URL` and `PLAYWRIGHT_SERVICE_ACCESS_TOKEN`
in process environment or the selected env file; process values win. Fabric
credentials remain separate. Never put tokens or credential-bearing URLs in
YAML. Invalid YAML exits `2`; missing service prerequisites exit `127`;
connection failure writes an `error` envelope with `playwright_execution_error`,
not a visual finding, and never falls back locally. Plan-only needs no Azure
token. For selected YAML, native pytest HTML/JUnit are under each report's
`report/` directory alongside the unchanged facade envelope and case evidence.
See `docs/PLAYWRIGHT-CI.md` for authentication and Python-only CI examples.

**By default, `playwright` tests every page, every page's own bookmarks, and every
RLS role — not just the default tab.** `--pages none`/`--roles none` (or `PLAYWRIGHT_PAGE_IDS`/
`--page-ids`, which skip discovery entirely as an explicit override) fall back to the
one-case shape every prior release had. Discovery needs the full permission set
in `docs/PLAYWRIGHT-CI.md` ("Register the service principal") on the service
principal beyond what embedding already required; a missing grant logs a
warning and falls back to the single-case shape rather than failing the run.
Each role gets its own embed token —
a token carries its RLS identity, so one token cannot cover two roles — and
discovered roles with no effective-identity user (`PLAYWRIGHT_USER_NAME`, or
`playwright_user_name` in `fab-test.yml`) abort before any token is minted
rather than silently testing no role at all (`GenerateToken` drops the identity
entry with an empty username). Case ids and `test_results` rows now carry page,
bookmark, and role, so two roles of the same page write to different evidence
directories instead of overwriting each other's `screenshot.png`.

**The matrix a report expands into**: one case per page, plus one case per that
page's *own* bookmark (never a page paired with another page's bookmark), and
the whole set repeated once per discovered role. A report with 2 pages, 1
bookmark on the first and 2 on the second, under 2 roles, is 10 cases.
Bookmarks are found in the PBIR `definition/bookmarks/` parts, a flat
`definition/bookmarks.json`, **or** a legacy `report.json`'s embedded config —
the shape every report in a classic (non-PBIR) workspace still has. A bookmark
*group* is expanded into its children, which carry the state; the group itself
is not a case. `user_name` is emitted only on a case that carries a role: an
embed token for a model with no RLS is rejected outright when it carries an
identity.

See what a report would test, without rendering it:

```bash
fab-test playwright --artifact "Sales Report" --plan-only
```

This writes the same `test-cases.csv`/`test-cases.json` a real run writes and an
envelope with status `skipped`, then exits `0` — no embed token is minted and no
browser is launched, so it works on a machine where `playwright install` has
never run. Passing `--dry-run` as well takes the cheaper path: `--dry-run` wins
and no discovery call is made.

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

**Exit `127` is a setup problem, exit `1` is a report failure.** A run that never
reached a case (missing credential, unresolved workspace, unknown report name)
exits `127` and names what's missing; a run that opened the report and found a
real problem (a broken visual, a render timeout, an RLS token that couldn't be
minted) exits `1`. Don't retry a `127` — fix the named prerequisite first.

**Setting this up in CI** (service principal registration, tenant settings,
workspace role, XMLA endpoint, GitHub Environment/secrets) is a one-time,
outside-the-CLI prerequisite covered in `docs/PLAYWRIGHT-CI.md`, not here. A
copy-ready workflow lives at
`docs/examples/github-actions/playwright-live.yml`; this repository's own
`.github/workflows/playwright-demo.yml` (manually dispatched, gated behind
the `fabric-demo` Environment) is the working reference for what a real
dispatch looks like.

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
`--workspace` (or its `--workspace-id`/`--from-workspace` aliases), `FABRIC_WORKSPACE_ID`,
or `workspace:` in `fab-test.yml` already supplies a workspace, `environments.yml` is never opened — a missing file or an
absent `dev:` entry no longer fails a run whose workspace was never in question. It
is read exactly as before only when no workspace resolves from any of those sources;
a repository that already pins its workspace there is unaffected. `workspace:` is
discoverable: `fab-test init` scaffolds a commented line for it, and
`fab-test config --show` lists its effective value and origin (`fab-test.yml:workspace`,
`env:FABRIC_WORKSPACE_ID`, etc.) alongside every other setting.

**Every generated case gets its own accurate result, not the run's outcome copy-pasted.**
`fab-test-results/playwright/<report>/test-cases/<case>/result.json` (written by the pytest
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
reports, and fab-test determines which kind a target is itself.** You never
need to declare `--report-type`/`PLAYWRIGHT_REPORT_TYPE` up front:

- A local `NAME.Report`/`NAME.PaginatedReport` folder's own suffix tells the
  per-artifact subprocess its type directly -- a batch run with no `--artifact`
  discovers and correctly validates both kinds in the same repository, and a
  local `.PaginatedReport` folder (which previously wasn't discoverable at
  all) is found alongside `.Report` folders.
- `--artifact NAME --env ENV` with no matching local folder resolves the type
  live: `resolve_report` tries Fabric item type `Report` first, then
  `PaginatedReport`, and uses whichever actually matches the name.
- `--report-type {report,paginated}` (or `PLAYWRIGHT_REPORT_TYPE`) is an
  explicit override for the rare case you want to force it, mirroring
  `--dataset-id`'s override pattern -- never required for either path above.
  A single global value could never correctly describe a workspace with both
  report types in it, which is exactly why detection, not declaration, is the
  default. Static `.env`-only mode (workspace/report/dataset IDs supplied
  directly, no artifact name at all) is the one exception that still requires
  it -- there's no name to detect a type from there.

A paginated report is resolved against Fabric item type `PaginatedReport`
instead of `Report`. Page/bookmark/role discovery is skipped entirely (RDL
reports have neither dimension). One baseline case is generated with no
parameters, plus -- when the report declares parameters -- one case with a
parameter set applied at embed time as `parameterValues` (see below). Both
have no `page_name`/`bookmark_name` and a `report_link` that stays `{}` (RDL
reports use a different URL shape in the Fabric portal, not yet linked). The
embed configuration itself carries no `pageName`/`bookmark` key at all, rather
than empty values that would mimic a real page or bookmark. Because a
paginated report never fires the interactive embed SDK's `rendered`/`error`
events, the pytest spec does not race them for this case: it embeds, waits
`PLAYWRIGHT_RENDER_WAIT_SECONDS` (default `20`; also settable per case via
`render_wait_seconds` if you generate test cases yourself), lets in-flight
network activity settle (`networkidle`, bounded to 5s, best-effort), and then
scans the page and every iframe for Power BI's own `ms-Dialog-content`
error-modal marker -- found means the case fails, absent means it passes.
Evidence (screenshot, console, network) is captured the same way as an
interactive-report failure either way.

```bash
# Auto-detected -- no PLAYWRIGHT_REPORT_TYPE needed
fab-test playwright --artifact "Invoice RDL" --env dev --env-file .env

# Forced explicitly, if you ever need to
fab-test playwright --artifact "Invoice RDL" --env dev --report-type paginated
```

**A parameterized paginated report gets a second case with real values.** A
render with no parameters says nothing about a parameter's own
`FilterExpression`, which only breaks once a value is applied. The parameter
set holds the first valid value of each single-value parameter and the first
two of each multi-value one (a multi-value parameter repeats its name once per
value, the embed SDK's `parameterValues` shape). Declared parameters come from
the local `.rdl` when there is one, else the report's deployed definition
(Fabric `getDefinition`). Valid values come from a static `<ParameterValues>`
list, or from the parameter's own `<DataSetReference>` query run through
`executeQueries` against the report's dataset -- which needs the tenant's
**Dataset Execute Queries REST API** setting for the service principal. A
free-text parameter, or a query that fails, leaves only the baseline case and
logs a warning naming the parameter and the setting; it never fails the run.
Each `test_results` row carries `parameters` (`[{name, value}, ...]`, empty on
the baseline) so the two cases can be told apart:

```json
{"test_name": "Invoice_params-Region-East", "status": "error",
 "actual": "RDL error modal detected",
 "parameters": [{"name": "Region", "value": "East"}]}
```

A case that never rendered because its embed token failed records that failure
as `actual`, never `rendered`.

**A paginated report bound to a Power BI dataset resolves that binding
automatically -- from the report's own local `.rdl` file, when one exists.**
Power BI's `GET /reports/{id}` metadata lookup that resolves an interactive
report's dataset commonly comes back empty for an RDL report even when it
queries one or more Power BI datasets as data sources (confirmed live), so
`fab-test` reads a local `NAME.rdl` file's own `<DataSources>` block instead:
a `PBIDATASET` data source's `ConnectString` embeds the dataset's own GUID
(`Initial Catalog=sobe_wowvirtualserver-<GUID>`) and `rd:PowerBIWorkspaceName`
names the workspace it lives in, which commonly differs from the report's own
workspace -- a shared dataset commonly does. Nothing needs supplying by hand
for a report checked in this way. A report with no local `.rdl` resolves it
from its own data sources (`GET /reports/{id}/datasources`, whose Power BI
connection names the dataset as `sobe_wowvirtualserver-<GUID>`) -- without
this, `GenerateToken` refuses the token with *At least one dataset is
required*. `--dataset-id`/`PLAYWRIGHT_DATASET_ID` and
`--dataset-workspace-id`/`PLAYWRIGHT_DATASET_WORKSPACE_ID` remain available as
explicit overrides (a display name there resolves the same way
`WORKSPACE.Workspace/NAME.Type` targets resolve a workspace name).

A paginated report's `GenerateToken` payload is otherwise minimal --
`reports`/`datasets` only, no `targetWorkspaces`/`accessLevel` -- matching a
validated reference implementation, but its dataset entry carries one field
an interactive report's never does: `xmlaPermissions: "ReadOnly"`. Without it,
`GenerateToken` itself succeeds but the resulting token cannot connect to the
dataset, and embedding fails with `"Cannot connect to dataset ... because XMLA
permissions are off"` -- a genuinely misleading message: it has nothing to do
with any workspace, tenant, or capacity-tier XMLA setting (all changed and
tested live, no effect); only this one field, confirmed live and matching
[Microsoft's own paginated-report embedding
documentation](https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-paginated-reports),
clears it. An interactive report's dataset entry is unaffected.

**`--dataset-id` with no report named tests the reports built on that
dataset -- not every local report.** `fab-test playwright --dataset-id ID`
with no `--artifact`, target, or `--impact-manifest` looks the dataset's
dependent reports up live -- in `--dataset-workspace-id`'s workspace and, when
set and different, the `--workspace-id`/`FABRIC_WORKSPACE_ID`/`PLAYWRIGHT_WORKSPACE_ID` workspace --
and runs one per-report validation for each, embedded against that dataset.
With neither workspace given it refuses (exit `2`) before any network call;
a dataset nothing depends on exits `0` with a notice. `PLAYWRIGHT_DATASET_ID`
in a `.env` never switches this on -- only the flag does.

```bash
fab-test playwright --dataset-id 11111111-2222-3333-4444-555555555555 \
  --dataset-workspace-id aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
```

**A bare `--workspace` (no `--artifact`/target, no explicit `--artifact-dir`, and
no dataset selector) tests every deployed Report and PaginatedReport in that
workspace, listed live from Fabric instead of scanned from the repository --
so the run needs no checkout at all.** `--workspace-id` and `--from-workspace`
trigger the identical behavior; they are the same flag under three names, not
three separate modes. A workspace *name* resolves the same way a
`WORKSPACE.Workspace/NAME.Type` target's workspace half does -- a GUID is used
directly, a name is looked up and must be unambiguous. Naming a report
(`--artifact`/a target), passing an explicit `--artifact-dir` (even `.`), or
giving `--dataset-id`/`--dataset-workspace-id` all keep their own narrower
selection instead -- a bare `--workspace` only applies when nothing else
names what to run. An ambient `FABRIC_WORKSPACE_ID` or a `workspace:` in
`fab-test.yml`, with no `--workspace` on the command line, is unaffected and
keeps today's repository discovery -- only the explicit flag switches the
denominator.

```bash
# Every Report/PaginatedReport deployed in this workspace -- no checkout needed
fab-test playwright --workspace "Sales Dev"

# Equivalent -- same shared flag
fab-test playwright --workspace-id c4698d28-b05c-40bc-926c-707563ac85e7

# A real --artifact-dir keeps the repository as the denominator instead
fab-test playwright --workspace "Sales Dev" --artifact-dir .
```

**`--dataset-workspace-id` alone -- no `--dataset-id`, `--artifact`, target, or
`--impact-manifest` -- means every dataset in that workspace.** Every
semantic model in the workspace is listed live, and each one's own dependent
reports (including paginated/RDL reports) are run, embedded against that
model -- the same per-report resolution `--dataset-id` mode uses, just for
every dataset the workspace has rather than one named explicitly. `--env`
works in place of (or alongside) `--dataset-workspace-id`: with neither
`--dataset-workspace-id` nor `--workspace-id`/`FABRIC_WORKSPACE_ID` set, the
workspace resolves from `--env` via `environments.yml` instead. With no
workspace from any of those sources it refuses (exit `2`) before any network
call; a workspace with no semantic models, or none with dependent reports,
exits `0` with a notice.

```bash
fab-test playwright --dataset-workspace-id aaaaaaaa-bbbb-cccc-dddd-ffffffffffff
```

**`--dataset-workspace-id` with a bare `--artifact NAME` (or a target) and no
`--dataset-id` refines by what `NAME` turns out to be.** With no local match
under `--artifact-dir`, `NAME` is resolved against Fabric in that workspace:
a `SemanticModel` runs that one dataset's dependents (dataset-targeted mode,
above, named by display name instead of `--dataset-id`); anything else
resolves as a normal single-report target, with the workspace stashed as a
fallback so nothing else needs to name it. A report that *does* exist
locally is left alone -- this Fabric-side lookup is a last resort, never run
ahead of ordinary discovery.

```bash
# "Sales Model" is a dataset in this workspace: runs its dependent reports
fab-test playwright --dataset-workspace-id aaaaaaaa-bbbb-cccc-dddd-ffffffffffff \
  --artifact "Sales Model"

# "Invoice RDL" is not a dataset: refines to that one report
fab-test playwright --dataset-workspace-id aaaaaaaa-bbbb-cccc-dddd-ffffffffffff \
  --artifact "Invoice RDL"
```

Pairing `--dataset-workspace-id` with `--dataset-id`, `--impact-manifest`, or
a report that already has a local folder is unaffected by either of the two
behaviors above:

```bash
# A checked-in .rdl file resolves both the dataset and its workspace on its own
fab-test playwright --artifact "Invoice RDL" --env dev

# Forced explicitly, for a report with nothing checked in locally
fab-test playwright --artifact "Invoice RDL" --env dev \
  --dataset-id 66666666-7777-8888-9999-000000000000 \
  --dataset-workspace-id "Sales Dev"
```

**A paginated report is a flat `NAME.rdl` file, discovered the same way
`NAME.Report` folders are.** `fab-test playwright` with no `--artifact` scans
for both, so a repository with a mix of interactive and paginated reports
validates all of them in one batch run, and each subprocess is told its type
directly from the file/folder actually found -- never a global setting, which
could never correctly describe a repository containing both.

**`--artifact NAME --env ENV` also resolves live even with no matching local
file at all.** The local file/folder is never read for playwright's own
validation (it validates the *deployed* report, never local content) --
discovery only used it to find something to dispatch against, so a purely
remote report with nothing checked in locally used to be silently
undiscoverable through the real CLI (previously working only by coincidence
when a same-named local folder happened to exist). `fab-test playwright` now
falls back to resolving the named target live whenever local discovery finds
nothing and an environment was given; a real filesystem path
(`./src/Sales.Report`) is unaffected -- naming a specific location and finding
nothing there is still a real miss, not a service-resolution signal.

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

When [`resolve_item`](../../../../src/fab_test/scripts/playwright_validation/resolver.py)
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

Browser setup -- `pytest`, `pytest-playwright`, and `pytest-html` are dev-only dependencies of this project, so a `pip install cft-fab-test` consumer needs all three installed separately (plus `pytest-xdist`, needed the moment more than one case runs, which is the default for any report with more than one page):

```bash
playwright install chromium
pip install pytest pytest-playwright pytest-html pytest-xdist
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
  "fab_test_all": ["bpa", "pbir", "pql_test", "rdl"]
}
```

`playwright` and `a11y` are excluded from `fab-test all` by default but remain available as direct subcommands.

Accepts the union of flags from `bpa`, `pbir`, `pql-test`, and `rdl`, plus `--playwright-env-file` for Playwright support.

```bash
fab-test all \
  --tabular-editor-path "C:\..." \
  --env DEV \
  --playwright-env-file .env
```

After all analyzers finish, `fab-test all` prints an aggregate summary table showing analyzer, artifact, status, errors, warnings, and output path, plus total errors and warnings across the run.
