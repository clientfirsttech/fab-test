---
name: fab-test
description: fab-test CLI reference for running Fabric artifact analyzers locally (fab-test 1.0.0.0.dev15). Covers all subcommands, flags, artifact isolation, result locations, and how fab-test differs from pytest. Use when invoking, troubleshooting, or extending local artifact validation.
---

# fab-test

`fab-test` discovers and analyzes Fabric artifacts under your working directory — the local equivalent of the CI artifact validation gate.
It is **not** `pytest`. Use `pytest` to test the analyzer wrappers; use `fab-test` to test your actual artifacts.

Entry point: `scripts/fab_test.py` (installed as `fab-test` console script via `pip install -e .`).

## Assumed artifact format

Every analyzer assumes PBIP-format content: the semantic model serialized as **TMDL** (`*.SemanticModel/definition/**/*.tmdl`) and the report as **PBIR**, the enhanced report format (`*.Report/definition.pbir` plus `*.Report/definition/pages/`). Tabular Editor's BPA is handed the model's `definition/` folder; PBIR Inspector is handed the `.Report` folder.

Discovery matches on folder suffix (`*.SemanticModel`, `*.Report`), never on contents, so a legacy-format folder is still discovered — it surfaces as the analyzer's own failure, not as an "unsupported format" skip. A bare `.pbix` is not an input.

## Distinction from pytest

| Command | What it tests |
|---------|---------------|
| `pytest -m bpa` | Is the BPA wrapper code correct? (always green, no tools needed) |
| `fab-test bpa` | Do my `.fabric` artifacts pass BPA rules? (requires Tabular Editor) |
| `pytest -m pbir` | Is the PBIR wrapper code correct? (always green, no binary needed) |
| `fab-test pbir` | Do my reports pass PBIR Inspector rules? (requires PBIR Inspector binary) |
| `pytest -m pql_test` | Is the pql-test wrapper code correct? (mocked, always green) |
| `fab-test pql-test` | Do my semantic model DAX tests pass? (requires Power BI Desktop open) |
| `pytest -m playwright` | Is the Playwright wrapper code correct? (mocked contract tests) |
| `fab-test playwright` | Do my Power BI reports render without visual-load errors? (requires service-principal credentials) |

## Installation

From a checkout:

```bash
pip install -e .
```

From an index — **`pip install fab-test` does not work yet.** The name is
unregistered on PyPI. The pre-release lives on TestPyPI, and both flags below are
required: TestPyPI carries `pql-test` 0.1.11 and `fabric-cicd` 0.1.7 where this
project needs `pql-test==0.1.12` and a current `fabric-cicd`, so without the
extra index the install fails to resolve; and pip skips PEP 440 dev releases
unless the version is named exactly.

```bash
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  "fab-test==1.0.0.0.dev1"
```

Either way this registers the `fab-test` console script. The `.venv` is searched automatically for tool binaries (e.g. `pql-test`) even when not on `PATH`.

Rules and metadata resolve in the same layer order however `fab-test` was
installed: `.fab-test/metadata/` first, then `.github/metadata/` (legacy,
for consumer repositories already on that layout — this repository no
longer keeps a copy there), then the copy packaged in the wheel — except
`environments.yml`, which has no packaged fallback by design and lives at
`.fab-test/metadata/environments.yml` in this repository. `fab-test config
--show` names the layer each file came from.
Release and publishing procedure: [`docs/RELEASE.md`](../../../docs/RELEASE.md).

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

Plain `fab-test doctor --format json` gives every analyzer entry the same five
keys, `version` included — `null` for an analyzer with no wrapped tool of its
own (`pql_test`, `playwright`, `dependencies`, `telemetry`), the resolved
pinned version (from `analyzers.json`) for one that bootstraps a binary:

```bash
fab-test doctor --format json
```
```json
{
  "analyzers": [
    {"analyzer": "bpa", "ready": true, "resolved_path": "C:\\...\\TabularEditor.exe", "reason": "resolved via cached download (version 2.28.0)", "remediation": null, "version": "2.28.0"},
    {"analyzer": "pbir", "ready": true, "resolved_path": "C:\\...\\fab-inspector.exe", "reason": "resolved via cached download (version 3.4.0)", "remediation": null, "version": "3.4.0"},
    {"analyzer": "pql_test", "ready": false, "resolved_path": null, "reason": "no workspace, credentials, or running Desktop instance", "remediation": "Set FABRIC_WORKSPACE_ID ...", "version": null}
  ]
}
```

