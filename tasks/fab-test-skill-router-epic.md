# fab-test Skill Router Epic

**Status**: ✅ COMPLETED (2026-11-22)
**Goal**: Make the main `SKILL.md` a short router, so an agent loads only the part of the skill its task needs.

## Overview

`SKILL.md` is 475 lines and 30.6K characters (about 7.5K tokens), and both Claude Code and Copilot load all of it whenever the skill triggers. A task such as editing a Data Agent test needs about 40 of those lines; the rest (the run manifest schema, the doctor JSON shapes, `-q` constraints already in `references/operations.md`) is paid for on every turn and buries the rule that matters. It also cannot be imported by a `riteway ai` eval on Windows: riteway passes the prompt as one argument, and the cap is about 32K characters. The Skill Componentization epic already moved flags, configuration and targeting into `references/`; this finishes the job for the sections added since.

## Decisions

1. The main file keeps what every task needs: what fab-test is, the artifact format, pytest vs fab-test, install, exit codes, JSON on stdout, the `-q`-first habit, service mode, the subcommand list, and the reference table that routes the rest.
2. Each flow keeps a few must-not-miss lines in the main file (for Data Agent tests: an agent uses `--questions` then `--answers`, never invents an expected answer, edits with `replace`/`remove`, lints before a run, and `--auth az` when the principal is blocked), then points at its reference.
3. New references: `data-agent.md` (the whole `DataAgentTests` block), `run-manifest.md`, `discoverability.md` (the doctor JSON shapes). Facts already in `operations.md` and `configuration.md` are not repeated.
4. A test caps the main file (lines and characters), as `test_skill_main_file_keeps_its_required_sudolang_constructs` guards its form, so it cannot grow back unnoticed. The character cap leaves room for a riteway eval to import it on Windows.
5. The `ai-evals/fab-test-data-agent-tests/` evals run before and after; the pass rate must hold. They test the rules kept in the main file; no eval yet needs `references/data-agent.md`, and no saved answer cites it.

## Baseline Evals

Run the six `tests init` evals on the current skill, `--runs 2`, and record the pass rate.

**Status**: ✅ 22 of 22 assertions, each 2/2 runs, on the 475-line skill.

**Requirements**:
- Given the current skill, should record each eval's pass rate before any file moves

## Split The Skill

Move the sections, keep the must-not-miss lines, route through the reference table, keep both copies identical, list the new files in the wheel check.

**Status**: ✅ 209 lines, about 14.5K characters. The full suite passes (3836, 2 skipped); `test_skill_main_file_stays_a_router` and `test_every_reference_file_is_routed_from_the_main_file` guard it. `-q --format json`'s byte-identical rule, the one fact `operations.md` lacked, was added there.

**Requirements**:
- Given the main SKILL.md, should be under 250 lines and 16,000 characters
- Given a fact the skill documented before the split, should still be documented in SKILL.md or a reference file
- Given a new reference file, should appear in SKILL.md's reference table and in the packaged copy and wheel check
- Given the split, should keep the description naming the current version and the SudoLang constructs the existing guard requires

## After Evals

**Requirements**:
- Given the split skill, should hold or raise the baseline pass rate on the same evals

**Status**: ✅ 22 of 22, each 2/2. Two files errored before judging on the first attempt (no result written, no reason printed at four concurrent) and passed 4/4 when rerun alone.

## Copilot Evals

Run the same evals with GitHub Copilot CLI answering. riteway sends extraction, answer and judge prompts to one agent, so `ai-evals/agents/copilot-answers-claude-judges.mjs` routes only the answer to Copilot (`@github/copilot@1.0.114`, read-only: shell and writes denied) and keeps Claude extracting and judging, as in the Claude runs.

**Requirements**:
- Given the split skill and Copilot answering, should pass the same evals as Claude, judged by the same judge

**Status**: ✅ 22 of 22, each 2/2 (Copilot's default model, claude-sonnet-5.5; 12 premium requests). 14 Copilot sessions opened during the run, so the answers were Copilot's, not a fallback.
