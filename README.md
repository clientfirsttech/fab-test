# fab-test

<p align="center">
  <img src="https://github.com/clientfirsttech/fab-test/blob/main/docs/images/fab-test-logo.png?raw=true" alt="fab-test logo" width="400">
</p>

**The Power BI tooling ecosystem is scattered: Tabular Editor's BPA, PBIR Inspector, DAX tests, Playwright, each with its own install, its own invocation, its own output format.** `fab-test` brings them together behind one CLI and one result contract, so it doesn't matter who's asking: a developer running a quick local check, a CI/CD build agent gating a deployment, or an AI coding agent that needs a single command and a machine-readable verdict it can act on. Point it at a `.pbip`-format artifact and get the same validation everywhere: Best Practice Analyzer rules, PBIR report structure, DAX tests, and rendered-report checks, all through one command with a pass/fail answer trustworthy for human and machine alike.

## Install

The package is **`cft-fab-test`**; the command it installs is **`fab-test`**.
PyPI refuses the name `fab-test` as too similar to the unrelated
[`fabtest`](https://pypi.org/project/fabtest/), so only the distribution name
carries the prefix -- the console script, the `fab_test` import package, and
every command in this README are unchanged.

### From PyPI (beta)

The current release is the beta `1.9.0b10`. pip skips pre-releases unless you
pass `--pre` or name the version, so a bare `pip install cft-fab-test` finds
nothing until the first final release.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install --pre cft-fab-test          # or pin it: "cft-fab-test==1.9.0b10"

fab-test --version
```

In a pipeline, pin the exact version rather than `--pre`: `--pre` also lets
pre-releases of *dependencies* in, not only this package.

New here? [docs/GETTING-STARTED.md](https://github.com/clientfirsttech/fab-test/blob/main/docs/GETTING-STARTED.md)
walks from a fresh install through `fab-test init`, a service principal created
with the Azure CLI (API permissions, client secret saved to `.fab-test/.env`,
workspace roles), to a first `fab-test playwright` run from the console.

### From source in editable mode (developers)

Editable mode links the package source into the active environment so code changes are reflected immediately.

```bash
git clone https://github.com/clientfirsttech/fab-test.git
cd fab-test
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

To contribute, install the dev extras and the git hooks. The pre-commit hook runs [gitleaks](https://github.com/gitleaks/gitleaks) and blocks any commit whose staged changes contain a secret:

```bash
pip install -e ".[dev]"
pre-commit install
```

Then create your own `fab-test.yml` at the repo root. It is gitignored: it
holds per-contributor values, such as the UPN `fab-test playwright` uses for
RLS embed tokens, that must never be committed.

```bash
fab-test init            # scaffolds a commented fab-test.yml (and .fab-test/.env.example)
```

Uncomment only what you need. For the Playwright RLS tests, set
`playwright_user_name` to a user in your own dev tenant (or export
`PLAYWRIGHT_USER_NAME` instead, which wins over the file). Run
`fab-test config --show` to confirm what is in effect.

### From a locally built wheel

Build the wheel into `dist/`:

```bash
pip install build
python -m build
```

Create a fresh virtual environment, activate it, and install the wheel:

```bash
python -m venv .venv-test
source .venv-test/bin/activate  # Windows: .venv-test\Scripts\activate
pip install dist/cft_fab_test-*.whl
```

Verify the console scripts are registered:

```bash
fab-test --help
```

## Assumed project format

`fab-test` assumes your Power BI content is saved as a **PBIP** project, with the semantic model in **TMDL** and the report in **PBIR** (the enhanced report format):

```
Sales.pbip
Sales.SemanticModel/
  definition/
    model.tmdl
    tables/*.tmdl
Sales.Report/
  definition.pbir
  definition/
    pages/pages.json
```

### Where fab-test looks

Discovery starts at the directory you run the command in and walks down.
A folder is an artifact because its name ends in a Fabric type suffix:
`Sales.SemanticModel`, `Sales.Report`, at any depth, whether or not a
`.pbip` sits beside it. That last part matters for artifacts committed for
CI rather than opened in Desktop: `deployed/Sales.SemanticModel` on its own
is found.

The suffixes come from [`artifact-map.json`](https://github.com/clientfirsttech/fab-test/blob/main/src/fab_test/metadata/artifact-map.json),
packaged with the distribution so an install outside this repository knows
what an artifact looks like. A `.fab-test/metadata/artifact-map.json` (or
the legacy `.github/metadata/artifact-map.json`) overrides it when present.

Skipped while walking: nested git checkouts (worktrees, vendored clones),
`.venv`, `node_modules`, `__pycache__`, `dist`, `build`, `.github`, `.claude`,
and the run's own `--output-dir`. `.github` and `.claude` hold agent
tooling -- skill instructions, worked examples, worktrees -- not this
project's own artifacts, so a suffix-matching folder placed there for
documentation purposes is never mistaken for one to test. Without those
exclusions a scan of this repository returns eight artifacts where three
are real.

One consequence is worth knowing: run `fab-test` from a folder that holds
*repositories* rather than artifacts and it finds nothing, because every
candidate below it is a nested checkout. It tells you so and names the fix:
`cd` into a repository, or point at one:

```console
$ fab-test pbir
  ⚠ fab-test pbir: no *.Report artifacts found under C:\Users\jkers\Git
    9 git checkouts below this root were skipped; a scan does not
    descend into a nested repository. cd into one, or name it directly:
      --artifact-dir C:\Users\jkers\Git\fab-test
```

**If you already have a `fabric-artifacts/` layout, nothing you do needs to
change.** That directory sits inside your working directory, so everything
found before is still found. `--artifact-dir` still narrows the search when
you pass it, and still exits `2` if the path you name does not exist. (Named
`fabric-artifacts`, not `.fabric/artifacts` — a dot-prefixed folder can't
sync through Fabric Git Integration.)

Every analyzer is built on that assumption:

| Analyzer | Discovers | Reads on disk | Format it requires |
|----------|-----------|---------------|--------------------|
| `bpa` ([Tabular Editor](https://github.com/TabularEditor/TabularEditor)) | `*.SemanticModel` | `definition/` | TMDL |
| `pql-test` ([PQL.Assert](https://github.com/clientfirsttech/PQL.Assert)) | `*.SemanticModel` | `definition/` | TMDL |
| `pbir` ([PBIR Inspector](https://github.com/NatVanG/fab-inspector)) | `*.Report` | `definition/` | PBIR |
| `a11y` ([pbir-a11y](https://github.com/Juls-BI/pbir-a11y)) | `*.Report` | `definition/` | PBIR |
| `playwright` | `*.Report` | none (renders the deployed report) | folder naming only |

Deployment and dependency discovery read the report's `definition.pbir` to resolve which semantic model it points at, so that file is what pairs a report with its model.

Power BI Desktop writes this layout when you **Save as** a `.pbip` project with the TMDL and enhanced report format (PBIR) options turned on, under **File → Options and settings → Options → Preview features** in the versions where they are still preview.

Discovery matches on folder suffix (`*.SemanticModel`, `*.Report`), not on folder contents, so a project saved in the legacy format is still picked up; it fails inside the analyzer that cannot read it rather than being reported as an unsupported format. A bare `.pbix` is not a supported input at all.

## Run manual tests locally

### Local Desktop workflow (no cloud required)

The fastest path to real findings: a `.pbip` open in Power BI Desktop, no `fabric-artifacts` layout, no Fabric workspace, no service principal. The project has to be saved in TMDL and PBIR; see [Assumed project format](#assumed-project-format).

```bash
fab-test doctor --local     # what's ready, and what fab-test local will run
fab-test local --dry-run    # see the plan first
fab-test local              # BPA, PBIR Inspector, and Desktop-bound pql-test
```

A missing prerequisite (e.g. `pqlint` not installed) is reported as skipped with a remediation hint, not a failure. Likewise, if Power BI Desktop is not open, `pql-test` cannot reach the model and no DAX tests execute — that artifact reports `warning` with zero counts and exits 0, rather than a misleading `failed` or a green `passed` over a run in which nothing happened. See [`docs/QUICKSTART-LOCAL.md`](https://github.com/clientfirsttech/fab-test/blob/main/docs/QUICKSTART-LOCAL.md) for the full walkthrough.

### Wrapper contract tests with pytest

`pytest` exercises the analyzer wrappers without requiring external tools such as Tabular Editor or Power BI Desktop. To run the contract tests against the installed wheel, stay in the repository root and run the following inside the same virtual environment:

```bash
# Windows
.venv-test\Scripts\activate
# macOS/Linux
# source .venv-test/bin/activate

pip install pytest
pytest
```

To run a subset of tests by marker:

```bash
pytest -m fab_test
pytest -m analyzers
```

> **Note:** Some wrapper contract tests launch the installed console scripts (`tabular-editor-bpa`, `fab-test`, etc.) as subprocesses. Those scripts must be on `PATH`, so always activate the virtual environment before running `pytest`.

### Artifact validation with fab-test

`fab-test` discovers artifacts under your working directory, in the TMDL/PBIR layout described in [Assumed project format](#assumed-project-format). It requires the corresponding external tools for each analyzer.

```bash
# Discover which artifacts would be analyzed
fab-test bpa --dry-run

# Run BPA against SemanticModel artifacts
fab-test bpa --tabular-editor-path "/path/to/TabularEditor.exe"

# Run PBIR Inspector against Report artifacts
fab-test pbir --inspector-path "/path/to/PBIRInspectorCLI"

# Run pbir-a11y accessibility checks against Report artifacts (requires
# Node.js >= 18 and npm the first time -- it's built from source, then
# cached; see fab-test doctor --analyzer a11y). Not run by `fab-test all`
# by default -- add "a11y" to fab_test_all in analyzers.json to opt in.
fab-test a11y

# Run the active (fixture-verified) rules against paginated (.rdl) reports -- pure Python,
# no external tool, always ready. Included in `fab-test all` by default.
# Every rule and its source links: docs/RDL-RULES.md
# --verbose adds a findings table; each finding names its path (Dataset › Field)
# and quotes the query or expression that broke the rule.
fab-test rdl

# Run pql-test DAX tests
fab-test pql-test --env DEV

# Run Playwright visual validation (always needs a service principal --
# see "Playwright: the minimal working config" below)
fab-test playwright --artifact "Not Working Visuals" --env dev --env-file .env

# Test only the reports built on one dataset (looked up live in the
# dataset's workspace and, if set, the --workspace workspace)
fab-test playwright --dataset-id <DATASET_GUID> --dataset-workspace-id <WORKSPACE_GUID>

# Discover reports that depend on a deployed semantic model
fab-test dependencies --semantic-model SalesModel --env dev --env-file .env
```

### Keep the output short: `-q`

A default run explains itself for a person: a banner, a result line, and a summary per artifact. When you only need to know whether it passed (an AI agent in an edit loop, a busy CI log), add `-q`:

```console
$ fab-test bpa -q
bpa warning e=0 w=25 fab-test-results/bpa/Report with Bookmarks - Broken Visuals/envelope.json
bpa warning e=0 w=103 fab-test-results/bpa/SampleModel-PQLAssert/envelope.json
$ fab-test rdl -q
rdl failed e=3 w=3 fab-test-results/rdl/QRY-02/envelope.json
```

One line per artifact: `<analyzer> <status> e=<errors> w=<warnings> <where>`, where `<where>` is the envelope with the findings. Exit codes and every file under `fab-test-results/` are unchanged, and a failure still says why: a missing credential, a timeout, or a crash prints its message above the lines.

| Command | Before | Default now | `-q` |
|---------|-------:|------------:|-----:|
| `fab-test bpa` | 2,569 chars | 1,935 | 176 |
| `fab-test pbir` | 5,195 | 3,043 | 324 |
| `fab-test a11y` | 4,089 | 2,901 | 320 |
| `fab-test pql-test` | 2,086 | 1,678 | 193 |
| `fab-test local` | 9,850 | 6,656 | 693 |

*Measured against this repository's four sample artifacts.* Default output got shorter too: each path is named once, and the Rules and Tool paths (the same for every artifact, and already in the envelope) appear only with `-v`.

To make a repository terse for everyone who runs it, pin the level once instead of passing a flag:

```yaml
# fab-test.yml
verbosity: summary      # summary | default | verbose | debug
```

A flag beats the environment variable (`ANALYZER_VERBOSITY`), which beats the file, so `fab-test bpa -v` still gives you the full output for one run. `-q` and `-v` together exit `2`. See [Output Verbosity](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/references/operations.md#output-verbosity) for the levels.

### Playwright: the minimal working config

Every other analyzer can fall back to `az login`; `playwright` cannot --
generating an embed token always calls MSAL with a service-principal secret,
so it refuses immediately (exit `127`) and names every missing variable
rather than authenticating partway and failing on the embed-token call.
`fab-test doctor` reports it as not ready for the same reason, so it never
shows a false green for a developer who is only signed in with `az login`.

With a service principal set, a workspace resolves without `environments.yml`
from any of -- in this order -- `--workspace` (preferred; `--workspace-id` and
`--from-workspace` are accepted aliases for the same name-or-GUID value),
`FABRIC_WORKSPACE_ID`, or `workspace:` in `fab-test.yml`. No `fab-test.yml` is
required at all:

```bash
fab-test playwright --artifact "Not Working Visuals" --workspace "Sales Dev"
# or
FABRIC_WORKSPACE_ID="Sales Dev" fab-test playwright --artifact "Not Working Visuals"
```

A bare `--workspace` with no `--artifact`/target and no explicit
`--artifact-dir` tests every deployed Report and PaginatedReport in that
workspace instead of scanning the repository -- so the run needs no checkout
at all. `--workspace-id`/`--from-workspace` trigger the identical behavior;
an ambient `FABRIC_WORKSPACE_ID` alone (no `--workspace` on the command line)
keeps today's repository discovery:

```bash
fab-test playwright --workspace "Sales Dev"
```

Add `--changed-since REF` to test only the deployed reports your change
touches: the reports built on a semantic model changed since that Git branch,
tag or commit, or the reports themselves -- interactive or paginated (a changed
`.PaginatedReport` folder or loose `.rdl` file). Uncommitted and new artifact
folders count. Nothing changed, or nothing deployed affected, exits 0:

```bash
fab-test playwright --workspace "Sales Dev" --changed-since main
```

A repository that already pins its workspace in committed config can rely on
`fab-test.yml` instead and drop the flag/env var entirely:

```yaml
# fab-test.yml
workspace: Sales Dev      # name or GUID -- also discoverable via `fab-test config --show`
environment: dev
```

```bash
fab-test playwright --artifact "Not Working Visuals"
```

`environments.yml` is only consulted when no workspace resolves from
`--workspace` (or its `--workspace-id`/`--from-workspace` aliases),
`FABRIC_WORKSPACE_ID`, or `workspace:` in `fab-test.yml` --
a repository that already pins its workspace there keeps working unchanged.

A run with 5 report x page x bookmark cases and 1 real failure now says so:
`envelope.json`'s `test_results` carries one row per case with that case's own
real outcome, so `findings` names only the case that actually failed instead of
tagging all 5 identically. Each row also points at that case's own evidence
(`fab-test-results/playwright/<report>/test-cases/<case>/screenshot.png`, plus
`console.json`/`network.json` when there's something to capture) and links
straight back to the report page/bookmark it validated on `app.powerbi.com`;
`--report` renders both as links right in the table, and the same paths are in
`envelope.json` for a script or an agent to open directly.

A render timeout or a broken visual now names the real cause. A failed race
between Power BI's `rendered` and `error` events writes that case's full SDK
event history to `event_log.json`, and a timeout with no event at all falls
back to scanning the embedded frame for Power BI's own error panel, writing
any text it finds to `embed_error_details.txt` and folding it into the
failure message -- so `envelope.json` names a permissions/token-scope problem
instead of restating "did not render within 180000ms".

**Running this in CI** is a separate setup from the local config above --
service principal registration, tenant settings, workspace role, and the
GitHub Environment/secrets a workflow reads. See
[docs/PLAYWRIGHT-CI.md](https://github.com/clientfirsttech/fab-test/blob/main/docs/PLAYWRIGHT-CI.md)
for the full walkthrough and
[docs/examples/github-actions/playwright-live.yml](https://github.com/clientfirsttech/fab-test/blob/main/docs/examples/github-actions/playwright-live.yml)
for a copy-ready workflow.

**Showing the browser for a demonstration.** Browsers are hidden by default. Add
`--headed` to watch the local windows, and `--slow-mo 500` to pause 500 ms between
actions so an audience can follow. Use one worker so windows open one at a time:

```bash
fab-test playwright --artifact "Not Working Visuals" --env DEV --headed --slow-mo 500 --workers 1
```

The same settings live in [docs/examples/playwright/headed.yml](https://github.com/clientfirsttech/fab-test/blob/main/docs/examples/playwright/headed.yml)
for `--playwright-config`. Setting `PLAYWRIGHT_HEADLESS=false` (environment or `.env`) also shows the
window; a YAML `launch.headless` or `--headed` takes precedence. These apply to local browsers only; on Azure-hosted
browsers there is no local window, so they are ignored with a warning.

**Optional Azure-hosted browsers** keep Python Playwright and pytest on the
invoking machine while moving browsers to Azure. Select a credential-free
YAML file with `--playwright-config`; omitting it keeps local execution:

```bash
fab-test playwright --artifact "Not Working Visuals" --env DEV \
  --playwright-config docs/examples/playwright/azure.yml --workers 8 --report
```

Store `PLAYWRIGHT_SERVICE_URL` and `PLAYWRIGHT_SERVICE_ACCESS_TOKEN` in the
gitignored `.fab-test/.env` or the process environment, separately from Fabric
embedding credentials. See [Azure browser setup](https://github.com/clientfirsttech/fab-test/blob/main/docs/PLAYWRIGHT-CI.md#azure-hosted-browsers)
for supported settings, token authentication, and Python-only GitHub Actions
and Azure DevOps examples. More workers parallelize cases within one report,
not reports; service limits still apply.

### Playwright tests every page, bookmark, and role by default

`fab-test playwright` discovers a report's pages, each page's own bookmarks,
and (when RLS is in play) the semantic model's roles, and tests the full
matrix, not just whichever tab opens first. It expands to one case per page,
plus one per that page's *own* bookmark, repeated once per role -- a report
with 2 pages, 1 bookmark on the first and 2 on the second, under 2 roles, is
10 cases. Discovery needs the full
permission set in
[docs/PLAYWRIGHT-CI.md](https://github.com/clientfirsttech/fab-test/blob/main/docs/PLAYWRIGHT-CI.md#1-register-the-service-principal)
on the service principal in addition to what embedding already required; a
missing grant logs a warning and falls back to testing the one default page
rather than failing the run. Turn a dimension off with `--pages none` /
`--roles none`:

```bash
# Every page, every page's bookmarks, every role
fab-test playwright --artifact "Not Working Visuals" --env dev

# Only the default page/role, matching every prior release
fab-test playwright --artifact "Not Working Visuals" --env dev --pages none --roles none

# See the matrix without rendering it: writes test-cases.csv/json and exits 0,
# minting no embed token and launching no browser
fab-test playwright --artifact "Not Working Visuals" --env dev --plan-only
```

Role discovery needs an effective-identity user to embed with. Declare it once
in `fab-test.yml` instead of setting `PLAYWRIGHT_USER_NAME` per run:

```yaml
playwright_user_name: analyst@contoso.com
```

With a user configured, an RLS-secured model's roles are discovered and tested
under one embed token each. `PLAYWRIGHT_USER_NAME` still wins over the file, and
a case with no role embeds with no identity at all.

### Validating a paginated (RDL) report

A Power BI paginated report has no page/bookmark dimension and doesn't fire the
interactive embed SDK's render events, so it's tested differently -- but you
don't need to declare any of that up front. `fab-test playwright` figures out
which kind of report a target is itself: a local `NAME.rdl` file (a paginated
report's real local artifact shape -- a flat file, not a folder) is discovered
alongside `NAME.Report` folders, and `--artifact NAME --env ENV` with no local
match tries Fabric's `Report` item type first, then `PaginatedReport`, using
whichever actually matches the name. If the report is bound to a Power BI
dataset, its dataset ID and workspace are read straight out of the `.rdl`
file's own `<DataSources>` block -- or, for a report that exists only in the
workspace, from the report's own data sources -- so there is no GUID to look up
and supply by hand.

```bash
fab-test playwright --artifact "Invoice RDL" --env dev --env-file .env
```

A report that declares parameters is tested twice: once with no parameters,
and once with a real parameter set applied at embed time -- the first valid
value of each single-value parameter and the first two of each multi-value
one. The valid values are read the way the report itself reads them: a static
list straight from the `.rdl`, or the parameter's own dataset query run against
the report's dataset. That query needs the tenant's **Dataset Execute Queries
REST API** setting to allow the service principal; without it, the report is
tested with no parameters and a warning names the setting. Each case's row in
`test_results` carries a `parameters` field, empty on the no-parameter case, so
a failure names the values that caused it.

`--report-type {report,paginated}` (or `PLAYWRIGHT_REPORT_TYPE`) forces it
explicitly, for the rare case you need to -- never required for `--artifact`
or local discovery. See [the fab-test skill's playwright flags reference](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/references/flags.md) for the full behavior.

### Naming what to test

Every analyzer subcommand takes an optional target. Omit it and `fab-test` discovers everything matching, as before. The grammar is the one `pql-test` and the Fabric CLI already use, so a target pasted from either works here unchanged.

| Target | Means |
|--------|-------|
| *(omitted)* | Discover every matching artifact under `--artifact-dir` (default: the working directory) |
| `Sales` | The artifact named `Sales`; the analyzer's own glob picks the type |
| `Sales.SemanticModel` | That name **and** type; `Sales.Report` is not selected |
| `./src/Sales.SemanticModel` | Exactly that folder, wherever it lives (not confined to `--artifact-dir`) |
| `local/Sales` | The copy open in a running Power BI Desktop instance |
| `"Sales Dev.Workspace/Sales.SemanticModel"` | A deployed item in the named Fabric workspace |

```bash
fab-test bpa Sales.SemanticModel                          # one artifact, by name and type
fab-test pql-test local/Sales                             # bind to Power BI Desktop
fab-test pql-test "Sales Dev.Workspace/Sales.SemanticModel"   # a deployed model
fab-test all local/Sales                                  # everything that can run locally
```

Not every analyzer accepts every form. Run `fab-test list` for the Scopes column, and see the [targeting reference](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/references/targeting-and-discovery.md#targeting) for the rules. `--artifact STEM` still works as a deprecated alias.

### Testing what's deployed

`bpa`, `pbir`, `a11y`, and `rdl` can test what is deployed in a workspace instead of what is on disk. They export each item's definition read-only, analyze it like a local folder, and delete the export afterwards. `pql-test` connects to the deployed model directly and downloads nothing.

```bash
fab-test bpa "Sales Dev.Workspace/Sales.SemanticModel"   # one deployed model
fab-test bpa "Sales Dev.Workspace/Sales"                 # untyped: resolved as the analyzer's own type
fab-test pbir --workspace "Sales Dev"                    # every deployed report; local folders are ignored
fab-test all --workspace "Sales Dev"                     # bpa, pbir, pql-test and rdl over deployed items
```

The target decides the mode, and every run says which it chose on its first line: `mode=service workspace=Sales Dev source=target`. `workspace:` in `fab-test.yml` and `FABRIC_WORKSPACE_ID` only supply a default; they never turn a bare `fab-test bpa` into a service run.

- **Credentials** come from the chain under [Credentials](#credentials): a service principal, then an ambient `az login`. A rejected token (HTTP 401) names `az login --tenant`; a missing permission (403) names the access the identity needs.
- **`--keep-export`** keeps the redacted definitions under `fab-test-results/export/<item id>/<Item>.<Type>/` instead of deleting them.
- **More than 50 items** of one type stops with exit `2` naming `--all`; pass `--all` to proceed.
- **One item that cannot be exported** (a PBIR-Legacy report, a missing permission) is named and fails the run; the others are still tested.

For CI, copy [docs/examples/github-actions/service-mode.yml](https://github.com/clientfirsttech/fab-test/blob/main/docs/examples/github-actions/service-mode.yml).

### Credentials

**`fab-test` stores no credentials**: no token, no cache, no credential file. It reads what your environment already provides and delegates sign-in to the tool that owns the credential, so there is no `fab-test` token cache to look for.

```bash
fab-test auth status        # which identity would be used, verified for real
fab-test auth login         # delegates to `pql-test auth login`
```

`auth status` resolves in the same order that actually authenticates: environment variables, then `.env`, then an ambient Azure credential (`az login`, managed identity, VS Code sign-in). It exits `0` when verified, `127` when nothing resolves, and `1` when credentials work but a named workspace is unreachable.

`fab-test doctor` uses the same chain but never acquires a token, so it reports an ambient credential as `unverified` and points at `auth status`. That is expected.

> `--env` is the test environment label (`DEV`, `PROD`). `--cloud`, on `auth login` only, selects the Azure cloud. They are deliberately different names.

### Readable reports

The result envelopes are the machine contract. To see *what actually failed* without reading JSON, ask for a report:

```bash
fab-test all --report
```

Reports are **opt-in**: nothing is written without the flag, so no existing run gets slower. Add `report: true` to `fab-test.yml` to turn them on for good.

Each artifact gets a self-contained HTML page beside its envelope, and `fab-test all --report` also writes `fab-test-results/index.html` linking them all, so one run means one page to open:

```
  ╭────────────┬───────────────────────┬──────────┬───────┬────────╮
  │ Analyzer   │ Artifact              │ Status   │   Err │   Warn │
  ├────────────┼───────────────────────┼──────────┼───────┼────────┤
  │ pbir       │ SampleModel-PQLAssert │ FAILED   │     4 │      1 │
  │ bpa        │ SampleModel-PQLAssert │ warning  │     0 │     21 │
  ╰────────────┴───────────────────────┴──────────┴───────┴────────╯

  pbir/SampleModel-PQLAssert
    fab-test-results/pbir/SampleModel-PQLAssert/native.json/TestRun.html
  bpa/SampleModel-PQLAssert
    fab-test-results/bpa/SampleModel-PQLAssert/report.html

  Index:  fab-test-results/index.html
```

PBIR Inspector writes its own `TestRun.html` and it appears **with or without** `--report`; it is richer than anything generated from the envelope, so `fab-test` never overwrites it. Two upstream asset paths in it are repaired in place, both by inlining as base64 so nothing 404s once the report is copied out of the tool's install directory: the favicon link, and every per-object screenshot. Tabular Editor emits TRX and `pql-test` emits JSON, so those two get a generated `report.html`.

Every analyzer's envelope also records **every test conducted, not only the failures**: pass, fail, warning, and skip. The two generated reports show that as a table with an All / Errors / Warnings / Passed filter, so a passing run no longer reads as an empty page; PBIR Inspector's own report keeps its own UI, so for that one the full list is there for telemetry to read rather than for the filter to show.

That table also has a **search box and sortable column headers**: type to narrow to a rule, test, or object by name, or click a header to sort by that column (click again to reverse); the sorted column shows a ▲/▼ arrow so it's obvious which column and direction is active, and the arrow moves to whichever column you click next. Both work together with the status filter. The report stays fully offline and self-contained; the small script behind search and sort never fetches or links to anything outside the page itself.

The index also shows when the run happened and, in CI, who ran it and from which branch/commit (falling back to local `git`, or an em-dash outside a git checkout).

Running locally and don't want to go find the file? Add `--open-report` and it opens in your default browser when the run finishes:

```bash
fab-test bpa --open-report
```

`--open-report` implies `--report`, so you never have to pass both. This is a local convenience for a human at a terminal, not something to add to a pipeline YAML: it is automatically suppressed under CI, falling back to just printing the path.

Status and non-zero counts are coloured in a terminal. Colour is off when output is redirected, off whenever `NO_COLOR` is set, and never present under `--format json`.

### The machine-readable workflow (agents and pipelines)

`fab-test` is designed to be called the same way by a human, a CI pipeline, or an AI agent. The four-command loop:

```bash
fab-test doctor --format json          # 1. is each analyzer's tool/credential ready?
fab-test list --format json            # 2. what subcommands exist, and how many artifacts match?
fab-test bpa --format json             # 3. run it; stdout is exactly one JSON document
cat fab-test-results/run.json          # 4. read the manifest instead of globbing result dirs
```

`--format json` guarantees stdout carries nothing but the payload; narration goes to stderr. When a run fails, `run.json` says why without a second file: an artifact whose analyzer aborted before writing an envelope carries the remediation message in its `detail` field (`"Pass --env, set FABRIC_ENVIRONMENT, ..."`), so uploading the manifest alone is enough to diagnose a red build. See the [Agent Contract](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/SKILL.md#agent-contract) for exit codes, the JSON stdout guarantee, and the `run.json` schema.

Full CLI reference: [`.github/skills/fab-test/SKILL.md`](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/SKILL.md).

See [`docs/QUICK-VALIDATION.md`](https://github.com/clientfirsttech/fab-test/blob/main/docs/QUICK-VALIDATION.md) for a complete local build-and-test workflow, and [`docs/RELEASE.md`](https://github.com/clientfirsttech/fab-test/blob/main/docs/RELEASE.md) for how `fab-test` itself is published.

## Configuration

`fab-test.yml` at the repository root is an entirely optional config-file front door; no file at all means every setting behaves exactly as it always has.

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
| 4 (lowest) | Packaged default | `200` seconds |

`fab-test.yml` is meant to be committed; it holds no credentials, only settings and rule overlays (tune one BPA/PBIR Inspector rule without forking the packaged rules file). Credentials belong in a `.env` file (auto-discovered, gitignored) or a pipeline's own secrets store. See the [Configuration section of the fab-test skill](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/references/configuration.md#configuration) for the full settings list and rule-overlay keys.

### Telemetry (optional)

`fab-test` can ship each analyzer result to a Fabric Eventhouse and/or a Fabric
Lakehouse, so findings across runs, branches, and people land somewhere queryable.
The two destinations are independent — configure either, both, or neither — and
each is off until you give it an address; telemetry never fails a build, and one
destination failing to deliver never blocks the other.

**Configuring a destination is what turns it on**: there is no separate switch:

```yaml
# fab-test.yml
telemetry:
  eventhouse:
    uri: https://<cluster>.kusto.fabric.microsoft.com
    database: fabric_ops
  lakehouse:
    workspace: <workspace-name-or-guid>
    lakehouse: <lakehouse-name>
```

`fab-test init` scaffolds both blocks commented out, so they're discoverable in the generated `fab-test.yml` without reading these docs. Lakehouse telemetry writes one JSONL file per table per run to `Files/fab-test-telemetry/<table>/<run_id>.jsonl` via OneLake, reusing the same credentials as Eventhouse — no separate Lakehouse credential exists. Querying it means a SQL endpoint, Direct Lake, or Power BI, no KQL required.

`lakehouse:` accepts a friendly display name or the item's GUID — use the GUID if your tenant has OneLake friendly names disabled (the error looks like `FriendlyNameSupportDisabled`); `fab-test` detects which one you gave it automatically.

**The Lakehouse's "Load to Tables" wizard doesn't see these files** — it only recognizes CSV and Parquet, not JSON/JSONL. Load them with a Spark notebook instead: see [the fab-test skill's Telemetry reference](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/references/configuration.md#telemetry) for the two-line snippet.

**The tables create themselves on first use.** You need an Eventhouse and a KQL
database; `fab-test` builds the rest. Before each run's first send it checks that
its table and ingestion mapping exist, creates whatever is missing, and only then
ingests. A run against a healthy cluster issues no schema commands at all.

Each table holds a single `Data: dynamic` column, so downstream Eventhouse
functions own the transform and a new payload field is a new key rather than a
table alteration. `fabric_dynamic_analysis` receives `pql-test` records;
everything else goes to `fabric_static_analysis`.

If your credential may ingest but not create tables (a normal arrangement for a
governed cluster), the run says so and hands you the KQL to run yourself:

```kusto
.create-merge table fabric_static_analysis (Data: dynamic)
.create-or-alter table fabric_static_analysis ingestion json mapping 'fab_test_payload'
    '[{"column":"Data","path":"$","datatype":"dynamic"}]'
```

That mapping is not decoration. Without it Kusto maps by column name, finds
nothing called `analyzer` or `status`, and stores empty rows *successfully*, which
is why `fab-test` checks for it rather than assuming a table that exists is usable.

Three more things to know before the first run:

- **Install the extra for each destination you use.** Neither client ships in the
  base package: `pip install 'cft-fab-test[telemetry]'` for Eventhouse's Kusto ingest
  client, `pip install 'cft-fab-test[telemetry-lakehouse]'` for Lakehouse's OneLake
  client. Shipping egress-capable clients to everyone who only reads files on a
  laptop is not a default worth having.
- **Both reuse your existing credentials.** The same `FABRIC_TENANT_ID`,
  `FABRIC_SERVICE_PRINCIPAL_ID`, and `FABRIC_SERVICE_PRINCIPAL_SECRET` the
  analyzers use, falling back to `DefaultAzureCredential` (`az login`, a managed
  identity) when none are set. There are no `EVENTHOUSE_*`/`LAKEHOUSE_*` credential
  variables.
- **Grant the right role on each destination.** Eventhouse needs **Database
  Ingestor** on the KQL database; Lakehouse needs a workspace role (e.g.
  Contributor) or a direct share on the item. This is the most likely first-run
  failure and it looks exactly like a bad secret, so `fab-test doctor` names it per
  destination rather than letting you go rotate a working credential.

| You want | Do this |
|---|---|
| See where it would go, and what it would send | `fab-test bpa --dry-run` |
| Turn it off for one run | `fab-test bpa --no-telemetry` |
| Turn it off everywhere | `ENABLE_EVENTHOUSE_LOGGING=false` |
| Check readiness | `fab-test doctor` (the `telemetry-eventhouse`/`telemetry-lakehouse` rows) |
| Override the Eventhouse address per environment | `EVENTHOUSE_URI` / `EVENTHOUSE_DATABASE` |
| Override the Lakehouse address per environment | `LAKEHOUSE_WORKSPACE` / `LAKEHOUSE_NAME` |

`--telemetry` with neither destination configured is an error (exit `2`) naming
both config keys and both sets of environment variables, rather than a run that
quietly sends nothing. When a send fails, the run's own exit code is unchanged, one
warning is printed per failed destination for the whole run (not per artifact), and
`run.json` records the reason(s) in `telemetry_error`, so a pipeline that uploads
only the manifest can still tell a run whose telemetry landed from one whose
records were dropped. One destination failing never blocks the other's delivery.
Credential values never reach the payload, the log, or the manifest.

**What each record identifies.** `actor` carries the git email (`git config
user.email`, or `GITHUB_ACTOR` in a pipeline) as-is, so you can ask who ran what;
the same address the repository already stores on every commit. File paths are
recorded relative to the repository root, never absolute: an absolute path on a
laptop is `C:\Users\<name>\…`, which shipped the operating-system username in every
record until it was found by reading rows in a real Eventhouse. If you would rather
not record a person at all, unset `user.email` for the repository; an unresolvable
actor is stored as an empty string, not as a placeholder.

### Where metadata lives

Rulesets, the analyzer registry, the artifact map, and `environments.yml` all resolve the
same way: `.fab-test/metadata/` first, then `.github/metadata/`, then the copy packaged in
the wheel:

```
.fab-test/metadata/
  rules/BPARules.json                      <- your tuned BPA ruleset
  rules/pbi-inspector-custom-rules.json    <- your tuned PBIR ruleset
  analyzers.json                           <- analyzer definitions and tool install URLs
  artifact-map.json                        <- which folder suffixes are Fabric artifacts
  environments.yml                         <- workspaces and promotion chain
```

`.fab-test/metadata/` is the directory to create. `.github/metadata/` still resolves and is
kept only so existing repositories keep working; `.github/` belongs to GitHub, not to this
tool. Anything you don't override comes from the wheel, so a `pip install` works with no
metadata of your own at all.

`environments.yml` is the one exception: it has no packaged default, because a workspace GUID
baked into a release would aim a deployment at somewhere you never chose. If no layer supplies
it, the command fails and names both places you could put it.

### Tool versions

`analyzers.json`'s `tool_install.version` field pins each wrapped tool (Tabular Editor,
PBIR Inspector) to a specific release, and the download cache is keyed by that version, so
a newer pin in a `fab-test` upgrade downloads the new binary rather than silently reusing
whatever an older checkout had cached. `fab-test doctor` reports the resolved version
alongside each tool's readiness, and names the environment variable or file path
shadowing the pin if one is in play. See
[docs/RELEASE.md](https://github.com/clientfirsttech/fab-test/blob/main/docs/RELEASE.md#bumping-a-wrapped-tools-pin)
for the pin-bump procedure, and
[.github/workflows/check-tool-updates.yml](https://github.com/clientfirsttech/fab-test/blob/main/.github/workflows/check-tool-updates.yml)
for the weekly job that watches upstream for you.

## Usage

`fab-test` discovers and analyzes artifacts under your working directory. It is the local equivalent of the CI artifact validation gate. See the [Run manual tests locally](#run-manual-tests-locally) section above for common commands, and [`.github/skills/fab-test/SKILL.md`](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/SKILL.md) for the full CLI reference.

## AI agent guidance

The AIDD agent instructions and skills live in the repository, not in the wheel: [`.github/agents/`](https://github.com/clientfirsttech/fab-test/tree/main/.github/agents/) and [`.github/skills/`](https://github.com/clientfirsttech/fab-test/tree/main/.github/skills/). Clone the repository to get them. The `fab-test` CLI reference an agent needs is [`.github/skills/fab-test/SKILL.md`](https://github.com/clientfirsttech/fab-test/blob/main/.github/skills/fab-test/SKILL.md).

### The `fab-test` skill

Unlike the other repository-only skills, the `fab-test` CLI reference skill (`SKILL.md` plus `references/*.md`) is also packaged inside the wheel, so a plain `pip install cft-fab-test` -- no checkout, no clone -- can still hand it to an agent harness, and the copy it installs can never drift from the CLI version actually installed:

```bash
fab-test skill                    # list the main skill and its reference topics
fab-test skill fab-test           # print the resolved main SKILL.md
fab-test skill flags              # print one reference topic (e.g. flags, credentials)

fab-test skill --install claude   # write .claude/skills/fab-test/ (SKILL.md + references/)
fab-test skill --install copilot  # write .github/instructions/fab-test/ (Copilot's applyTo shape)
fab-test skill --show             # report install state for every known harness
fab-test skill --install claude --uninstall   # remove a directory this command created
```

A repo-level override (`.fab-test/skill/SKILL.md` or `.github/skills/fab-test/SKILL.md`) is resolved ahead of the packaged copy when present, so a fork can customize the skill without patching the wheel. `--install` is idempotent and never clobbers a differing local copy without `--force`; `--dry-run` reports the plan first.

What the distribution *does* carry is the metadata the analyzers need, so `bpa`, `pbir`, and `doctor` work from a plain `pip install` with no checkout:

```python
import importlib.resources as resources

metadata = resources.files("fab_test").joinpath("metadata")
print(metadata.joinpath("rules/BPARules.json"))  # packaged BPA ruleset
print(metadata.joinpath("analyzers.json"))       # tool install URLs doctor reads
```

## License

MIT. See [LICENSE](https://github.com/clientfirsttech/fab-test/blob/main/LICENSE).

`fab-test` wraps, but does not redistribute, several external tools it
downloads or builds at runtime — Tabular Editor 2, fab-inspector, and
pbir-a11y (the latter under the source-available PolyForm Shield 1.0.0
license, not MIT). See
[THIRD-PARTY.md](https://github.com/clientfirsttech/fab-test/blob/main/THIRD-PARTY.md)
for what each permits.