The download cache is keyed by `version`, so bumping the pin in a `fab-test`
upgrade downloads the new binary rather than reusing whatever an older
checkout cached. If a local override (an env var or a `default_path` file) is
shadowing the declared pin, `reason` names the variable or file and says the
resolved tool will not receive automatic updates — a state a user in it can't
fix by upgrading `fab-test` alone. See
[docs/RELEASE.md](https://github.com/kerski/fab-test/blob/main/docs/RELEASE.md#bumping-a-wrapped-tools-pin)
for how a pin gets bumped and delivered.

`doctor --local` checks Python version, whether a Desktop instance is running, the Desktop Bridge CLI's presence (path only — never invoked), and each of `fab-test local`'s four analyzers, then states exactly which ones would run:

```bash
fab-test doctor --local --format json
```
```json
{
  "checks": [
    {"check": "python", "ready": true, "reason": "3.12.10", "resolved_path": "/usr/bin/python3.12", "remediation": null},
    {"check": "desktop", "ready": false, "reason": "no running instance detected", "resolved_path": null, "remediation": "Open a .pbip file in Power BI Desktop"},
    {"check": "bpa", "ready": true, "reason": "resolved via cached download (version 2.28.0)", "resolved_path": "C:\\...\\TabularEditor.exe", "remediation": null, "version": "2.28.0"}
  ],
  "would_run": ["bpa", "pbir", "pql_test"]
}
```

Only the bootstrapped checks (`bpa`, `pbir`) carry `version` here — the
Python/Desktop/Desktop-Bridge/`pql_test` checks under `--local` have no tool
version of their own, so the key is simply absent rather than `null`. The
plain (non-`--local`) `doctor` above is the one with the uniform five-key
shape.

### The run manifest (`fab-test-results/run.json`)

Every analyzer invocation (a single subcommand or `all`) writes one `run.json` under `--output-dir` (default `fab-test-results/`), so a caller reads one file instead of globbing result directories:

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
      "envelope_path": "fab-test-results/bpa/SampleModel-PQLAssert/envelope.json",
      "errors": 0,
      "warnings": 21,
      "detail": null
    }
  ],
  "totals": {"errors": 0, "warnings": 21},
  "telemetry_error": null,
  "exit_code": 0
}
```

Per-artifact `status` is one of `passed` / `failed` / `skipped` / `timeout` / `preflight_failed` (the last two cover an aborted run). `detail` is `null` for a normal completion and carries the human-readable failure reason whenever the run ended without a result to report — the resolved remediation message for `preflight_failed`, the exceeded duration for `timeout`, and the analyzer's own error message when it exited non-zero before writing an envelope (`"status": "failed"` with `"envelope_path": null`). That last case is the one a pipeline meets most: `fab-test playwright --artifact ThinReport` with no `--env` aborts before authenticating, and `detail` carries `No environment given, so there is nothing to resolve 'ThinReport' against. Pass --env, ...`. So a caller never has to fall back to stderr to learn what to fix — `run.json` on its own is enough, which matters when it is the only file a pipeline uploads. `detail` stays `null` when the analyzer *did* write an envelope, however it failed: the findings are the reason, and `envelope_path` points at them. `origin` is `"local"` when no CI environment variable is detected, or the detected CI system's name (`"github-actions"`, `"gitlab-ci"`, `"circleci"`, `"azure-devops"`) otherwise — the envelope schema, `status` values, and result layout are identical either way; this is the only field that differs between a local run and a CI run. The `command` field is sanitized: known credential flags (`--client-secret`, `--password`, `--token`, `--secret`, `--api-key`) and any `key=value`-shaped token have their value redacted before the file is written — no credential ever appears in the manifest.

`target` is the resolved target as a structured object, or `null` when the run discovered artifacts instead of being pointed at one. Branch on `scope` (`path` / `desktop` / `workspace`) rather than parsing `raw`. Where `origin` says local versus CI, `target` says whether the run read files on disk, a running Desktop instance, or a deployed workspace item — a distinction `origin` alone never answered. `workspace_id` is the GUID resolved from a workspace name; it names a workspace and grants access to nothing, so it is safe to record.

`telemetry_error` is `null` when this run's telemetry was delivered, or when none was asked for; otherwise it carries why the records were dropped — an unreachable cluster, a missing `[telemetry]` extra, a missing Database Ingestor grant. It never changes `exit_code`: telemetry is diagnostic and must not fail a build. See [Telemetry](#telemetry).

`doctor`, `list`, `explain`, `auth`, and `clean-tools` never write a manifest — they don't run an analyzer.

## Subcommands

```
 fab-test bpa              — Tabular Editor Best Practice Analyzer (SemanticModel artifacts)
 fab-test pbir             — PBIR Inspector static report analysis (Report artifacts)
 fab-test a11y             — pbir-a11y accessibility checks (Report artifacts) — opt-in, not run by `fab-test all`
 fab-test pql-test         — pql-test DAX/PQL test runner (SemanticModel artifacts) [alias: pql_test]
 fab-test playwright       — Playwright visual/error validation (Report artifacts)
 fab-test playwright-impact — Build impacted-report manifest from changed artifacts [alias: playwright_impact]
 fab-test dependencies     — Discover reports that depend on a deployed semantic model
 fab-test all              — Run the analyzers listed in analyzers.json
 fab-test local            — Run BPA, PBIR Inspector, and Desktop-bound pql-test — no cloud required
 fab-test doctor           — Check whether each analyzer's tool/credentials are ready
 fab-test doctor --local   — Check readiness for the local Desktop workflow specifically
 fab-test list             — List subcommands with artifact glob, matched count, and required tool
 fab-test explain ANALYZER — Show the resolved command for one analyzer without running it
 fab-test config --show    — Print every effective setting with its value and origin
 fab-test config --validate — Confirm fab-test.yml's keys and types are valid
 fab-test init             — Scaffold fab-test.yml, .fab-test/.gitignore, and .fab-test/.env.example
 fab-test auth status      — Show which identity fab-test would use, verified for real
 fab-test auth login       — Delegate sign-in to the tool that owns the credential
 fab-test clean-tools      — Remove or inspect the .fab-test-tools downloaded-binary cache
