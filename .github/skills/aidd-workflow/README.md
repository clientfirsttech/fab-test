# aidd-workflow

Project-specific command resolver for the `fab-test` package in the
`fab-test` repository. Maps natural-language user commands to the
correct AIDD skill chain for a Python + Microsoft Fabric + GitHub Actions project.

## Why

The upstream AIDD framework ships a generic `ai/commands/` directory for command
resolution. This project migrated that layer to `.github/skills/aidd-workflow/`
(Phase 5.1) so all agent guidance lives under `.github/` and is picked up by
VS Code Copilot automatically.

## What it does

1. Enforces pre-flight constraints (read `vision.md` first, skip JS skills, use TDD)
2. Maps every user trigger phrase to the exact AIDD skills to load
3. Surfaces project-specific skills (`fabric-cicd-deployment`)

## When to use

This file is loaded automatically by the `aidd.agent.md` workflow protocol before
any AIDD command. You can also reference it directly when unsure which skill to
invoke for a given request.
