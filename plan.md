# Project Plan

Guiding vision and constraints: [vision.md](vision.md)

## Active Epics

- [CLI Agent Ergonomics](tasks/cli-agent-ergonomics-epic.md) — Make `fab-test` equally callable by a human at a prompt and by an AI agent parsing stdout. **14 tasks.**
- [Local Desktop First Run](tasks/local-desktop-first-run-epic.md) — Give a Power BI developer with a `.pbip` open in Desktop real results in one command, no cloud required. **14 tasks.**
- [Config Consolidation](tasks/config-consolidation-epic.md) — One config front door, one precedence rule, rule overlays instead of forked rule files. **13 tasks**, 1 deferred.

## Standalone Tasks

- **Wire coverage enforcement** — add `pytest-cov` to the `dev` optional-dependency group, scope `[tool.coverage.run]` to `src/`, and put `--cov-fail-under=80` in the CI invocation only (never `pytest.ini`, which would fail every granular marker run). Makes the `vision.md` coverage constraint enforceable rather than aspirational.

## Suggested Order

1. **CLI Agent Ergonomics** — establishes the contract (`doctor`, `list`, JSON stdout, exit codes, run manifest) the other two build on.
2. **Local Desktop First Run** — consumes `doctor` and the run manifest to deliver the fastest adoption path.
3. **Config Consolidation** — collapses config sprawl once the surfaces that need configuring are known.

## Completed Epics

- [CLI Global Options](tasks/cli-global-options-epic.md) — Added `--help` epilog and `--version`/`-V` to the `fab-test` CLI.
- [CLI Quality Backlog](tasks/archive/2026-08-18-cli-quality-backlog-epic.md) — Hardened `fab-test` into a predictable, fast, and CI-friendly CLI (exit codes, input validation, checksum verification, `--timeout`/`--jobs`/config-file support, `clean-tools`, shell completions, subcommand aliases, per-artifact progress).
- [Telemetry Context](tasks/archive/2026-08-18-telemetry-context-epic.md) — Analyzer telemetry now always carries repository, branch, actor, and run context (local git fallback, `origin` field, machine context + PII redaction, payload schema validation, `--telemetry --dry-run` preview).
