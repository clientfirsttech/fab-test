# Promptfoo Skill Evaluation Epic

**Status**: 🔄 IN-PROGRESS — 1/3 tasks (scope and scenarios defined 2026-09-02; local runner blocked, see Discovery)
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

---

# Discovery (2026-09-02)

## Decisions

| Decision | Choice | Consequence |
|----------|--------|-------------|
| Grader | **Claude Sonnet 5** (`claude-sonnet-5`) | Higher-fidelity rubric judgment on the "would an agent choose right, and why" cases. Costs more per run than Haiku, which is why CI is path-filtered rather than running on every push. |
| CI behavior | **Non-blocking, path-filtered** on `.github/skills/fab-test/**` | Skill drift is reported without a non-deterministic judge red-building a PR that never touched the skill. Satisfies the epic's "decide and document the choice" requirement. |
| Scenario families (v1) | Subcommand selection, exit-code interpretation, targeting grammar | The pytest-vs-fab-test distinction is **deferred** — it is one table with no branching behavior, so it is the cheapest family to add later once the harness exists. |
| Local runner | **OPEN** — see Blocker below | Does not block scenario authoring; does block the epic's third task (documented pre-commit command). |

## Blocker: promptfoo cannot start on win32-arm64

Reproduced two ways on the development machine (`node -p process.platform+process.arch` → `win32-arm64`):

1. `npx --yes promptfoo@latest --version`
2. a clean `npm init -y` + `npm install promptfoo` in an empty directory, run via `./node_modules/.bin/promptfoo`

Both install successfully and then fail identically at startup:

```
promptfoo could not load its SQLite dependency because the libsql binding
for "win32-arm64-msvc" is missing.
Required package: @libsql/win32-arm64-msvc
```

`npm view @libsql/win32-arm64-msvc` returns **404 — the package does not
exist**. `libsql`'s published `optionalDependencies` cover darwin x64/arm64,
linux x64/arm64/arm (gnu and musl), and win32-**x64** only. The dependency is
required at process start and there is no bypass: promptfoo's env flags are
`PROMPTFOO_DISABLE_{TELEMETRY,SHARING,UPDATE,REF_PARSER,TEMPLATE_ENV_VARS,
REDTEAM_MODERATION,REDTEAM_REMOTE_GENERATION,SHARE_EMAIL_REQUEST}` — none
disables the DB. Installing `@libsql/win32-x64-msvc` by hand does not help
either: a native x64 `.node` addon cannot load into an ARM64 Node process.

This is a platform gap, not a configuration mistake, and it is the same shape
as the gaps `fab-test` itself degrades to skips. Three paths work; the choice
is the user's:

| Path | Why it works | Cost |
|------|--------------|------|
| Docker, `linux/arm64` | `@libsql/linux-arm64-gnu` is published; Docker Desktop is already installed on this machine | A Dockerfile, a bind mount for the skill files, API-key passthrough |
| An x64 Node install | `@libsql/win32-x64-msvc` loads into an x64 Node under Windows-ARM x64 emulation | A second Node toolchain to keep current; slower than native |
| Ubuntu WSL distro | Native ARM Linux speed | Machine setup outside this repository (`wsl -l -v` shows only the docker-desktop distros today) |

CI is unaffected — all three workflows run `ubuntu-latest` (x64), where
promptfoo installs and runs unmodified. A CI-only eval is therefore viable with
no local runner at all, at the cost of no pre-commit feedback loop.

## Context-loading strategy

The skill is **~86 KB across 8 files** (`SKILL.md` 17 KB, `flags.md` 30 KB,
plus six smaller references). Pasting all of it into every prompt is both
expensive at Sonnet 5 rates and unfaithful — a real agent loads `SKILL.md`
and follows its table of contents to one reference. So each scenario declares
the minimum file set it needs, and that set is itself part of what is being
tested: if a scenario can only be answered with `flags.md` loaded, then
`SKILL.md`'s table of contents must be what points there.

**Every family runs a no-skill control arm.** The same prompt with no skill
content proves the skill is what produced the correct answer rather than the
model's priors — without it, a scenario can pass while the skill contributes
nothing, which is the exact failure this epic exists to catch.

**Assertions must be version-agnostic.** `SKILL.md`'s frontmatter description
names the current `__version__`, which moves on nearly every epic. No assertion
may match a version string, or the suite goes red on every bump.

## Scenarios

Assertion types: `contains` / `not-contains` / `javascript` are deterministic and
free; `llm-rubric` costs a Sonnet 5 call and is used only where the check is
about reasoning rather than output shape.

### Family A — Subcommand selection

Checks: `SKILL.md` "Subcommands", "Distinction from pytest", and the scopes
table in `references/targeting-and-discovery.md`. Files loaded: `SKILL.md`
(plus `references/flags.md` for A5 only).

| # | Prompt | Expected | Assertion |
|---|--------|----------|-----------|
| A1 | "Check my Power BI report for accessibility problems." | `fab-test a11y` | `contains: "fab-test a11y"`, `not-contains: "fab-test pbir"` |
| A2 | "Do the DAX tests on my semantic model pass?" | `fab-test pql-test` | `contains` |
| A3 | "Do my reports actually render, or do visuals error out?" | `fab-test playwright` | `contains` |
| A4 | "Check my semantic model against best-practice rules." | `fab-test bpa` | `contains` |
| A5 | "Which reports depend on the deployed SalesModel?" | `fab-test dependencies --semantic-model SalesModel` | `contains: "dependencies"` + rubric on the flag |
| A6 | **Trap.** "I just edited `invoke_pql_test.py`. How do I verify my change?" | `pytest -m pql_test` — **not** `fab-test pql-test` | `contains: "pytest"`, `not-contains: "fab-test pql-test"` |
| A7 | **Trap.** "Tabular Editor isn't installed. What do I run first?" | `fab-test doctor` | `contains: "doctor"` |

