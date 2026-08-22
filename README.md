# fab-test

Metadata-driven CI/CD and validation framework for Microsoft Fabric artifacts.

This package provides the `fab-test` CLI and supporting analyzer wrappers used by the [fabric-ci-cd-dataops](https://github.com/kerski/fabric-ci-cd-dataops) reference implementation.

## Install

### From PyPI

```bash
pip install fab-test
```

### From source in editable mode (developers)

Editable mode links the package source into the active environment so code changes are reflected immediately.

```bash
git clone https://github.com/kerski/fab-test.git
cd fab-test
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

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
pip install dist/fab_test-*.whl
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
A folder is an artifact because its name ends in a Fabric type suffix —
`Sales.SemanticModel`, `Sales.Report` — at any depth, whether or not a
`.pbip` sits beside it. That last part matters for artifacts committed for
CI rather than opened in Desktop: `deployed/Sales.SemanticModel` on its own
is found.

The suffixes come from [`.github/metadata/artifact-map.json`](https://github.com/kerski/fab-test/blob/main/.github/metadata/artifact-map.json),
with a copy packaged in the distribution so an install outside this
repository behaves the same.

Skipped while walking: nested git checkouts (worktrees, vendored clones),
`.venv`, `node_modules`, `__pycache__`, `dist`, `build`, and the run's own
`--output-dir`. Without those exclusions a scan of this repository returns
eight artifacts where three are real.

**If you already have a `.fabric/artifacts/` layout, nothing you do needs to
change.** That directory sits inside your working directory, so everything
found before is still found. `--artifact-dir` still narrows the search when
you pass it, and still exits `2` if the path you name does not exist.

Every analyzer is built on that assumption:

| Analyzer | Discovers | Reads on disk | Format it requires |
|----------|-----------|---------------|--------------------|
| `bpa` (Tabular Editor) | `*.SemanticModel` | `definition/` | TMDL |
| `pql-test`, `pql-lint` | `*.SemanticModel` | `definition/` | TMDL |
| `pbir` (PBIR Inspector) | `*.Report` | `definition/` | PBIR |
| `playwright` | `*.Report` | — (renders the deployed report) | folder naming only |

Deployment and dependency discovery read the report's `definition.pbir` to resolve which semantic model it points at, so that file is what pairs a report with its model.

Power BI Desktop writes this layout when you **Save as** a `.pbip` project with the TMDL and enhanced report format (PBIR) options turned on — under **File → Options and settings → Options → Preview features** in the versions where they are still preview.

Discovery matches on folder suffix (`*.SemanticModel`, `*.Report`), not on folder contents, so a project saved in the legacy format is still picked up — it fails inside the analyzer that cannot read it rather than being reported as an unsupported format. A bare `.pbix` is not a supported input at all.

## Run manual tests locally

### Local Desktop workflow (no cloud required)

The fastest path to real findings: a `.pbip` open in Power BI Desktop, no `.fabric/artifacts` layout, no Fabric workspace, no service principal. The project has to be saved in TMDL and PBIR — see [Assumed project format](#assumed-project-format).

```bash
fab-test doctor --local     # what's ready, and what fab-test local will run
fab-test local --dry-run    # see the plan first
fab-test local              # BPA, PBIR Inspector, and Desktop-bound pql-test
```

A missing prerequisite (e.g. `pqlint` not installed) is reported as skipped with a remediation hint, not a failure. See [`docs/QUICKSTART-LOCAL.md`](https://github.com/kerski/fab-test/blob/main/docs/QUICKSTART-LOCAL.md) for the full walkthrough.

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

# Run pql-test DAX tests
fab-test pql-test --env DEV

# Run Playwright visual validation (requires service-principal credentials)
fab-test playwright --artifact "Not Working Visuals" --env dev --env-file .env

# Discover reports that depend on a deployed semantic model
fab-test dependencies --semantic-model SalesModel --env dev --env-file .env
```

### Naming what to test

Every analyzer subcommand takes an optional target. Omit it and `fab-test` discovers everything matching, as before. The grammar is the one `pql-test` and the Fabric CLI already use, so a target pasted from either works here unchanged.

| Target | Means |
|--------|-------|
| *(omitted)* | Discover every matching artifact under `--artifact-dir` (default: the working directory) |
| `Sales` | The artifact named `Sales`; the analyzer's own glob picks the type |
| `Sales.SemanticModel` | That name **and** type — `Sales.Report` is not selected |
| `./src/Sales.SemanticModel` | Exactly that folder, wherever it lives (not confined to `--artifact-dir`) |
| `local/Sales` | The copy open in a running Power BI Desktop instance |
| `"Sales Dev.Workspace/Sales.SemanticModel"` | A deployed item in the named Fabric workspace |

```bash
fab-test bpa Sales.SemanticModel                          # one artifact, by name and type
fab-test pql-test local/Sales                             # bind to Power BI Desktop
fab-test pql-test "Sales Dev.Workspace/Sales.SemanticModel"   # a deployed model
fab-test all local/Sales                                  # everything that can run locally
```

Not every analyzer accepts every form — `bpa` reads files on disk and cannot fetch a deployed item. Run `fab-test list` for the Scopes column, and see the [targeting reference](https://github.com/kerski/fab-test/blob/main/.github/skills/fab-test/SKILL.md#targeting) for the rules. `--artifact STEM` still works as a deprecated alias.

### Credentials

**`fab-test` stores no credentials** — no token, no cache, no credential file. It reads what your environment already provides and delegates sign-in to the tool that owns the credential, so there is no `fab-test` token cache to look for.

```bash
fab-test auth status        # which identity would be used, verified for real
fab-test auth login         # delegates to `pql-test auth login`
```

`auth status` resolves in the same order that actually authenticates — environment variables, then `.env`, then an ambient Azure credential (`az login`, managed identity, VS Code sign-in). It exits `0` when verified, `127` when nothing resolves, and `1` when credentials work but a named workspace is unreachable.

`fab-test doctor` uses the same chain but never acquires a token, so it reports an ambient credential as `unverified` and points at `auth status`. That is expected.

> `--env` is the test environment label (`DEV`, `PROD`). `--cloud`, on `auth login` only, selects the Azure cloud. They are deliberately different names.

### Readable reports

The result envelopes are the machine contract. To see *what actually failed* without reading JSON, ask for a report:

```bash
fab-test all --report
```

Reports are **opt-in** — nothing is written without the flag, so no existing run gets slower. Add `report: true` to `fab-test.yml` to turn them on for good.

Each artifact gets a self-contained HTML page beside its envelope, and `fab-test all --report` also writes `analyzer-results/index.html` linking them all, so one run means one page to open:

```
  ╭────────────┬───────────────────────┬──────────┬───────┬────────╮
  │ Analyzer   │ Artifact              │ Status   │   Err │   Warn │
  ├────────────┼───────────────────────┼──────────┼───────┼────────┤
  │ pbir       │ SampleModel-PQLAssert │ FAILED   │     4 │      1 │
  │ bpa        │ SampleModel-PQLAssert │ warning  │     0 │     21 │
  ╰────────────┴───────────────────────┴──────────┴───────┴────────╯

  pbir/SampleModel-PQLAssert
    analyzer-results/pbir/SampleModel-PQLAssert/native.json/TestRun.html
  bpa/SampleModel-PQLAssert
    analyzer-results/bpa/SampleModel-PQLAssert/report.html

  Index:  analyzer-results/index.html
```

PBIR Inspector writes its own `TestRun.html` and it appears **with or without** `--report` — it is richer than anything generated from the envelope, so `fab-test` never overwrites it. Tabular Editor emits TRX and `pql-test` emits JSON, so those two get a generated `report.html`.

Status and non-zero counts are coloured in a terminal. Colour is off when output is redirected, off whenever `NO_COLOR` is set, and never present under `--format json`.

### The machine-readable workflow (agents and pipelines)

`fab-test` is designed to be called the same way by a human, a CI pipeline, or an AI agent. The four-command loop:

```bash
fab-test doctor --format json          # 1. is each analyzer's tool/credential ready?
fab-test list --format json            # 2. what subcommands exist, and how many artifacts match?
fab-test bpa --format json             # 3. run it — stdout is exactly one JSON document
cat analyzer-results/run.json          # 4. read the manifest instead of globbing result dirs
```

`--format json` guarantees stdout carries nothing but the payload — narration goes to stderr. When a run fails, `run.json` says why without a second file: an artifact whose analyzer aborted before writing an envelope carries the remediation message in its `detail` field (`"Pass --env, set FABRIC_ENVIRONMENT, ..."`), so uploading the manifest alone is enough to diagnose a red build. See the [Agent Contract](https://github.com/kerski/fab-test/blob/main/.github/skills/fab-test/SKILL.md#agent-contract) for exit codes, the JSON stdout guarantee, and the `run.json` schema.

Full CLI reference: [`.github/skills/fab-test/SKILL.md`](https://github.com/kerski/fab-test/blob/main/.github/skills/fab-test/SKILL.md).

See [`docs/QUICK-VALIDATION.md`](https://github.com/kerski/fab-test/blob/main/docs/QUICK-VALIDATION.md) for a complete local build-and-test workflow.

## Configuration

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

`fab-test.yml` is meant to be committed — it holds no credentials, only settings and rule overlays (tune one BPA/PBIR Inspector rule without forking the packaged rules file). Credentials belong in a `.env` file (auto-discovered, gitignored) or a pipeline's own secrets store. See the [Configuration section of the fab-test skill](https://github.com/kerski/fab-test/blob/main/.github/skills/fab-test/SKILL.md#configuration) for the full settings list and rule-overlay keys.

### Where metadata lives

Rulesets, the analyzer registry, the artifact map, and `environments.yml` all resolve the
same way — `.fab-test/metadata/` first, then `.github/metadata/`, then the copy packaged in
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
kept only so existing repositories keep working — `.github/` belongs to GitHub, not to this
tool. Anything you don't override comes from the wheel, so a `pip install` works with no
metadata of your own at all.

`environments.yml` is the one exception: it has no packaged default, because a workspace GUID
baked into a release would aim a deployment at somewhere you never chose. If no layer supplies
it, the command fails and names both places you could put it.

## Usage

`fab-test` discovers and analyzes artifacts under your working directory. It is the local equivalent of the CI artifact validation gate. See the [Run manual tests locally](#run-manual-tests-locally) section above for common commands, and [`.github/skills/fab-test/SKILL.md`](https://github.com/kerski/fab-test/blob/main/.github/skills/fab-test/SKILL.md) for the full CLI reference.

## AI agent guidance

The AIDD agent instructions and skills live in the repository, not in the wheel: [`.github/agents/`](https://github.com/kerski/fab-test/tree/main/.github/agents/) and [`.github/skills/`](https://github.com/kerski/fab-test/tree/main/.github/skills/). Clone the repository to get them. The `fab-test` CLI reference an agent needs is [`.github/skills/fab-test/SKILL.md`](https://github.com/kerski/fab-test/blob/main/.github/skills/fab-test/SKILL.md).

What the distribution *does* carry is the metadata the analyzers need, so `bpa`, `pbir`, and `doctor` work from a plain `pip install` with no checkout:

```python
import importlib.resources as resources

metadata = resources.files("fabric_ci_cd_dataops").joinpath("metadata")
print(metadata.joinpath("rules/BPARules.json"))  # packaged BPA ruleset
print(metadata.joinpath("analyzers.json"))       # tool install URLs doctor reads
```

## License

MIT. See [LICENSE](https://github.com/kerski/fab-test/blob/main/LICENSE).
