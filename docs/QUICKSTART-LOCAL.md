# Quickstart: local Desktop workflow

The fastest way to get real findings from `fab-test`: a `.pbip` open in Power BI Desktop, no `fabric-artifacts` layout, no Fabric workspace, no service principal.

The project must be saved in PBIP format with the semantic model in **TMDL** and the report in **PBIR** — that is what BPA and PBIR Inspector read. See [Assumed project format](../README.md#assumed-project-format) for the layout and how to turn both on in Power BI Desktop.

## From install to first findings

```bash
# 1. Install the beta from PyPI
#    The exact pin is required because pip skips pre-releases (or pass --pre).
#    The package is cft-fab-test; the command it installs is still fab-test.
pip install "cft-fab-test==1.9.0b8"

# 2. Check what's ready
fab-test doctor --local

# 3. See the plan before running anything
fab-test local --dry-run

# 4. Run it
fab-test local
```

Four commands. Step 2 tells you exactly what's missing and how to fix it before you spend time on step 4.

## What runs without any cloud access

`fab-test local` discovers every `.pbip` project under `--artifact-dir` (default: the repository root — wherever your `.pbip` actually lives, not a fixed folder) and runs:

| Analyzer | Needs |
|----------|-------|
| BPA (Tabular Editor Best Practice Analyzer) | Tabular Editor, downloaded automatically on first run |
| PBIR Inspector | PBIR Inspector, downloaded automatically on first run |
| `pql-test` (DAX/PQL tests) | Nothing extra — connects to your open Desktop instance automatically |

None of these need a Fabric workspace, a service principal, or a network call beyond the one-time tool download. An analyzer whose prerequisite is missing is **skipped with a remediation hint**, not a failure — `fab-test local`'s exit code only reflects real findings, never a missing tool.

## Checking readiness first

```bash
fab-test doctor --local
```

reports, in order: your Python version, whether a Power BI Desktop instance is running, whether the Desktop Bridge CLI is on `PATH` (used for report-render checks — not yet wired into `fab-test local` itself), and each of the four analyzers above. The last line states exactly which analyzers `fab-test local` will run given what it found:

```
✅ python: 3.12.10 — /usr/bin/python3.12
❌ desktop: no running instance detected
   → Open a .pbip file in Power BI Desktop
❌ desktop-bridge: not found on PATH
   → npm install -g @microsoft/powerbi-desktop-bridge-cli (preview; report-render checks only)
✅ bpa: resolved via cached download
✅ pbir: resolved via cached download
✅ pql_test: pql-test is a fab-test dependency

fab-test local would run: bpa, pbir, pql_test
```

Add `--format json` for a single machine-readable document instead.

## DAX tests against your open Desktop instance

If you have the `.pbip` open in Power BI Desktop, `fab-test local` (via `pql-test`) connects to it automatically — no `--workspace-id`, no credentials. `fab-test local`'s subparser doesn't even expose a `--workspace-id` flag, so there's no way to accidentally reach for a Fabric workspace from the local path. The run manifest (`fab-test-results/run.json`) records `"origin": "local"` and, when a Desktop instance was matched, a `"desktop"` field on the `pql_test` envelope naming the port and model it bound to.

## Moving to CI later

Nothing about the contract changes. The same envelope schema, `status` values, and result layout apply whether a project runs locally or in a pipeline — the manifest's `origin` field is the only thing that differs (`local` vs. the detected CI system, e.g. `github-actions`). See [QUICK-VALIDATION.md](QUICK-VALIDATION.md) for the CI-oriented walkthrough and a copy-pasteable workflow snippet.
