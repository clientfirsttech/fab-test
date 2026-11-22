# Authoring Command Grammar Epic

**Status**: ✅ IMPLEMENTED 2026-11-19 on `feature/authoring-command-grammar`, AIDD-reviewed and gates passed; merged to `dev` (#71). Decisions 1–3 are the user's; 4–9 were proposed by Claude and accepted by the user 2026-11-19, along with lint printing only and its exit codes.
**Goal**: every command that authors a test file follows one grammar, written as an AIDD skill that is loaded when a command is planned and when one is reviewed, and the PBIR contract flow runs init → lint → run without leaving fab-test.

Journey: [authoring-command-grammar.yaml](../plan/story-map/authoring-command-grammar.yaml).

## Overview

WHY: PBIR slicer contracts shipped the first authoring flow — `fab-test pbir contract init`, lint, `fab-test pbir`, CI — and the next ones (Data Agent test suites, a possible `playwright` scaffold) will be planned one epic at a time. Nothing makes them reuse its shape. The evidence is already in the repo: `fab-test init` scaffolds config at the top level, `pbir contract init` is caught by an argv check in `fab_test.py` before argparse (so `help`, `list` and `explain` don't know it exists), the lint step is `pql-test contract lint`, a second tool with its own exit codes, and the Data Agent epic planned `fab-test data-agent init` (it collides with the analyzer's TARGET) with tests inside the `.DataAgent` folder (Fabric's Commit to Git deletes them). Run commands have `aidd-analyzer-contract` to keep them consistent; authoring commands have nothing. This epic adds that skill and wires it into planning and review.

**Decisions**

1. ✅ **Grammar is `fab-test <analyzer> <noun> <verb> [TARGET]`** (user, 2026-11-19). The noun names the file a person authors (`contract`, `tests`); the verb comes from a closed list. The bare analyzer (`fab-test pbir`) runs the check and never writes source files.
2. ✅ **fab-test owns lint** (user, 2026-11-19). Every authoring flow has a `lint` verb with fab-test's exit codes, wrapping the upstream linter where one exists. pbir gets `contract lint` in this epic.
3. ✅ **Scope is the skill and its wiring, plus `pbir contract lint` and aligning `pbir contract init`'s inputs and output modes with the run** (user, 2026-11-19; the init alignment was added the same day after the flag survey). Not in scope: a parser-driven parity test, replacing the argv check with real subparsers, and rewriting the Data Agent epic's decisions. The skill records the first two as known gaps, and plan.md logs all three as standalone tasks.
4. ✅ **Verbs are `init` and `lint`, closed.** `init` creates the authored file from the artifact, or appends to it. `lint` validates it against the artifact without running anything, and needs no service. A third verb is added to the skill only when a second analyzer needs it (vision: no abstraction until the second caller).
5. ✅ **A noun means one file format everywhere.** `contract` is always ODCS; a Data Agent's promptfoo suite is `tests`. Two analyzers share a noun only if they share the format.
6. ✅ **TARGET is always the item, never the authored file.** `init`, `lint` and the run all take `Sales.Report` (or `--artifact NAME` + `--artifact-dir`), and fab-test finds the paired file, so a person learns one argument. `--<noun> FILE` overrides the pairing, as `fab-test pbir --contract` does today.
7. ✅ *(superseded 2026-11-21 by Data Agent decision 22: `fab-tests/<flow>/`, outside the Git-connected folder)* **Authored files live beside the item folder, never inside it**: `<Item>.<Type>.<suffix>` (e.g. `Sales.Report.odcs.yaml`), paired by a stable identity recorded in the file (pbir uses the report's `logicalId`), not by name alone. This applies to files outside the item's definition. Tests that are part of the definition, like T-TEST procedures in a SQL database project, stay inside (refined by the Inventory, 2026-11-19).
8. ✅ **Top-level verbs are about fab-test itself** (`init`, `doctor`, `config`, `list`, `explain`, `skill`, `help`). `fab-test init` stays the repo's config scaffold and never gains an analyzer argument.
9. ✅ **Division of labour with `aidd-polite-review`** (on `dev` since #69): the grammar skill decides a command's *shape* (words, flags, files, exit codes); polite review judges how it *talks* (wording, questions, interruptions). Neither restates the other; the grammar skill names polite review in its intro and its plan step.

**Open question, settled 2026-11-19**: `lint` prints only (text, or one JSON document) and writes no envelope; the run writes results. Characterizing pql-test 0.2.1 also refined the exit codes: for `lint`, any problem in the file, unreadable YAML included, is a finding (1), as pql-test treats it; 2 means there was nothing to check.

---

## Inventory the Authoring Surface

**Status**: ✅ 2026-11-19, in [known-gaps.md](../.github/skills/aidd-command-grammar/references/known-gaps.md). Beyond the lines below, it found `validate-environments-yaml` (a second console script, exit 1 for an unreadable file), refined decision 7 for files that are part of an item's definition, and recorded that `contract init` exits 130 when interrupted, which the skill's exit-code rule should allow.

List every command a person types to create or check an authored file, as built and as planned, and how each departs from decisions 1–8. This becomes the skill's `references/known-gaps.md`.

**Requirements**:
- Given the parser, `fab_test.py`'s argv dispatch and the planned epics, should list each authoring command with its grammar, flags, file placement, exit codes, output modes and where it is discoverable (`--help`, `help`, `list`, `explain`, the fab-test skill).
- Given `pbir contract init`, should record as gaps: dispatched before argparse (not in `help`/`list`/`explain`), and lint done by `pql-test` outside fab-test.
- Given the Data Agent epic, should record decision 3 (tests inside the item folder) and decision 10 (`data-agent init`, a TARGET collision) as gaps to fix before that epic is built.
- Given `fab-test init`, should record it as conforming under decision 8, not as a gap.
- Given `pbir contract init` beside `fab-test pbir` (surveyed 2026-11-19), should record each input or output that differs:
  - `--artifact` is the primary way to name a report on init (metavar `NAME`) but a deprecated alias for TARGET on the run (metavar `STEM`).
  - `--artifact-dir` on init defaults to `.` and ignores `artifact_dir` in `fab-test.yml`/`pyproject.toml`; the run honours it.
  - `--format` on init defaults to `text` and ignores the config's `format`; the run honours it. (Verbosity already resolves flag → `ANALYZER_VERBOSITY` → `fab-test.yml` on both.)
  - `-q` prints nothing on a successful init but one line per artifact on the run.
  - `--dry-run` means "print the file instead of writing it" on init and "list the artifacts without running" on the run.
  - The skill's flag reference ([flags.md](../src/fab_test/skill/references/flags.md)) lists init's flags without `-q`/`-v`, which only the walkthrough documents.

---

## Grammar Skill

**Status**: ✅ 2026-11-19. `SKILL.md` (99 body lines, ~1.6k tokens) and `references/checklist.md`; validate-skill checks pass (emulated).

Write `.github/skills/aidd-command-grammar/SKILL.md`, shaped like `aidd-analyzer-contract`: a short contract, Constraints, `planCommand` and `reviewCommand` processes, and `references/checklist.md` + `references/known-gaps.md`.

**Requirements**:
- Given the skill, should state decisions 1 and 4–8 as Constraints, plus the shared `init` flags: `--questions` (with `--format json`: each question, its suggested answer and `needs_human`), `--answers FILE`, `--dry-run`, `--force` to change existing entries (new entries append and ids are kept), `-q`/`-v`/`--format json`, and refusal of run-only flags (`--report`, `--open-report`, `--telemetry`) naming the command that takes them.
- Given an input flag shared by the verbs and the run (TARGET, `--artifact`, `--artifact-dir`, `--as-of`, `--<noun> FILE`), should require one name, metavar, help text and default on every one of them, each default resolved flag → env → `fab-test.yml` → packaged, as the run resolves it.
- Given output, should require the vision's modes on every verb with the run's meanings: `-q` prints one line per item (the result, e.g. `✓ Sales.Report.odcs.yaml written`), the default adds what a person acts on (the next step), `-v` adds per-item detail (each rule, added/kept/replaced), and `--format json` keeps stdout to one document. `--format` and verbosity resolve from flags, then env, then `fab-test.yml`, never a hard-coded default.
- Given `--dry-run`, should give it one meaning on every verb: show what would be written or run, and write nothing. `--output-dir` belongs only to a verb that writes under `fab-test-results/`.
- Given a caller that can't answer a prompt (no TTY, CI, or `--format json`), should require `init` to refuse with exit 2 naming `--questions`/`--answers` before asking anything, never to prompt or guess.
- Given exit codes, should give every authoring verb the same meanings: 0 done or clean, 1 lint findings, 2 usage error, unreadable file or refusal, 127 a missing wrapped tool, 130 interrupted.
- Given any authoring verb's output, should name the next step (`init` → `lint` → run → the CI snippet) in text, and as a `next` field in JSON.
- Given discoverability, should require each verb to appear in the analyzer's `--help`, `fab-test help`, `list --format json`, and the fab-test skill's flag reference.
- Given documentation, should require one table per flow in the fab-test skill's flag reference and the guide, with a row per flag and a column each for `init`, `lint` and the run, so a caller sees which inputs and output modes carry across steps and which are refused.
- Given documentation, should require each flow to have a walkthrough with the same steps (save the artifact, init, lint, run, break it, CI) and an init-to-CI flowchart, as `docs/SLICER-CONTRACTS-WALKTHROUGH.md` has.
- Given `/command-grammar plan [analyzer noun]`, should output the touch-point list and the epic's Given/should lines; given `/command-grammar review`, should report each unmet Constraint with its checklist row.
- Given `aidd-upskill`'s limits, should pass the validate-skill checks (emulated in Python: `aidd-` prefix, frontmatter under 100 tokens, body under 160 lines and 5000 tokens, `# Title` and `## Process`).

---

## Wire It Into Planning and Review

**Status**: ✅ 2026-11-19. aidd-workflow (Pre-Flight, the task and review rows, Project-Specific Skills, and a discovery question), aidd-review's Criteria, and aidd-analyzer-contract's scope line. The AIDD agent's copy of the command table (`.github/agents/aidd.agent.md`) was missed here and found by `test_aidd_command_map.py` at the task 6 checkpoint; fixed then.

Make the skill load on its own, so consistency doesn't depend on anyone remembering it.

**Requirements**:
- Given `aidd-workflow`'s Pre-Flight, should add: (task plans, adds, reviews or changes a subcommand, verb, noun, or flag a person types) => load aidd-command-grammar.
- Given `aidd-workflow`'s Command Map, should add `aidd-command-grammar` to the "task, create epic" and "review" rows, and list it under Project-Specific Skills.
- Given `aidd-review`'s Criteria, should add a line to use /aidd-command-grammar on any diff that touches the parser, `fab_test.py`'s dispatch, or an `init`/`lint` module.
- Given `aidd-analyzer-contract`, should say in one line that run commands are its scope and authoring verbs are aidd-command-grammar's, and link to it.
- Given `aidd-product-manager` discovery for a new analyzer, should prompt for the authored file's noun and placement as a discovery question (via aidd-workflow's "discover" row, not by editing the upstream skill).

---

## Skill Evals

**Status**: ✅ 2026-11-19. Three fixtures (plan Data Agent tests; review a breaking and a conforming transcript), 15/15 assertions at `--runs 1`; dated output moved aside.

Prove the skill changes what an agent plans and catches, with riteway AI evals in `ai-evals/aidd-command-grammar/` (`npx -y riteway@9.3.0 ai ... --runs 1`; move the dated output aside, don't commit it).

**Requirements**:
- Given a request to plan Data Agent test authoring, should plan `fab-test data-agent tests init` and `tests lint` with the suite beside `NAME.DataAgent/`, never `data-agent init` or a file inside the folder.
- Given a diff adding a top-level `fab-test lint` or an `init` without `--answers`, should report each as a finding with its checklist row.
- Given a diff that follows the grammar, should report no grammar findings.
- Given each fixture, should be unambiguous on its own (see the polite-review evals: a fixture that half-matches a real gap draws a legitimate finding).

---

## Align `pbir contract init` With the Run

**Status**: ✅ 2026-11-19. `-q` prints `contract written added=N replaced=N kept=N unchanged=N PATH` (the run prints `pbir failed e=1 w=0 PATH`). Verified through the console script under -q, the default, -v, `--format json`, `--questions`, `--answers`, `--dry-run`, a refused `--report`, no terminal, and `fab-test.yml` defaults. A broken `fab-test.yml` already crashes every command at import, init included, so it isn't treated differently here; logged in plan.md.

Fix the init-vs-run differences the inventory recorded, so init, lint and the run share inputs and output modes (user, 2026-11-19). TDD each one; remove its row from `known-gaps.md` when it passes.

**Requirements**:
- Given `artifact_dir` or `format` in `fab-test.yml`/`pyproject.toml`, or the matching env var, should resolve init's `--artifact-dir` and `--format` defaults the way the run does (flag → env → file → packaged), and a broken config should not stop init from reading the flags, as verbosity already handles.
- Given `--artifact`, should keep it working on init with the same metavar and help as the run (an alias for TARGET), so `--help` reads the same on both.
- Given `-q` on a successful init, should print one result line (`✓ <contract path> written`, or `unchanged`), matching the run's one line per item; given `-q --dry-run`, should print only the contract.
- Given `--dry-run`, should keep "show the contract, write nothing" and use the skill's shared help wording.
- Given the walkthrough, guide and flags.md, should list init's `-q`/`-v` and the new defaults, and add a CHANGELOG line for the changed `-q` output (shipped beta behaviour).
- Given the blast-radius rule, should run init under `-q`, the default, `-v`, `--format json`, `--questions`, `--answers` and `--dry-run` through the installed console script, and the walkthrough's commands unchanged.

---

## `fab-test pbir contract lint`

**Status**: ✅ 2026-11-19. `_slicer_contract_lint.py` (255 lines); the report lookup and shared flags moved to `_slicer_init_output.py`, so the init module shrank to 386 lines. Lint also runs with no TARGET over every contract under `--artifact-dir`, as the run does over every report, which the CI examples need; the skill now says so. pql-test runs through its console entry point with fab-test's interpreter (`python -m pql_test` has no `__main__`). Verified through the console script under the default, -q, -v, `--format json`, a refused `--open-report`, and a failing contract. Version `1.10.0b5` (`b4` is on PyPI).

The first command planned with the skill: run `/command-grammar plan pbir contract` and paste its Given/should lines here before TDD. Characterize first: read the installed `pql-test contract lint --help` and its `--format json` output, and settle the open question.

**Requirements** (minimum, before the skill's lines are added):
- Given `fab-test pbir contract lint Sales.Report`, should find the paired contract and the report's semantic model, run `pql-test contract lint` on them, add fab-test's own checks (the contract reads, ids are unique, pages and bookmarks resolve), and exit 0 clean, 1 on findings, 2 when the contract can't be read or none pairs.
- Given `-q`, the default, `-v`, `--format json`, and `--report`/`--open-report` (refused, naming `fab-test pbir --report`), should behave as the vision's output-modes constraint and the skill's output rule say, and take its inputs exactly as the run does (config-resolved `--artifact-dir` and `--format` included).
- Given the flag reference and guide, should add the pbir flow's init/lint/run flag table, run through each mode on the installed console script before review.
- Given `init`'s output, should name `contract lint` as the next step; given `lint`'s output, should name `fab-test pbir`.
- Given the walkthrough, guide and the fab-test skill reference, should replace `pql-test contract lint` with `fab-test pbir contract lint`, keeping one line on running pql-test directly.
- Given a `src/` change in the beta series, should bump the version and re-stamp the fab-test skill's frontmatter (vision: Versioning).

---

## Follow-ups in plan.md

**Status**: ✅ 2026-11-19. Two deferred tasks (grammar parity test, `pbir contract` subparsers), the Data Agent and `playwright init` tasks pointed at the skill, C4 annotated, and four defects found on the way: a malformed `fab-test.yml` traceback, a failed tool download traceback, `invoke_pql_test`'s broken `-m pql_test` fallback, and `validate-environments-yaml`.

Record what decision 3 left out, so it isn't lost.

**Requirements**:
- Given plan.md's standalone tasks, should add: a parser-driven grammar parity test (ratchet like `test_analyzer_contract_parity.py`), and real subparsers for `pbir contract` in place of the argv check.
- Given the existing "Data Agent: test location and `init` grammar" task, should point it at the skill, so the Data Agent epic's decisions 3 and 10 are rewritten against it when that epic resumes.
- Given the "`fab-test playwright init` scaffolding" task, should point it at the skill's noun rule.

---

## AIDD Review

**Status**: ✅ 2026-11-19. An independent reviewer (unanchored on the implementation) ran aidd-review with aidd-python, aidd-module-budgets, aidd-tdd, aidd-command-grammar and aidd-polite-review, exercising the CLI on scratch copies. One blocking finding, eight should-fix, seven nits; all fixed except where noted:

- **Blocking, fixed:** the run's other flags (`--telemetry`, `--timeout`, `--jobs`, `--dry-run` on lint) fell through to argparse's "unrecognized arguments". `parse` now refuses any `fab-test pbir` flag a verb doesn't take, naming the run; a typo is still argparse's error.
- **Fixed:** `Next:` carries the TARGET and `--artifact-dir` as typed; no-TARGET lint prefers the report beside a contract when two share a `logicalId` and names both otherwise; lint finds contracts with the run's `contract_files`; the skill's `-q` example and help-parity claim corrected, with `--artifact`/`--artifact-dir`/`--format` help shared through `_cli_utils` (the run's help now says they default from `fab-test.yml`) and a test asserting equal help for both verbs; refusals name `fab-test pbir NAME --open-report` and "an HTML report"; `-q` problems name their contract; lint exits 130 on Ctrl-C; `-q` says `contract unchanged` when nothing changed.
- **Nits fixed:** `next` is `null` rather than absent; missing paths and names get their own messages (C4's other half); `{init,lint}` named when the verb is missing; unreadable YAML on one line; init's "see the result first with --dry-run" now says `--force --dry-run`; `--artifact STEM` in the guide; flags.md trailing space; the epilog says TARGET; `Any` instead of a private argparse type in lint's signature.
- **Declined:** caching `file_config()` (three reads of a small file per command; not worth the state). On exit 2 with `--format json`, stdout stays empty and the reason goes to stderr, as the run's own refusals do; left as is.

---

## Quality Gates

**Status**: ✅ 2026-11-19, on the reviewed code. Whole-repo ruff clean; complexity and module-budget ratchets pass; full suite in CI's two halves: 3421 passed + 2 skipped, then 220 Playwright passed with total coverage 91.25% (floor 80%); the CI-env run (`GITHUB_ACTIONS=true CI=true`) 3421 passed; pip-audit finds no known vulnerabilities. The venv's stale `1.10.0b2` metadata needed `uv pip install -e .` first (environment, not code).

Whole-repo ruff, the complexity and module-budget ratchets, the coverage floor on the full suite, and the CI-env run.

**Requirements**:
- Given the vision's Definition of Done, should pass every gate with all three callers documented for `contract lint`.