```

Underscore spellings (`pql_test`, `playwright_impact`) still work silently as aliases —
existing scripts and muscle memory keep working. Result directories under `fab-test-results/`
use the original underscore names regardless of which spelling you invoke.

## Targeting

Every analyzer subcommand takes an optional positional `TARGET` naming what to test. Omit it and `fab-test` discovers every matching artifact, exactly as before. The grammar is the one `pql-test` and the Fabric CLI already use, so a target pasted from either means the same thing here.

| Target | Means |
|--------|-------|
| *(omitted)* | Discover every matching artifact under `--artifact-dir` (default: the working directory) |
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
| `bpa`, `pbir`, `a11y` | yes | yes | **no** |
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

## Discovery

`--artifact-dir` defaults to the working directory for every subcommand,
`all` and `local` included. Discovery walks down from there.

**What counts as an artifact.** A folder whose name ends in a Fabric type
suffix, at any depth, with or without a `.pbip` beside it. A committed
`deployed/Sales.SemanticModel` is found; before, only top-level folders and
`.pbip`-paired ones were. `.pbip` pairing still supplies the `[from X.pbip]`
note and the Desktop binding — it no longer decides whether an artifact
exists.

**Where the suffixes come from.** `artifact-map.json`, resolved via the metadata
layers (`.fab-test/metadata/` > `.github/metadata/` > packaged with the
distribution), maps nine suffixes to Fabric types. The packaged copy is the
fallback so an install from PyPI or a run outside a checkout behaves
identically; a malformed map takes the same path as a missing one and warns.
Adding a type means editing the map, not the code.

**What is pruned, and why it is load-bearing.** Nested git checkouts
(worktrees, vendored clones), `.venv`, `venv`, `env`, `node_modules`,
`__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `dist`,
`build`, `.fab-test-tools`, and the run's own `--output-dir`. Without these a
scan of this repository returns eight artifacts where three are real, the
other five being worktree copies. Results are pruned because envelopes land
in folders named after the artifacts that produced them, which a scan would
otherwise rediscover as artifacts.

A matched folder is not descended into: Fabric artifacts do not nest, and
`Sales.SemanticModel/definition` is a matched artifact's contents.