A6 is the highest-value case in the family: it is the one confusion the skill
opens with ("It is **not** `pytest`") and devotes a whole table to, so a
regression there means that table stopped working.

### Family B — Exit-code interpretation

Checks: `SKILL.md` "Agent Contract" → `ExitCode` SudoLang block. Files loaded:
`SKILL.md` only — if a scenario here needs a reference file, the Agent Contract
is under-specified and that is itself the finding.

| # | Prompt | Expected | Assertion |
|---|--------|----------|-----------|
| B1 | "`fab-test bpa` exited 127. What happened and what do I do?" | A required external tool could not be resolved; the message names the flag/env var/config key that fixes it | `contains: "127"` + rubric: names tool resolution, not findings |
| B2 | "`fab-test playwright` exited 126." | Unsupported on this platform; the message names the supported OS | rubric: platform, **not** conflated with 127's missing-tool meaning |
| B3 | "`fab-test` exited 2." | Invalid CLI arguments; no analyzer ran | `not-contains: "finding"` — the trap is reporting findings for a run that never started |
| B4 | "`fab-test pbir` exited 1." | Either error-level findings **or** the analyzer process crashed | rubric: both readings offered, and the envelope named as how to tell them apart |
| B5 | **Trap.** "`fab-test all` exited 0 but the summary shows 21 warnings. Did it pass?" | Yes — warnings never fail the build | `contains: "0"` + rubric: unambiguous yes |
| B6 | "Exit 1 on a scheduled run. Retry it?" | No — read the envelope; the exit code is deterministic, a retry changes nothing | rubric |

B5 is worth keeping permanently: the `warning` status added by the pql-test
Connection-Failure Reporting epic makes "exited 0, shows warnings, and one
analyzer ran nothing" a live shape an agent will meet, and reading it as a
failure is the misinterpretation that epic existed to prevent.

### Family C — Targeting grammar

Checks: `references/targeting-and-discovery.md` "Targeting", "Which scopes each
analyzer accepts", "Scope-specific behavior". Files loaded: `SKILL.md` +
`references/targeting-and-discovery.md`.

| # | Prompt | Expected | Assertion |
|---|--------|----------|-----------|
| C1 | "Run BPA against the model I have open in Power BI Desktop." | `fab-test bpa local/Sales` | `contains: "local/"` |
| C2 | "Run pql-test against the deployed Sales model in the 'Sales Dev' workspace." | `fab-test pql-test "Sales Dev.Workspace/Sales.SemanticModel"` — **quoted** | `javascript`: matches the workspace form **and** the quoting |
| C3 | **Trap.** "Run PBIR Inspector against the deployed report in the Sales Dev workspace." | Refuse: `pbir` has no workspace scope, exits `2`; offer a path or `local/NAME` | rubric: refusal + the working alternatives, **not** a fabricated command |
| C4 | "Test only `Sales.SemanticModel`, not the report of the same name." | The type-qualified target `Sales.SemanticModel` | `contains` |
| C5 | **Trap.** "I have a directory literally named `local`. How do I target `local/Sales` inside it?" | `./local/Sales` — the leading `./` escapes the Desktop scheme | `contains: "./local/"` |
| C6 | "`fab-test all local/Sales` — what happens to `playwright`, which can't take a `local/` target?" | It is **skipped** with a message; the batch is not failed | rubric: skip, not failure |

C3 and C6 are the two cases a plausible-sounding wrong answer is most likely:
both require the agent to report a limitation rather than emit a command, which
is exactly what an under-specified skill fails at.

## Scope revisions to the tasks above

1. **Task 1 (define scope)** is satisfied by this section.
2. **Task 2 (author config)** gains a requirement: per-scenario file selection
   plus a no-skill control arm, rather than one prompt template with the whole
   skill inlined.
3. **Task 3 (CI and document)** gains the runner decision above, and its
   contributor-doc target needs creating — **there is no `CONTRIBUTING.md` in
   this repository**, so "documented in contributor-facing docs" has no home
   yet. Creating one, or a `docs/dev/` page, is part of that task. It must not
   land in `README.md` or `docs/QUICK-VALIDATION.md`, which are end-user
   surfaces for a `pip install fab-test` caller.

## Found during discovery, unrelated to this epic

`SKILL.md`'s Installation section pins `"fab-test==1.0.0.0.dev1"` — a
**four-segment** version, which vision.md's Versioning section explicitly
forbids ("Three-part semver ... no fourth segment"), and stale besides
(`__version__` is `1.1.0.dev1`). Both authored and packaged copies carry it.

**Fixed 2026-09-08** (doc-only, no version bump per vision.md): corrected to
`"fab-test==1.1.0.dev2"` in both `SKILL.md` copies, plus the same stale
four-segment example (`1.0.0.0.dev15`) in `README.md`, `docs/RELEASE.md`, and
`docs/QUICKSTART-LOCAL.md`. No test pins these example strings to
`__version__`, so nothing else needed to change; `.github/workflows/publish.yml`
intentionally still accepts a four-component tag for backward compatibility
with pre-migration releases, which is unrelated and untouched.
