# Promptfoo Skill Evaluation Epic

**Status**: 📋 PLANNED
**Goal**: Add promptfoo-based evaluation of the `fab-test` skill so agent-facing behavior (not just the CLI's Python code) is regression-tested.

## Overview

`tests/test_skill_resource.py` and the pytest suite verify that `fab-test` the CLI behaves correctly and that the packaged skill files stay byte-identical to their authored source — but nothing verifies that an LLM agent given the skill actually picks the right subcommand, targeting syntax, or exit-code interpretation from `SKILL.md` and its `references/*.md`. A skill can be internally consistent and still mislead an agent (ambiguous phrasing, missing example, contradictory instruction) in a way no diff check catches. Promptfoo closes that gap by running real prompts against the skill content and asserting on the model's output, giving early warning when a skill edit changes agent behavior instead of only its file contents.

**Scope note**: this is a contributor/CI safeguard for authoring the skill, not a feature shipped to or run by end users of the `fab-test` CLI. It belongs alongside `tests/test_skill_resource.py` in dev tooling — never in README, install instructions, or the packaged skill contract itself.

---

## Define eval scope and scenarios

Decide what promptfoo is actually grading before wiring anything up: not "does fab-test work" (pytest/CLI already own that) but "given the skill's instructions, does an agent choose correctly." Draft a scenario list — subcommand selection (bpa vs. pbir vs. pql-test vs. playwright), targeting-grammar usage, exit-code interpretation (0/1/2/126/127), and the pytest-vs-fab-test distinction — pulled from the skill's own "Agent Contract" and "Distinction from pytest" sections so scenarios stay traceable to real skill content.

**Requirements**:
- Given the skill's Agent Contract and subcommand reference sections, should produce a written list of scenarios with the specific skill passage each one is checking.
- Given a scenario, should specify the prompt, the expected assertion (exact match, contains, or LLM-graded rubric), and which skill file(s) it exercises.
- Given the scope draft, should be reviewed against `.github/skills/fab-test/SKILL.md` and its `references/` files, not the packaged copy, since the authored source is the one edited day to day (fab-test Skill Distribution epic).

---

## Author promptfoo config and test cases

Add a `promptfooconfig.yaml` (or scoped config under a `promptfoo/` directory) that loads the skill content as context, defines providers, and encodes the scenarios from the scope task as test cases with assertions.

**Requirements**:
- Given the promptfoo config, should reference the authored skill files (`.github/skills/fab-test/SKILL.md`, `references/*.md`) as the content under test, not the packaged copy.
- Given each scenario from the scope task, should exist as a promptfoo test case with an assertion type appropriate to what's being checked (deterministic match for exit codes/flags, LLM-rubric for subcommand-choice reasoning).
- Given the config, should run locally via `promptfoo eval` without requiring secrets beyond an API key the user already has configured.

---

## Wire into CI and document

Add a way to run the eval (npm script, Make target, or documented CLI invocation) and record results, then document the workflow so it isn't a one-off.

**Requirements**:
- Given a contributor edits `.github/skills/fab-test/SKILL.md`, should have a documented command to run the promptfoo eval before committing, recorded in contributor-facing docs (e.g. `CONTRIBUTING.md` or a dev-tooling doc) — not the end-user README, which documents the CLI a `pip install fab-test` user runs.
- Given CI, should run the eval (or flag why it's deferred, e.g. cost/flakiness) — decide and document the choice rather than leaving it silent.
- Given the AIDD `document` command's three-caller sync (agent skill, README/docs, pipeline YAML), should note the promptfoo eval as a contributor-side check under "Documentation Is Part of Done," per [vision.md](../vision.md) — without adding it to the README/docs caller, since that surface is end-user facing and promptfoo is not.