**When pruning empties the result.** Run from a directory that holds
repositories rather than artifacts — `~/Git`, a projects folder — and every
candidate below it is a nested checkout, so discovery returns nothing by
design. It is not silent about it: the warning names how many checkouts it
skipped and up to three of them as a pasteable `--artifact-dir`, and
`--format json` carries the same in `skipped_checkouts` plus a
`remediation` string.

```
  ⚠ fab-test pbir: no *.Report artifacts found under C:\Users\jkers\Git
    9 git checkouts below this root were skipped — a scan does not
    descend into a nested repository. cd into one, or name it directly:
      --artifact-dir C:\Users\jkers\Git\fab-test
```

`fab-test list` says the same below its table when every discovering
analyzer matched `0` and checkouts were pruned. Both stay silent when
nothing was pruned, so `skipped_checkouts: []` with an empty `artifacts`
means the root genuinely holds no artifacts — that is the distinction the
key exists to make.

**Unhandled types.** All nine types parse, so a target can name one no
analyzer reads. `fab-test bpa Sales.Notebook` exits `2` with
`bpa reads SemanticModel artifacts; 'Sales.Notebook' is a Notebook, which no
fab-test analyzer reads`; where another analyzer does read that type it is
named instead. Under `all`, the analyzer is skipped with the same message
rather than failing the batch. `fab-test list`'s Glob column shows which
suffix each analyzer handles.

**In CI, keep passing `--artifact-dir` explicitly.** A default that follows
the working directory is right at a prompt and wrong in a build: pinning the
root means the job scans the same tree whichever directory the runner starts
in. An explicit path that does not exist still exits `2`; an absent default
does not. It also settles the pruning question before it arises — a job that
checks out submodules or vendors a second repository has nested checkouts by
construction, and naming the root says which tree to scan instead of relying
on where the runner landed:

```yaml
- name: Validate artifacts
  run: fab-test all --artifact-dir "${{ github.workspace }}/artifacts" --format json
```

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

## Reports

Result envelopes are the machine contract. A person who wants to know *what actually failed* needs something else, so `fab-test` can write a readable HTML report per artifact.

**Generation is opt-in.** Nothing is written unless `--report` is passed (or `report: true` in `fab-test.yml`, or `ANALYZER_REPORT=1`), so no existing run gets slower and no pipeline collects artifacts it did not ask for.

```bash
fab-test all --report          # reports for every analyzer, plus an index
fab-test bpa --report          # one analyzer
fab-test all --report --no-report   # invalid: mutually exclusive, exits 2
```

### Where a report comes from

| Analyzer | Report | Why |
|----------|--------|-----|
| `pbir` | Upstream `native.json/TestRun.html` | PBIR Inspector produces its own, richer than anything rendered from the envelope. **Appears with or without `--report`.** |
| `bpa` | Generated `report.html` | Tabular Editor emits TRX (Visual Studio TeamTest XML); there is no HTML to wrap. |
| `pql-test` | Generated `report.html` | `pql-test` emits JSON and CI log annotations only. |

The generated report never overwrites an upstream one: `attach_report` is a no-op when the envelope already carries `native_html_output_path`. PBIR's own `TestRun.html` also has two upstream asset paths repaired in place, both by inlining as base64 data URIs rather than leaving a relative path for the browser to resolve: the favicon (`fix_favicon_link`) -- FabInspCLI ships it relative to the tool's *install* directory, which 404s once the report lands under `fab-test-results/` -- and each per-object screenshot (`fix_screenshot_images`) -- the template builds that `src` as `PBIInspectorPNG\<Id>.png`, a Windows-style relative path with the same problem. An object whose screenshot file genuinely isn't in that folder is left as it was; only the images that exist but couldn't resolve get fixed.

Every report is a single self-contained file — no external stylesheet, script, or font ever fetches, links, or points off the page, so it opens from disk and survives being uploaded as a CI artifact. Rendering is deterministic: the same envelope always produces the same bytes, and the run time shown comes from the envelope's `started_at`, never from render time.

**A failure to render is a warning, never a failed build.** Exit codes belong to findings, not to presentation.

### The full test list and its filter

