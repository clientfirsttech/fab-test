---
name: fab-test
description: fab-test CLI reference for running Fabric artifact analyzers locally and against a workspace (fab-test 1.10.0b5). Covers all subcommands, flags, results, slicer contracts, and Data Agent test suites (writing, editing, running), and how fab-test differs from pytest. Use when invoking, troubleshooting, or extending artifact validation.
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
| `fab-test bpa` | Do my Fabric artifacts pass BPA rules? (requires Tabular Editor) |
| `pytest -m pbir` | Is the PBIR wrapper code correct? (always green, no binary needed) |
| `fab-test pbir` | Do my reports pass PBIR Inspector rules? (requires PBIR Inspector binary) |
| `pytest -m pql_test` | Is the pql-test wrapper code correct? (mocked, always green) |
| `fab-test pql-test` | Do my semantic model DAX tests pass? (requires Power BI Desktop open) |
| `pytest -m playwright` | Is the Playwright wrapper code correct? (mocked contract tests) |
| `fab-test playwright` | Do my Power BI reports render without visual-load errors? (requires service-principal credentials) |
| `pytest -m rdl` | Is the rdl rule engine correct? (always green, no external tool — pure Python) |
| `fab-test rdl` | Do my paginated (`.rdl`) reports pass the active performance/correctness/accessibility rules? (no external tool required) |

## Installation

```bash
pip install -e .                          # from a checkout
pip install "cft-fab-test==1.10.0b5"      # from PyPI (a beta: or pip install --pre cft-fab-test); the command is fab-test
pip install "cft-fab-test[playwright]" && playwright install chromium   # before the first playwright run; Linux CI: --with-deps chromium
```

