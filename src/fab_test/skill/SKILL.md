---
name: fab-test
description: fab-test CLI reference for running Fabric artifact analyzers locally (fab-test 1.9.0b6). Covers all subcommands, flags, artifact isolation, result locations, and how fab-test differs from pytest. Use when invoking, troubleshooting, or extending local artifact validation.
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

From a checkout:

```bash
pip install -e .
```

From PyPI — the package is **`cft-fab-test`** (the command is still
`fab-test`). The current release is a beta, and pip skips PEP 440
pre-releases unless you pass `--pre` or name the version exactly:

```bash
pip install "cft-fab-test==1.9.0b6"     # or: pip install --pre cft-fab-test
```

`fab-test playwright` has its own install path. It runs its render spec as a
`python -m pytest` child, and those pytest packages are an extra, not base
dependencies. Install the extra plus the browser before the first run:

```bash
pip install "cft-fab-test[playwright]"  # pytest, pytest-playwright, pytest-html, pytest-xdist
playwright install chromium             # Linux CI: playwright install --with-deps chromium
```

Without the extra, `fab-test playwright` stops before minting any embed token
and its error names the missing packages and that `pip install` command.
`--plan-only` needs neither.

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

A default run states its result several ways for a person to skim. An agent that only needs to know whether it passed should ask for less. **Make `-q` the first invocation** and escalate only if it fails: re-run with `-v`, or read the envelope path `-q` prints, to learn why.

```
OutputBudget {
  fn choose(need) {
    (only pass/fail and where the result is)   => fab-test ANALYZER -q               // ~10x smaller than default
    (the result's fields, parsed)              => fab-test ANALYZER --format json 2>/dev/null
    (why one rule fired on one artifact)       => read the envelope path -q printed, or re-run with -v
  }
}

QuietLine {
  shape: "<analyzer> <status> e=<errors> w=<warnings> <where>"
  analyzer: the registry name, so "pql_test" and never "pql-test"
  status: "passed" | "warning" | "failed" | "skipped"
  where: envelope path relative to the working directory; the artifact name when the analyzer wrote no envelope. Always the last field, because artifact names contain spaces
}

Constraints {
  -q prints exactly one QuietLine per artifact and nothing else on a passing run; exit codes and every file under fab-test-results/ are unchanged
  -q and -v together exit 2
  (-q and a failure the findings cannot explain: a preflight failure, a timeout, or a nonzero exit with no findings) => the remediation or the analyzer's own output is still printed
  (-q --format json) => stdout is byte-identical to the same run without -q, and stderr is silent for passing artifacts
  (CI is detected) => -q still passes the analyzer's ::error:: and ::warning:: annotations through, verbatim
  (the same remediation applies to every artifact) => it is printed once per run, not once per artifact
  Precedence: -q/-v flag > ANALYZER_VERBOSITY > `verbosity:` in fab-test.yml > default. Levels: summary (= -q), default, verbose (= -v), debug (= -vv)
}
```

```bash
fab-test bpa -q                     # bpa warning e=0 w=103 fab-test-results/bpa/SampleModel-PQLAssert/envelope.json
fab-test local -q                   # one line per artifact across bpa, pbir, and pql_test
fab-test config --show              # verbosity = 'summary' (fab-test.yml:verbosity)
```