`findings` only ever holds violations — a passing run has always rendered as "No findings" with no evidence of what ran. An envelope may additionally carry `test_results`: every test or rule the analyzer evaluated, passed or failed. When it is present and non-empty, `render_report` shows that full list instead of the findings-only table, each row tagged `pass`/`warning`/`error`/`skip`, with an **All / Errors / Warnings / Passed** filter above the table — pure CSS (hidden radio inputs + sibling selectors). `bpa` and `pql_test` both populate `test_results` today; `pbir`'s own `TestRun.html` has its own filter UI and is untouched by this.

The full list also has a **search box and clickable, sortable column headers** (Search and Sort epic) — the one place the report emits an inline `<script>`. It never fetches, links, or references anything outside the page, so the self-contained-report guarantee still holds; only the stricter "no script at all" claim was relaxed. Typing in the search box hides any row whose text doesn't match, live; clicking a header sorts by that column (ascending, then descending on a second click), and appends a ▲/▼ arrow to that header so the active column and direction stay visible — clicking a different header moves the arrow, clearing the previous one (Sort Direction Indicator epic). Both search and sort compose with the status filter and with each other, and a "No matching rows" message appears if all three combine to nothing. None of this appears on the findings-only table or the per-run index — both have no full test list to search or sort, so neither gets the search box or the script.

