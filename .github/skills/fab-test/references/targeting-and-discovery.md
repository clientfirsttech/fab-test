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
distribution), maps ten suffixes to Fabric types (`PaginatedReport` added
alongside `Report` for the Paginated Report Testing epic, so
`WORKSPACE.Workspace/NAME.PaginatedReport` parses). The packaged copy is the
fallback so an install from PyPI or a run outside a checkout behaves
identically; a malformed map takes the same path as a missing one and warns.
A local paginated report is the one type here with no corresponding folder
convention: it is a flat `NAME.rdl` file, discovered by `playwright`
specifically (see [Flags](flags.md)) rather than through this suffix map.
Adding a type means editing the map, not the code.

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

**Unhandled types.** All ten types parse, so a target can name one no
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
