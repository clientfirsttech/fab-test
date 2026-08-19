# Project Plan

Guiding vision and constraints: [vision.md](vision.md)

## Active Epics

- [Local Desktop First Run](tasks/local-desktop-first-run-epic.md) — Give a Power BI developer with a `.pbip` open in Desktop real results in one command, no cloud required. **14 tasks.**
- [Config Consolidation](tasks/config-consolidation-epic.md) — One config front door, one precedence rule, rule overlays instead of forked rule files. **13 tasks**, 1 deferred.

## Standalone Tasks

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

## Suggested Order

1. **Local Desktop First Run** — consumes `doctor` and the run manifest (now shipped) to deliver the fastest adoption path.
2. **Config Consolidation** — collapses config sprawl once the surfaces that need configuring are known.

## Completed Epics

- [CLI Global Options](tasks/cli-global-options-epic.md) — Added `--help` epilog and `--version`/`-V` to the `fab-test` CLI.
- [CLI Quality Backlog](tasks/archive/2026-08-18-cli-quality-backlog-epic.md) — Hardened `fab-test` into a predictable, fast, and CI-friendly CLI (exit codes, input validation, checksum verification, `--timeout`/`--jobs`/config-file support, `clean-tools`, shell completions, subcommand aliases, per-artifact progress).
- [Telemetry Context](tasks/archive/2026-08-18-telemetry-context-epic.md) — Analyzer telemetry now always carries repository, branch, actor, and run context (local git fallback, `origin` field, machine context + PII redaction, payload schema validation, `--telemetry --dry-run` preview).
- [CLI Agent Ergonomics](tasks/archive/2026-08-19-cli-agent-ergonomics-epic.md) — Made `fab-test` equally callable by a human and an AI agent: stdout is now provably pure JSON under `--format json` (narration on stderr), exit code `127` for missing prerequisites, a readiness probe backing `doctor`/`list`/`explain`, a `run.json` manifest per invocation, canonical hyphenated subcommand names, and docs updated for all three callers.
