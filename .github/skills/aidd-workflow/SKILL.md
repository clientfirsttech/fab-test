---
name: aidd-workflow
description: Project-specific command resolver for fab-test. Maps user commands to AIDD skill chains for this Python/Fabric/GitHub-Actions project. Load this before any AIDD task in this project.
---

# AIDD Workflow — fab-test

Project-specific command router. Read this file to discover which skills to load for each user command in this Python + Microsoft Fabric project.

## Pre-Flight

Constraints {
  Always read vision.md before executing any task or plan command
  (vision conflict detected) => stop, explain the conflict, ask user to resolve before proceeding
  (project language is Python) => skip JS/TS skills: aidd-javascript, aidd-lit, aidd-react, aidd-autodux, aidd-ecs
  (task writes or reviews Python) => load aidd-python — it is the language skill the JS/TS skills would otherwise have supplied
  (task adds to, or reviews a diff touching, a file over 400 lines) => load aidd-module-budgets
  (task involves Fabric deployment) => load fabric-cicd-deployment first
  (task involves code changes) => use aidd-tdd — write tests before implementation
  All skills resolve to: .github/skills/<skill-name>/SKILL.md
  Epic files: tasks/<epic-name>-epic.md
}

## Command Map

| User says | Skills to load | Notes |
|-----------|---------------|-------|
| help, list commands | `aidd-please` | List commands without modifying files |
| plan, what's next, priorities | `aidd-please` | Review plan.md, suggest next steps |
| discover, user journey, user story, feature | `aidd-product-manager`, `aidd-please` | Interactive product discovery |
| task, create epic, plan task | `aidd-task-creator`, `aidd-please`, `aidd-tdd`, `aidd-python` | Plan + TDD execution |
| execute epic, run epic | `aidd-task-creator`, `aidd-please` | Execute a previously planned epic |
| review, code review | `aidd-review`, `aidd-python`, `aidd-module-budgets`, `aidd-please` | Quality + security review |
| churn, hotspots, refactoring candidates | `aidd-churn`, `aidd-please` | Hotspot ranking by LoC × churn × complexity |
| fix bug, fix, aidd-fix | `aidd-fix`, `aidd-python`, `aidd-please` | Structured bug-fix workflow |
| user test, test script | `aidd-user-testing`, `aidd-please` | Generate human/AI test scripts |
| run test, execute test | `aidd-user-testing`, `aidd-please` | Execute AI agent test |
| log, log changes, changelog | `aidd-log`, `aidd-please` | Document completed work |
| commit, create commit | `aidd-please` | Conventional commit |
| deploy, deployment, fabric deploy | `fabric-cicd-deployment` | Fabric artifact deployment pattern |
| requirements, functional spec, given/should | `aidd-requirements` | Write functional requirements |
| pr, pull request, review comments | `aidd-pr`, `aidd-please` | Triage + address PR review comments |
| parallel, fan out, sub-agents | `aidd-parallel`, `aidd-please` | Delegate to parallel sub-agents |
| pipeline, step-by-step pipeline | `aidd-pipeline`, `aidd-please` | Run a markdown task list as pipeline |
| security, jwt, timing | `aidd-jwt-security` or `aidd-timing-safe-compare` | Security review |
| upskill, create skill | `aidd-upskill`, `aidd-sudolang-syntax` | Author a new AIDD skill |
| document, update docs, sync docs, update readme | `document` | Sync README, QUICK-VALIDATION, and fab-test skill with codebase |

## Project-Specific Skills

| Skill | Purpose |
|-------|------|
| `aidd-workflow` | This file — project command resolver |
| `aidd-python` | Python best practices, simplicity budgets, over-engineering review lens |
| `aidd-module-budgets` | File-level size budgets, split seams for oversized modules |
| `fabric-cicd-deployment` | Metadata-driven Fabric deployment via environments.yml |
| `document` | Sync docs: README, QUICK-VALIDATION, fab-test skill |
| `fab-test` | fab-test CLI reference — subcommands, flags, result locations |

## Loading Protocol

resolveCommand(userInput) {
  1. Read vision.md
  2. Read this file (.github/skills/aidd-workflow/SKILL.md)
  3. Match userInput to the Command Map above
  4. Load the command file at .github/commands/[command-name].md
  5. Load each listed skill from .github/skills/<name>/SKILL.md
  6. Execute the workflow defined in the loaded skills
}
