# Targeting and Discovery

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
| `bpa`, `pbir`, `a11y`, `rdl` | yes | yes | yes — exports the deployed definition read-only |
| `pql-test` | yes | yes | yes |
| `playwright`, `playwright-impact`, `dependencies` | yes | **no** | yes |

The file-reading analyzers accept `local/` because the artifact is on disk either way — only `pql-test` actually *binds* to the running instance. They accept a workspace target by exporting the deployed item's definition through Fabric `getDefinition` (TMDL for a semantic model, PBIR for a report, the `.rdl` for a paginated report) into the run's output directory and analyzing that, so a service run reports through the same envelope, exit codes, HTML report and telemetry as a repo run. `pql-test` exports nothing: under `--workspace` (or `all`) it is handed each deployed model as `WORKSPACE.Workspace/NAME.SemanticModel` and discovers and runs its tests over XMLA. The export is **read-only and ephemeral**: it is deleted after the run unless `--keep-export` is passed (kept files are redacted for connection-string secrets). Exporting a deployed item *for testing* is in scope; deploying remains out of scope. Targets that no analyzer can honor — `pql-lint` with a workspace target — still exit `2` and name the forms that work:

```
$ fab-test pql_lint "Sales Dev.Workspace/Sales.SemanticModel"
  ✗ fab-test: pql_lint reads artifact files on disk and cannot fetch a deployed item.
    Use local/NAME for a running Power BI Desktop instance; a path
    (./src/Sales.SemanticModel) or a name (Sales.SemanticModel)
```

## Modes: local, service

**The TARGET (or its default) decides the mode. Flags and env vars supply defaults; they never silently change the mode.** Every run (except under `--format json` or `-q`, where stderr stays silent) prints `mode=local path=<folder or local/NAME> source=<…>` or `mode=service workspace=<name> source=<…>` (source is `target|flag|env|config|default`) on stderr first, and the envelope carries additive `mode` and `source` fields. In service mode, each item export then prints `exporting <Name>.<Type>... done (<seconds>s)` (or `... failed`) on stderr, under the same silence rules, so a multi-item `--workspace` run never sits silent while definitions download. A workspace-wide inventory (no item named) skips the usage-metrics items Microsoft generates (`Dashboard Usage Metrics Model`/`Report`, `Report Usage Metrics Model`/`Report`, `Usage Metrics Report`); naming one explicitly still analyzes it.

| Invocation | Mode |
|------------|------|
| `fab-test bpa`, `bpa Sales.SemanticModel`, `bpa ./src/Sales.SemanticModel` | `local` — artifact files in a folder; Git is not required |
| `fab-test pql-test local/Sales` | `local` — the model open in Power BI Desktop (an ambient `FABRIC_WORKSPACE_ID` never turns it remote) |
| `fab-test bpa "Dev.Workspace/Sales.SemanticModel"` | `service` — typed target |
| `fab-test bpa "Dev.Workspace/Sales"` | `service` — untyped, resolved by the analyzer's own type |
| `fab-test bpa --workspace Dev` | `service` — every deployed item of the analyzer's type; local folders are ignored unless `--artifact-dir` is passed |
| `fab-test all --workspace Dev` | `service` — every service-capable analyzer, including `pql-test` per model and `rdl` over paginated reports |
| `--workspace X` with a target naming workspace Y, or `local/NAME` with `--workspace` | exit `2` |

`workspace:` in `fab-test.yml` and `FABRIC_WORKSPACE_ID` supply a default workspace; they never flip a bare invocation to service. A workspace enumeration over **50** items stops with exit `2` naming `--all` (never a prompt); `--all` forces it. `--dry-run` lists the items; a typed target needs no token. A `getDefinition` 404 (item not in enhanced/Git-integration format) or 403 exits `1` with a named remediation; any other `getDefinition` failure exits `1` naming Fabric's own error code and message; an export that cannot be written exits `1` naming the path — a path over Windows' 260-character limit (PBIR's nested `visuals/` folders under a deep `--output-dir`) names a shorter `--output-dir` or Windows long-path support as the fix; missing credentials exit `127`. A report is exported in its stored format: a PBIR-Legacy report (a single `report.json`) is skipped with a `⏭ <name>.Report skipped` line — never analyzed, since the rules read PBIR and would pass it vacuously — and the run exits `1`; when every report is legacy it exits `1` naming them. Convert the report to PBIR to test it.

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
distribution), maps ten suffixes to Fabric types (`PaginatedReport` added
alongside `Report` for the Paginated Report Testing epic, so
`WORKSPACE.Workspace/NAME.PaginatedReport` parses). The packaged copy is the
fallback so an install from PyPI or a run outside a checkout behaves
identically; a malformed map takes the same path as a missing one and warns.
Adding a folder type means editing the map, not the code.

**Flat-file artifacts.** A paginated report has no corresponding folder
convention — it is a flat `NAME.rdl` file, never a `NAME.PaginatedReport/`
folder in practice. `discover_artifacts` decides the shape from the
analyzer's own glob: a suffix declared in `artifact-map.json` is a folder,
scanned the directory-suffix way described above; anything else (`*.rdl`)
is a file, found by walking for a matching filename instead. Both shapes
share the same target/path/type narrowing — `Sales.rdl` and
`Sales.SemanticModel` both resolve as a typed target, a path target checks
`is_file()` or `is_dir()` to match the right shape, and the run's own
result folder is pruned from discovery either way. `rdl` (see [Flags](flags.md))
is the one analyzer that reads `.rdl` files today; `playwright` also
discovers them, for the deployed report's local `.rdl` when one exists
(dataset auto-resolution — see the `playwright` section in
[Flags](flags.md)), and resolves everything else about a paginated report
live regardless.

**What is pruned, and why it is load-bearing.** Nested git checkouts
(worktrees, vendored clones), `.venv`, `venv`, `env`, `node_modules`,
`__pycache__`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `dist`,
`build`, `.fab-test-tools`, `.github`, `.claude`, and the run's own
`--output-dir`. `.github` and `.claude` hold agent tooling — skill
instructions, worked examples, worktrees — not this project's own
artifacts, so a suffix-matching folder placed there for documentation
purposes is never mistaken for one to test. Without these a scan of this
repository returns eight artifacts where three are real, the other five
being worktree copies. Results are pruned because envelopes land in folders
named after the artifacts that produced them, which a scan would otherwise
rediscover as artifacts.

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

**Unhandled types.** All ten `artifact-map.json` types parse, so a target
can name one no analyzer reads. `fab-test bpa Sales.Notebook` exits `2`
with `bpa reads SemanticModel artifacts; 'Sales.Notebook' is a Notebook,
which no fab-test analyzer reads`; where another analyzer does read that
type it is named instead. Under `all`, the analyzer is skipped with the
same message rather than failing the batch. `fab-test list`'s Glob column
shows which suffix each analyzer handles. `rdl` (a file suffix, not a
Fabric item type) parses the same way from a separate, small vocabulary
just for flat-file analyzers — `Sales.rdl` is a valid typed target even
though "rdl" is not in the ten-type list above.

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
