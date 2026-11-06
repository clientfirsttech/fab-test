# ODCS Contract Analyzer Epic

**Status**: 📋 PLANNED — needs discovery before any task is approved.
**Goal**: decide whether and how fab-test exposes `pql-test contract`, the ODCS data-contract commands added in `pql-test` 0.2.0.

## Overview

`pql-test` 0.2.0 adds a `contract` command group (lint, coverage, generate, trace) that works from PBIP files and so runs off Windows too, unlike `run-tests`. It reads [Open Data Contract Standard](https://github.com/bitol-io/open-data-contract-standard) contracts (schemas 3.0.2–3.2.0) and maps them to PQL.Assert DAX tests. fab-test currently wraps only `run-tests`. Follows [pql-test 0.2.0 Update](pql-test-0-2-0-epic.md), which only moves the pin.

Questions discovery must answer first:

1. **Who is the user and what is the pain?** Who writes ODCS contracts for semantic models, and would they run `contract lint` through fab-test rather than `pql-test` directly?
2. **One analyzer or an extension of `pql-test`?** `contract lint` is static (like `rdl`, `bpa`); `generate` writes files, which fab-test's analyzers do not do today.
3. **What are the commands' output and exit contracts?** Read the installed `pql-test contract --help` and its `--format json` output before designing the envelope.
4. **Registration cost.** `aidd-analyzer-contract` lists every touch point (envelope, exit codes, report, telemetry, registry, docs, skill); the Feature Flags epic lets it merge to `dev` switched off.

Nothing is decided; discovery runs `aidd-product-manager` before tasks are written. Quality gates will be the last task.