A repository whose agents should always be terse can pin it once with `verbosity: summary` in `fab-test.yml`; a person who wants the full output for one run passes `-v` and it wins. See [references/operations.md](references/operations.md#output-verbosity).

### Discoverability: doctor → list → explain

```
Discoverability {
  fn doctor()          // is each analyzer's tool/credential ready?
  fn doctor(--local)   // readiness for the local Desktop workflow specifically
  fn list()            // what subcommands exist, and how many artifacts match?
  fn explain(analyzer) // what command would `fab-test ANALYZER` actually run?
}

Constraints {
  doctor and list both support --format json
  doctor --analyzer NAME checks exactly one analyzer
  list's matched-artifact counts respect --artifact-dir
  explain ANALYZER never spawns a subprocess — it only shows the resolved command, tool path, rules path, and output path
}
```

```bash
fab-test doctor                       # is each analyzer's tool/credential ready?
fab-test doctor --local               # readiness for the local Desktop workflow specifically
fab-test list                         # what subcommands exist, and how many artifacts match?
fab-test explain bpa                  # what command would `fab-test bpa` actually run?
```

Plain `fab-test doctor --format json` gives every analyzer entry the same shape:

```
DoctorAnalyzerEntry {
  analyzer: String
  ready: Boolean
  resolved_path: String | null
  reason: String
  remediation: String | null
  version: String | null   // null for an analyzer with no wrapped tool of its own (pql_test, playwright, dependencies, telemetry); the resolved pinned version from analyzers.json for one that bootstraps a binary
}

Constraints {
  Every analyzer entry carries all five keys, version included, regardless of readiness
  The download cache is keyed by version, so bumping the pin in a fab-test upgrade downloads the new binary rather than reusing whatever an older checkout cached
  (a local override — an env var or a default_path file — shadows the declared pin) => reason names the variable or file and states the resolved tool will not receive automatic updates, a state a user in it can't fix by upgrading fab-test alone
}
```

See [docs/RELEASE.md](https://github.com/clientfirsttech/fab-test/blob/main/docs/RELEASE.md#bumping-a-wrapped-tools-pin) for how a pin gets bumped and delivered.

```bash
fab-test doctor --format json
```
```json
{
  "analyzers": [
    {"analyzer": "bpa", "ready": true, "resolved_path": "C:\\...\\TabularEditor.exe", "reason": "resolved via cached download (version 2.29.0)", "remediation": null, "version": "2.29.0"},
    {"analyzer": "pbir", "ready": true, "resolved_path": "C:\\...\\fab-inspector.exe", "reason": "resolved via cached download (version 3.4.0)", "remediation": null, "version": "3.4.0"},
    {"analyzer": "pql_test", "ready": false, "resolved_path": null, "reason": "no workspace, credentials, or running Desktop instance", "remediation": "Set FABRIC_WORKSPACE_ID ...", "version": null}
  ]
}
```

`doctor --local` checks Python version, whether a Desktop instance is running, the Desktop Bridge CLI's presence (path only — never invoked), and each of `fab-test local`'s four analyzers, then states exactly which ones would run:

```
DoctorLocalCheck {
  check: String            // "python" | "desktop" | "bpa" | "pbir" | ...
  ready: Boolean
  reason: String
  resolved_path: String | null
  remediation: String | null
  version                  // present only for the bootstrapped checks (bpa, pbir) — absent, not null, for python/desktop/desktop-bridge/pql_test, which have no tool version of their own
}

Constraints {
  Only the bootstrapped checks (bpa, pbir) carry version here
  The plain (non --local) doctor above is the one with the uniform five-key shape
}
```

```bash
fab-test doctor --local --format json
```
```json
{
  "checks": [
    {"check": "python", "ready": true, "reason": "3.12.10", "resolved_path": "/usr/bin/python3.12", "remediation": null},
    {"check": "desktop", "ready": false, "reason": "no running instance detected", "resolved_path": null, "remediation": "Open a .pbip file in Power BI Desktop"},
    {"check": "bpa", "ready": true, "reason": "resolved via cached download (version 2.29.0)", "resolved_path": "C:\\...\\TabularEditor.exe", "remediation": null, "version": "2.29.0"}
  ],
  "would_run": ["bpa", "pbir", "pql_test"]
}
```

### The run manifest (`fab-test-results/run.json`)

```
RunManifest {
  schema_version: Integer
  fab_test_version: String
  origin: "local" | "github-actions" | "gitlab-ci" | "circleci" | "azure-devops"
  target: Target | null
  command: String[]        // sanitized — see Constraints below
  artifacts: ArtifactResult[]
  totals { errors: Integer, warnings: Integer }
  telemetry_error: String | null
  exit_code: Integer
}

Target {
  raw: String
  scope: "path" | "desktop" | "workspace"
  name: String
  type: String | null
  workspace: String | null
  workspace_id: String | null   // the GUID resolved from a workspace name; names a workspace and grants access to nothing, so it is safe to record
  path: String | null
}

ArtifactResult {
  analyzer: String
  artifact: String
  status: "passed" | "failed" | "skipped" | "timeout" | "preflight_failed"
  envelope_path: String | null
  errors: Integer
  warnings: Integer
  detail: String | null
}

Constraints {
  Every analyzer invocation (a single subcommand or `all`) writes exactly one run.json under --output-dir (default fab-test-results/), so a caller reads one file instead of globbing result directories
  ("timeout" or "preflight_failed") => the run was aborted without producing a result to report
  (the run ended without a result to report) => detail carries the human-readable reason: the resolved remediation message for preflight_failed, the exceeded duration for timeout, or the analyzer's own error message when it exited non-zero before writing an envelope (status "failed", envelope_path null)
  (the analyzer did write an envelope, however it failed) => detail is null; the findings are the reason, and envelope_path points at them
  run.json alone is always enough to learn what to fix — a caller never has to fall back to stderr, which matters when run.json is the only file a pipeline uploads
  (no CI environment variable is detected) => origin = "local"
  (a CI system is detected) => origin = its name ("github-actions" | "gitlab-ci" | "circleci" | "azure-devops")
  The envelope schema, status values, and result layout are identical whether origin is local or CI — origin is the only field that differs between a local run and a CI run
  (target is null) => the run discovered artifacts instead of being pointed at one
  Branch on target.scope ("path" | "desktop" | "workspace") rather than parsing target.raw
  Where origin distinguishes local from CI, target.scope distinguishes whether the run read files on disk, a running Desktop instance, or a deployed workspace item — a distinction origin alone never answers
  command has every known credential flag (--client-secret, --password, --token, --secret, --api-key) and any key=value-shaped token redacted before the file is written — no credential ever appears in the manifest
  (this run's telemetry was delivered to every configured destination, or none was asked for) => telemetry_error = null
  (telemetry failed) => telemetry_error names why: an unreachable cluster, an unreachable OneLake endpoint, a missing install extra, a missing permission grant. One destination's failure never blocks the other's delivery; if both fail, telemetry_error names both, prefixed by destination
  telemetry_error never changes exit_code — telemetry is diagnostic and must not fail a build. See [Telemetry](references/configuration.md#telemetry)
  doctor, list, explain, auth, and clean-tools never write a manifest — they don't run an analyzer
}
```

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

The case a pipeline meets most is a `detail` populated on an aborted run: `fab-test playwright --artifact ThinReport` with no `--env` aborts before authenticating, and `detail` carries `No environment given, so there is nothing to resolve 'ThinReport' against. Pass --env, ...`.

## Subcommands

```
 fab-test bpa              — Tabular Editor Best Practice Analyzer (SemanticModel artifacts)
 fab-test pbir             — PBIR Inspector static report analysis (Report artifacts)
 fab-test a11y             — pbir-a11y accessibility checks (Report artifacts) — opt-in, not run by `fab-test all`
 fab-test rdl              — RDL static analysis: the active rules for paginated reports (.rdl files) — no external tool
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

## Reference files

| File | Read it when... |
|------|------------------|
| [references/targeting-and-discovery.md](references/targeting-and-discovery.md) | You need the `TARGET` grammar, per-analyzer scope rules, or how artifact discovery walks and prunes a directory tree |
| [references/credentials.md](references/credentials.md) | You need to know how `fab-test` resolves an identity, or what `auth status`/`auth login` do |
| [references/reports.md](references/reports.md) | You're generating or debugging the HTML `--report` output, the per-run index, or its search/sort/filter behavior |
| [references/configuration.md](references/configuration.md) | You're touching `fab-test.yml`, precedence, telemetry, rule overlays, or metadata-file resolution |
| [references/flags.md](references/flags.md) | You need the full global flag table or a specific subcommand's flags (`bpa`, `pbir`, `a11y`, `rdl`, `pql-test`, `playwright`, `playwright-impact`, `dependencies`, `all`, `local`) |
| [references/operations.md](references/operations.md) | You need `--dry-run`/verbosity behavior, the on-disk result layout, tool-resolution order, or pre-flight checks |
| [references/source-files.md](references/source-files.md) | You're navigating or modifying the `fab-test` implementation itself |
