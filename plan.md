# Project Plan

Guiding vision and constraints: [vision.md](vision.md)

## Active Epics

- [Artifact Targeting and Auth](tasks/artifact-targeting-and-auth-epic.md) — 📋 PLANNED. One grammar for naming any artifact (`./Sales.SemanticModel`, `local/Sales`, `"Sales Dev.Workspace/Sales.SemanticModel"`), plus a read-only `auth status` and a delegating `auth login` that stores no credentials. **10 tasks**, 2 deferred. Config Consolidation shipped the `.env` auto-discovery and `DefaultAzureCredential` fallback that tasks 7–9 were waiting on, so every task is unblocked.

## Standalone Tasks

- **Fix AIDD framework drift** — [.github/agents/aidd.agent.md](.github/agents/aidd.agent.md) has fallen out of sync with [aidd-workflow/SKILL.md](.github/skills/aidd-workflow/SKILL.md), the resolver it is supposed to front. Two defects:

  1. **Dead path.** Workflow Protocol step 3 and Loading Protocol step 4 both read `.github/commands/[command-name].md`. That directory does not exist, so both steps silently no-op on every command.
  2. **Missing commands and skills.** The Available Commands table omits `document`, `requirements`, `pr`, `parallel`, `pipeline`, `upskill`, and `deploy`; the Skill Locations list omits `document`, `fab-test`, and `aidd-python`. All exist under `.github/skills/`.

  The consequence worth fixing: the documentation-as-done rule from [vision.md](vision.md) reaches an agent only via the workflow resolver's `document` row. Enter through the agent file — which presents itself as the front door — and nothing says an epic is incomplete until the `fab-test` skill is updated. Add the rule to the agent file's Core Principles so it survives either entry point. Deliberately not bundled into the Artifact Targeting and Auth branch, to keep that scoped to the CLI.

- **Wire up the Power BI Desktop Bridge CLI** — deferred from Local Desktop First Run tasks 6-8. `doctor --local` already detects the bridge's presence (path only), but report-render capture (`invoke_desktop_report.py`, screenshot storage) needs its actual `status`/`screenshot`/`screenshot-all` command output schema, which couldn't be verified from the npm README (blocked) or any example output, and there's no live Desktop session in this environment to check against. Revisit once the schema is confirmed from a real installation or Microsoft's docs stabilize (currently preview, dated July 2026).
- **Wire coverage enforcement** — add `pytest-cov` to the `dev` optional-dependency group, scope `[tool.coverage.run]` to `src/`, and put `--cov-fail-under=80` in the CI invocation only (never `pytest.ini`, which would fail every granular marker run). Makes the `vision.md` coverage constraint enforceable rather than aspirational. The `dev` group now exists, so this is the only missing piece.
- **Reduce analyzer complexity** — the lint gate is clean, but the non-gating complexity report in `build.yml` still shows 36 findings across `src/`, concentrated in seven functions. Each is a wrapper that grew argument parsing, tool resolution, execution, and envelope writing into one body; the split is the same every time. Ranked worst first:

  | Function | Complexity | File |
  |----------|-----------|------|
  | `run_bpa` | 30 | [invoke_tabular_editor_bpa.py](src/fabric_ci_cd_dataops/scripts/invoke_tabular_editor_bpa.py) |
  | `run_inspector` | 24 | [invoke_pbir_inspector.py](src/fabric_ci_cd_dataops/scripts/invoke_pbir_inspector.py) |
  | `run_pql_test` | 23 | [invoke_pql_test.py](src/fabric_ci_cd_dataops/scripts/invoke_pql_test.py) |
  | `validate_environments_yaml` | 22 | [validate_environments_yaml.py](src/fabric_ci_cd_dataops/scripts/validate_environments_yaml.py) |
  | `_print_all_summary` | 18 | [fab_test_summary.py](src/fabric_ci_cd_dataops/scripts/fab_test_summary.py) |
  | `resolve_executable` | 17 | [_analyzer_tool_bootstrap.py](src/fabric_ci_cd_dataops/scripts/_analyzer_tool_bootstrap.py) |
  | `main` | 16 | [deploy.py](src/fabric_ci_cd_dataops/scripts/deploy.py) |

  Budgets and the review lens are in [aidd-python](.github/skills/aidd-python/SKILL.md). Raise a threshold only with a reason in the commit message.

## Completed Epics

- [CLI Global Options](tasks/cli-global-options-epic.md) — Added `--help` epilog and `--version`/`-V` to the `fab-test` CLI.
- [CLI Quality Backlog](tasks/archive/2026-08-18-cli-quality-backlog-epic.md) — Hardened `fab-test` into a predictable, fast, and CI-friendly CLI (exit codes, input validation, checksum verification, `--timeout`/`--jobs`/config-file support, `clean-tools`, shell completions, subcommand aliases, per-artifact progress).
- [Telemetry Context](tasks/archive/2026-08-18-telemetry-context-epic.md) — Analyzer telemetry now always carries repository, branch, actor, and run context (local git fallback, `origin` field, machine context + PII redaction, payload schema validation, `--telemetry --dry-run` preview).
- [CLI Agent Ergonomics](tasks/archive/2026-08-19-cli-agent-ergonomics-epic.md) — Made `fab-test` equally callable by a human and an AI agent: stdout is now provably pure JSON under `--format json` (narration on stderr), exit code `127` for missing prerequisites, a readiness probe backing `doctor`/`list`/`explain`, a `run.json` manifest per invocation, canonical hyphenated subcommand names, and docs updated for all three callers.
- [Run Manifest Failure Detail](tasks/archive/2026-08-19-run-manifest-failure-detail.md) — Abort-path manifest entries (`preflight_failed`, `timeout`) now carry the actual failure message, not just the status enum.
- [Local Desktop First Run](tasks/archive/2026-08-19-local-desktop-first-run.md) — 10/14 tasks: `.pbip` discovery anywhere in a repo, Power BI Desktop instance detection, DAX tests bound to a running Desktop instance with no workspace ID, `fab-test local` (the no-cloud analyzer bundle) with its own `--dry-run` plan and `doctor --local`, a `run.json` `origin` field distinguishing local from CI, and docs for all three callers. Deferred: Desktop Bridge CLI integration (tasks 6-8, see Standalone Tasks). Local-config scaffolding (its task 13) is now resolved by Config Consolidation's `fab-test init`.
- [Config Consolidation](tasks/archive/2026-08-20-config-consolidation.md) — One config front door (`fab-test.yml`, optional, additive), one precedence rule (CLI flag > env var > config file > packaged default) with origin tracking via `fab-test config --show`, a rule-overlay engine so tuning one BPA/PBIR rule never means forking the ruleset, `DefaultAzureCredential` fallback when no service principal is configured, a published JSON schema, `fab-test init` to scaffold the first config, and a full backward-compatibility sweep. 13/13 tasks; 1 deferred (Shared Base Configuration — an `extends:` key — cut under the simplicity constraint until a second organization actually needs it).