**Extending this to a new analyzer**: populate `test_results` on the envelope with a list of dicts in either shape `normalize_findings` already recognizes (pql-test's `suite_name`/`test_name`/`passed`/`expected`/`actual`, or a rule shape with `rule`/`severity`/`object`/`message` plus a `status` key of `pass`/`error`/`warning`/`skip`) — the renderer, the filter, the search box, the column sort, and the status colouring all come for free. No new HTML to write.

### The per-run index

`fab-test all --report` also writes `fab-test-results/index.html` linking every report and envelope, so one run means one page to open rather than four. It is built from the same rows the terminal summary prints, so its counts cannot disagree with them. Written only for a multi-analyzer run — indexing one analyzer is a page pointing at a single link.

The index header also shows **when the run happened and who ran it**: a UTC timestamp, plus branch/commit/actor sourced from `GITHUB_*` environment variables in CI, falling back to local `git` (branch, commit, `git config user.email`) outside CI, and to an em-dash (`—`) placeholder outside a git checkout entirely — it never raises. Per-analyzer `report.html` deliberately has no timestamp (see above): the index is scoped to one run, not a reusable artifact, which is why only it gained one.

### Finding the paths

The `all` summary lists one path per artifact beneath the table — the report where there is one, the envelope otherwise:

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
```

Paths are relative to the working directory and never truncated, so they stay clickable in a terminal that linkifies them. Under `--format json` each artifact row carries `report_path` (null when absent) alongside `output_path`, which keeps its existing meaning.

### Colour

Status and non-zero error/warning counts are coloured in text output. Colour is **off** when stdout is not a terminal, **off** whenever `NO_COLOR` is set (any value), always **off** under `--format json`, and can be forced on with `FORCE_COLOR=1` for a CI job that renders ANSI.

## Configuration

`fab-test.yml` at the repository root is an entirely optional config-file front door. No file at all means every setting resolves exactly as it did before this file existed.

```bash
fab-test --config custom.yml bpa   # --config must come before the subcommand: it's a top-level flag
fab-test init                      # scaffold fab-test.yml, .fab-test/.gitignore, .fab-test/.env.example
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
| 4 (lowest) | Packaged default | `200` seconds |

If both `fab-test.yml` and `[tool.fab-test]` are present, `fab-test.yml` wins per key and the CLI warns once about the duplicate source. `fab-test config --show --format json` reports each setting's origin as one of `flag`, `env:NAME`, `fab-test.yml:key`, or `default`.

### Settings

| Key | Type | Env var | Default |
|-----|------|---------|---------|
| `artifact_dir` | string | — | the working directory |
| `output_dir` | string | — | `fab-test-results` |
| `jobs` | integer | — | `1` |
| `format` | string (`text`\|`json`) | — | `text` |
| `timeout` | integer | `ANALYZER_TIMEOUT` | `200` |
| `environment` | string | `FABRIC_ENVIRONMENT` | (none) |
| `workspace` | string | `FABRIC_WORKSPACE_ID` | (none) — display name or GUID |
| `report` | boolean | `ANALYZER_REPORT` | `false` — see Reports below |
| `rules` | object | — | (none) — see Rule Overlays below |
| `telemetry` | object | — | (none) — see Telemetry below |

An unknown key exits `2` naming the key and the closest valid key (e.g. `artifac_dir` → "did you mean 'artifact_dir'?"); a key with the wrong type exits `2` naming the expected type.

### Telemetry

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

### Rule Overlays

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

### Metadata files and where they come from

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

### What belongs in `fab-test.yml` vs. repository secrets

`fab-test.yml` is meant to be committed — it holds no credentials. Service-principal credentials (`FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`) belong in a `.env` file or, in a pipeline, in the CI system's own secrets store — never in `fab-test.yml`. With no service-principal variables set at all, Fabric REST calls fall back to `DefaultAzureCredential` (`az login`, a managed identity, VS Code sign-in, ...) for every command except `fab-test playwright`, which always needs the full service principal (see the `playwright` subcommand section below).

**`.env` discovery order**, defined once and shared by `_credentials.py` and the Playwright config loader so they cannot disagree: `--env-file` > `PLAYWRIGHT_ENV_FILE` > `.fab-test/.env` > `./.env`. `.fab-test/.env` is preferred when both exist. `fab-test init` scaffolds `.fab-test/.gitignore` (containing `.env`) and `.fab-test/.env.example` alongside it, so a real `.env` in the same directory as the committed `.fab-test/metadata/` is protected by fab-test's own scaffolding rather than depending on a consumer's root `.gitignore` already covering it. A root `.env` keeps working unchanged when no `.fab-test/.env` exists. `fab-test auth status` reports which one actually supplied a credential (`.fab-test/.env`, `.env`, or `environment`).

## Global Flags (all subcommands)

| Flag | Default | Description |
|------|---------|-------------|
| `TARGET` (positional) | (discover all) | What to test — see [Targeting](#targeting) for the grammar |
| `--artifact STEM` | (all) | Deprecated alias for `TARGET`; passing both exits `2` |
| `--artifact-dir DIR` | the working directory | Root to discover artifacts under, recursively |
| `--output-dir DIR` | `fab-test-results` | Root directory for result envelopes |
| `--dry-run` | off | List matching artifacts without running any analyzer |
| `--telemetry` / `--no-telemetry` | config-driven | Force/suppress Eventhouse telemetry. A configured destination already enables it; `--telemetry` with none configured exits `2` — see [Telemetry](#telemetry) |
| `--report` / `--no-report` | off | Write a readable HTML report beside each envelope [env: `ANALYZER_REPORT`] |
| `--format {text,json}` | `text` | Aggregate summary output format (see Agent Contract above for the stdout guarantee) |
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

A missing prerequisite (`pqlint` not installed, Tabular Editor/PBIR Inspector not resolved) is reported as **skipped** with a remediation hint — it never fails the run. Exit code `1` only means a real finding, never a missing tool. `pql-test` is always ready (it's a pinned `fab-test` dependency); if a Desktop instance has the project's `.pbip` open, `pql-test`'s envelope records a `desktop` field naming the port and model it bound to (see `pql-test` below and the run manifest section for the full shape).

Discovery walks `--artifact-dir` recursively — see [Discovery](#discovery) for the rules, which are the same for every subcommand.

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

When [`resolve_item`](../../../src/fabric_ci_cd_dataops/scripts/playwright_validation/resolver.py)
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
  index.html          ← per-run index, only with --report on a multi-analyzer run
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


For `pql_test`, the envelope also contains `test_results` (full result array from pql-test, native shape). For `bpa`, it contains one entry per rule TE2 evaluated (`RuleName`/`RuleID`/`Severity`/`Category`/`ObjectName` plus a computed `status` of `pass`/`error`/`warning`), passed and failed alike — unlike `findings`, which stays failure-only. `pbir` matches the same idea in the shared `rule`/`severity`/`object`/`message` shape (each with a `status`), so telemetry can see every rule PBIR Inspector evaluated, not only the ones that failed — `pbir`'s own `TestRun.html` still has its own filter UI, so this field feeds telemetry, not the shared report's full-list filter, for that analyzer specifically. `playwright` uses the pql-test-shaped `test_results` too (one row per generated report x page x bookmark case), plus an `evidence` map per row (`screenshot`/`console`/`network` paths, whichever exist) that the shared renderer turns into links when `--report` is on (see the `playwright` section above). All four are `[]` when the analyzer produced no per-test breakdown.

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