Without the playwright extra, `fab-test playwright` stops before minting any embed token and names the missing packages; `--plan-only` needs neither. The `.venv` is searched for tool binaries (e.g. `pql-test`) even when not on `PATH`. Rules and metadata resolve `.fab-test/metadata/` → `.github/metadata/` (legacy) → the packaged copy; see [references/configuration.md](references/configuration.md#metadata-files-and-where-they-come-from). Releasing: [`docs/RELEASE.md`](../../../docs/RELEASE.md).

## Agent Contract

`fab-test` is built to be called identically by a human, a CI pipeline, and an AI agent.

### Exit codes

```
ExitCode {
  (all artifacts passed) => 0                                   // warnings never fail the build
  (an analyzer found error-level findings) => 1
  (the analyzer process crashed) => 1
  (CLI arguments are invalid; no analyzer was invoked) => 2
  (the analyzer is unsupported on this platform) => 126         // message names the supported OS
  (a required external tool could not be resolved) => 127       // message names the flag, env var, and config key that would fix it
}
```

### Slicer contracts

```
SlicerContracts {
  (a report has fab-tests/pbir/<Report>.Report.odcs.yaml, or one under --artifact-dir naming its logicalId) => fab-test pbir checks what its slicers open with  // CONTRACT.* findings
  (building one as an agent) => contract init --questions --format json |> ask needs_human |> contract init --answers FILE
  (before running it, or in CI before `fab-test pbir`) => contract lint [REPORT]  // 0 clean, 1 problems named, 2 nothing to check
  (a calendar-driven value) => resolved for --as-of (default today); the envelope's `contract` block records it
  (a bad contract) => exit 2 before any analyzer starts
}
```

See [references/slicer-contracts.md](references/slicer-contracts.md).

### Data Agent tests

```
DataAgentTests {
  (an agent builds or edits a suite) => fab-test data-agent tests init TARGET --questions --format json |> ask the person for expected answers |> tests init TARGET --answers FILE
  (an expected answer) => from the person or the data, never invented; never copied from the agent's answer to make a failing test pass
  (the agent should decline) => "match": "refuses", no expect
  (changing a test) => the same query with "replace": true; (deleting) => "remove": [ids] at the top level, which also deletes that conversation's later turns, so say so first
  (a suite was written) => fab-test data-agent tests lint TARGET before any run
  (the service principal is blocked or rejected, a person is signed in with az login) => rerun with --auth az; never loop the principal
}
```

Everything else (pairing, prompts, suggestions, provider failures, identity, CI, suite safety): [references/data-agent.md](references/data-agent.md).

### Service mode

```
ServiceMode {
  fn mode(target, flags) {
    (target is "WS.Workspace/NAME[.Type]")        => service, that one deployed item
    (--workspace WS and no target)                 => service, every deployed item of the analyzer's type; local folders ignored unless --artifact-dir is passed
    (workspace: in fab-test.yml, FABRIC_WORKSPACE_ID) => a default only; never turns a bare run into service mode
  }
  first stderr line: "mode=service workspace=<name> source=<target|flag|env|config|default>"   // silent under -q and --format json
  envelope: carries mode and source
  analyzers: bpa | pbir | a11y | rdl export the definition read-only; pql-test connects over XMLA and exports nothing
  all --workspace: runs fab_test_all from analyzers.json (bpa, pbir, pql-test, rdl) -- not playwright; use playwright --workspace for renders
}

Constraints {
  (more than 50 items of one type and no --all) => exit 2 naming --all
  (one item cannot be exported or is PBIR-Legacy) => that item is named and fails the run (exit 1); the others are still analyzed
  (a workspace target names no deployed item) => exit 1 listing the closest names
  (HTTP 401) => the message says the token was rejected and names az login --tenant / FABRIC_TENANT_ID
  (HTTP 403) => the message names the read access the identity needs
  (no credential resolves) => exit 127
  exports are deleted after the run; --keep-export keeps them redacted under fab-test-results/export/<item id>/<Item>.<Type>/
  (playwright --workspace WS, nothing else naming what to run) => every deployed Report/PaginatedReport, no checkout; --artifact, a target, --artifact-dir (even .), or a dataset selector narrows it instead
  (a playwright role, paginated-definition, or parameter-values lookup fails) => still rendered, with a warning-level coverage_limited finding naming the fix; status warning, exit unchanged
}
```

### JSON stdout guarantee

```
Constraints {
  Every subcommand that accepts --format json writes exactly one JSON document to stdout, nothing else
  Progress, banners, warnings, and any analyzer subprocess's own output are narrated to stderr, never stdout
  (--dry-run) => still exactly one JSON document on stdout: a small {"analyzer": ..., "dry_run": true, "artifacts": [...]} summary, never an empty stdout
  --format text (the default) is unaffected — output is unchanged from before this contract existed
}
```

```bash
fab-test bpa --format json 2>/dev/null | jq .   # safe to pipe straight into jq
```

### Spending fewer tokens: `-q`

**Make `-q` the first invocation** and escalate only if it fails: re-run with `-v`, or read the envelope path `-q` prints.

```
QuietLine {
  shape: "<analyzer> <status> e=<errors> w=<warnings> <where>"   // one per artifact; ~10x smaller than default
  status: "passed" | "warning" | "failed" | "skipped"
  where: the envelope path, always last (artifact names contain spaces)
}
```

`--format json 2>/dev/null` when you need the fields parsed. `verbosity: summary` in `fab-test.yml` pins it for a repository. Full rules: [references/operations.md](references/operations.md#output-verbosity).

### Discoverability: doctor → list → explain

```bash
fab-test doctor                          # is each analyzer's tool/credential ready? exits 1 on any ❌ (--strict: any ⚠)
fab-test doctor --analyzer NAME          # exactly one analyzer: a CI gate
fab-test doctor --local                  # readiness for the local Desktop workflow
fab-test doctor --workspace "Sales Dev"  # readiness for a service run against this workspace
fab-test list                            # subcommands and how many artifacts match (respects --artifact-dir)
fab-test explain bpa                     # the command fab-test bpa would run; never spawns it
```

`doctor` and `list` take `--format json`; the shapes are in [references/discoverability.md](references/discoverability.md).

### The run manifest

Every analyzer run writes one `fab-test-results/run.json`: read it instead of globbing result folders. Its `detail` says why an aborted run produced no result, `target.scope` says whether it read files, Desktop or a workspace, and it never holds a credential. Schema: [references/run-manifest.md](references/run-manifest.md).

## Subcommands

```
 fab-test bpa              — Tabular Editor Best Practice Analyzer (SemanticModel artifacts)
 fab-test pbir             — PBIR Inspector static report analysis (Report artifacts), plus each report's slicer contract
 fab-test pbir contract init — Build or extend a report's slicer contract by asking how to check each slicer
 fab-test pbir contract lint — Check contracts before a run: they read as the run reads them, are valid ODCS, and name what the model has
 fab-test a11y             — pbir-a11y accessibility checks (Report artifacts) — opt-in, not run by `fab-test all`
 fab-test rdl              — RDL static analysis: the active rules for paginated reports (.rdl files) — no external tool
 fab-test pql-test         — pql-test DAX/PQL test runner (SemanticModel artifacts) [alias: pql_test]
 fab-test playwright       — Playwright visual/error validation (Report artifacts)
 fab-test dependencies     — Discover reports that depend on a deployed semantic model
 fab-test data-agent       — Deployed Data Agent regression tests [aliases: agent, data_agent; FAB_TEST_ENABLE_DATA_AGENT=0 turns it off]
 fab-test all              — Run the analyzers listed in analyzers.json
 fab-test local            — Run BPA, PBIR Inspector, and Desktop-bound pql-test — no cloud required
 fab-test doctor           — Check whether each analyzer's tool/credentials are ready
 fab-test doctor --local   — Check readiness for the local Desktop workflow specifically
 fab-test list             — List subcommands with artifact glob, matched count, and required tool
 fab-test explain ANALYZER — Show the resolved command for one analyzer without running it
 fab-test config --show    — Print every effective setting with its value and origin
 fab-test config --validate — Confirm fab-test.yml's keys and types are valid
 fab-test init             — Scaffold fab-test.yml, .fab-test/.gitignore, and .fab-test/.env.example; append .fab-test-tools/ and fab-test-results/ to the root .gitignore
 fab-test auth status      — Show which identity fab-test would use, verified for real
 fab-test auth login       — Delegate sign-in to the tool that owns the credential
 fab-test clean-tools      — Remove or inspect the .fab-test-tools downloaded-binary cache
```

Underscore spellings (`pql_test`) still work silently as aliases —
existing scripts and muscle memory keep working. Result directories under `fab-test-results/`
use the original underscore names regardless of which spelling you invoke.

## Reference files

| File | Read it when... |
|------|------------------|
| [references/targeting-and-discovery.md](references/targeting-and-discovery.md) | You need the `TARGET` grammar, per-analyzer scope rules, or how artifact discovery walks and prunes a directory tree |
| [references/credentials.md](references/credentials.md) | You need to know how `fab-test` resolves an identity, or what `auth status`/`auth login` do |
| [references/reports.md](references/reports.md) | You're generating or debugging the HTML `--report` output, the per-run index, or its search/sort/filter behavior |
| [references/configuration.md](references/configuration.md) | You're touching `fab-test.yml`, precedence, telemetry, rule overlays, or metadata-file resolution |
| [references/flags.md](references/flags.md) | You need the full global flag table or a specific subcommand's flags (`bpa`, `pbir`, `a11y`, `rdl`, `pql-test`, `playwright`, `dependencies`, `all`, `local`) |
| [references/slicer-contracts.md](references/slicer-contracts.md) | A user wants a report's slicer defaults checked (fixed or calendar-driven), you're building a contract with `fab-test pbir contract init` or checking one with `contract lint`, or a finding's rule starts with `CONTRACT.` |
| [references/operations.md](references/operations.md) | You need `--dry-run`/verbosity behavior, the on-disk result layout, tool-resolution order, or pre-flight checks |
| [references/source-files.md](references/source-files.md) | You're navigating or modifying the `fab-test` implementation itself |
| [references/data-agent.md](references/data-agent.md) | You're writing, editing, linting or running a Data Agent test suite (`fab-test data-agent`, `tests init`, `tests lint`), or one failed |
| [references/run-manifest.md](references/run-manifest.md) | You're reading `fab-test-results/run.json`: its fields, statuses, `detail`, `target.scope` or `execution` |
| [references/discoverability.md](references/discoverability.md) | You need what `doctor`, `list` or `explain` check, or you're parsing `doctor --format json` or `doctor --local --format json` |
