# Polite Software Review Epic

**Status**: ✅ IMPLEMENTED 2026-11-17 on `feature/aidd-polite-review` (worktree `.claude/worktrees/aidd-polite-review`, from `dev`), not merged or archived: Decisions 1, 4, 6 and 7 await the user's review. Gates pass: ruff, both ratchets, 3011 + 201 tests, coverage 89.98%, CI-env run (the 16 live Playwright renders skip: no service principal in the worktree). Evals 15/15 at one run each. Pilot: [plan/polite-review-pilot.md](../plan/polite-review-pilot.md), nine findings filed as two plan.md standalone tasks. The source copy is deleted when the epic is archived.
**Goal**: AIDD discovery and review ask whether fab-test treats each of its three callers like a considerate helper, using one project skill, `aidd-polite-review`, built from the user's "Polite Software Review" text ([source](../plan/polite-software-review-source.md)).

**Decisions** (proposed 2026-11-17; review before starting):

1. **Name and home**: `.github/skills/aidd-polite-review/`. A project skill, like `aidd-analyzer-contract`; `validate-skill` requires the `aidd-` prefix.
2. **Wired through the router, not by editing vendored skills** (confirmed 2026-11-17): `aidd-workflow` gains a Pre-Flight rule that loads the skill in review only when a diff changes what a caller reads or answers (messages, `--help`, prompts, `init` questions, `explain`/`doctor` output, `report.html`, a skill an agent reads), so it is deliberately not in the `review` row. It is in the `discover` row, and has a `polite review` row of its own. `aidd-product-manager` stays as upstream ships it. `aidd.agent.md` mirrors the router.
3. **The three callers come before "pick one user"** (confirmed 2026-11-17, as vision.md already requires): the source says design for one primary user and mention the others only where they differ. vision.md says a change that helps one caller by degrading another is not aligned. So each review names a primary persona from `plan/story-map/personas.yaml` for the surface under review, always checks "Good citizen in automation" (pipeline) and "parseable, actionable output" (agent), and never proposes a fix that trades one caller for another.
4. **One finding, two outputs**: in review, High findings that lose data or deceive are blocking, other High and Medium findings are should-fix, and Low findings are nits, matching `aidd-review`. In discovery, each finding is also a `PainPoint` (impact from stakes, frequency from how often the path runs), so `aidd-product-manager`'s impact × frequency priority ranks it with no new scale.
5. **Reference files** (confirmed 2026-11-17): the source names four that were never provided. `principles.md` and `cli.md` are written now; `cli.md` covers every command-line surface (commands, flags, prompts, `--help`, stdout and exit codes), so deferring `gui.md` leaves no CLI surface unreviewed. `agents.md` covers both directions: software acting for a user, and software whose caller is an agent (fab-test's third caller and the Data Agent epic). `gui.md` waits for its first real target; until then `report.html` is reviewed with `principles.md` alone.
6. **Read-only**: the skill reports, it never edits. Findings become plan.md standalone tasks or story-map pain points, never same-session fixes.
7. **Documentation**: the agent is covered by the skill and the human by its README. The pipeline has no deliverable, since a judgment review can't gate CI; this is recorded here as the exception to vision's three-caller rule. No `src/` change, so no version bump.
8. **Attribution** (settled 2026-11-17): the traits are Alan Cooper's, from *The Inmates Are Running the Asylum* (1999), with excise and perpetual intermediates from *About Face*. The skill credits each principle by author and work in `principles.md`, paraphrases, and quotes no book passage. `THIRD-PARTY.md` lists software tools, not books, so it gets no row.

## Overview

WHY: fab-test's vision already asks for considerate behavior ("tell the caller how to fix it", no prompts in a pipeline, remediation an agent can act on), but no AIDD skill reviews for it. `aidd-review` checks code quality and security, and `aidd-ui` is a JS/React design persona. So rude output (a stack trace instead of the flag that fixes it, an `init` question that could have been inferred, a `--help` written for the parser rather than the person) passes review and is found only when someone trips over it. This epic turns Cooper's polite-software traits and the excise count into a skill that discovery uses to find pain points before building and review uses to catch regressions before merge.

---

## Skill Guards

pytest checks that keep AIDD skills honest, written first.

**Requirements**:
- Given any `.github/skills/*/SKILL.md`, should fail when it names a `references/`, `scripts/` or `assets/` file that does not exist.
- Given the `aidd-workflow` Command Map and the `aidd.agent.md` table, should fail when a command's skill list differs between them.

---

## Skill Draft

`SKILL.md` and `README.md` from the source, reshaped to AIDD form.

**Requirements**:
- Given `validate-skill`, should pass with no warnings: frontmatter under 100 tokens (the source's description is close to 300) and body under 160 lines.
- Given the trait and principle tables, should keep them only in `references/principles.md`, not in both places.
- Given the commands, should separate `/polite-review [target]` (report only) from `/polite-discover [journey]` (pain points and stories), each a pure thinking stage.
- Given a review, should start from a persona in `personas.yaml` and the vision's three callers, and say which evidence was run versus read.

---

## Principles Reference

`references/principles.md`: Cooper's traits and the expanded principles, with sources and what to look for.

**Requirements**:
- Given each principle, should give the question, observable signs of rude and polite behavior, and its source by author and work.
- Given fab-test's vision principles, should map "Tell the caller how to fix it" and "Local first" to the principles they express, so a finding cites both.

---

## CLI Reference

`references/cli.md`: probes for command-line tools, grounded in fab-test's own surfaces.

**Requirements**:
- Given a CLI, should list probes to run: no args, `--help`, a missing prerequisite, a bad flag, a non-TTY run, `--output-format json`, `-q`, Ctrl-C, and a rerun after success.
- Given an interactive prompt, should ask whether it could be inferred, defaulted or remembered, and whether a non-TTY run can answer it with a flag.
- Given output, should check that stdout stays parseable when it is meant to be, that each fact appears once, and that exit codes mean what `explain` says.

---

## Agents Reference

`references/agents.md`: an agent acting for a user, and software an agent calls.

**Requirements**:
- Given an agent that acts, should check scope, a visible plan, and a question before any irreversible step.
- Given software called by an agent, should check that capability is discoverable, findings carry rule, location and remediation, and nothing makes the agent guess or retry blind.

---

## Discovery and Review Wiring

Route the skill from `aidd-workflow` and `aidd.agent.md`.

**Requirements**:
- Given a diff that changes caller-facing text or prompts, should load `aidd-polite-review` in review; given a diff that doesn't, should not.
- Given `discover`, should load it with `aidd-product-manager` and save findings as `PainPoint`s in the journey YAML.
- Given the Skill Guards test, should pass with the new rows.

---

## Eval Tests

Riteway AI `.sudo` evals for both commands, per `aidd-upskill`.

**Requirements**:
- Given a canned transcript with a stack trace, a needless confirmation, and a prompt in a non-TTY run, should report each with its principle and a concrete fix.
- Given a fix that helps the human by breaking JSON stdout, should flag the trade-off rather than recommend it.
- Given polite output, should report no findings rather than invent some.

---

## Pilot Review

Run the skill on `fab-test pbir contract init` and `fab-test doctor` through the real CLI (targets confirmed by the user 2026-11-17).

**Requirements**:
- Given the pilot, should produce a report with an excise count for the main path and findings with evidence.
- Given each finding, should become a plan.md standalone task or a story-map pain point; none is fixed in this epic.
- Given the findings, should say which ones `aidd-review` alone would have missed. If none, revisit whether the skill earns its place.

---

## Documentation

Human and agent callers, per the Definition of Done (the pipeline exception is Decision 7).

**Requirements**:
- Given the README, should say what the skill is, why, and both commands with an example, with no process narrative.
- Given the epic's close, should delete `plan/polite-software-review-source.md`.

---

## Quality gates

Run as CI runs them, over the whole repo (vision.md, Definition of Done).

**Requirements**:
- Given `ruff check .`, the complexity and module-budget ratchets, the full suite with `--cov-fail-under=80`, and the CI-env run, should all pass.
