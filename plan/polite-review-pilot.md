# Politeness review: `fab-test pbir contract init` and `fab-test doctor`

Pilot of `aidd-polite-review` (Polite Software Review epic), 2026-11-17.

**Primary persona:** Local Developer, writing a report's first slicer contract on a laptop; then checking readiness with `doctor`. **Goals:** "pin what my report opens with, once, without a ceremony"; "know what will run before I run it".
**Other callers checked:** AI Agent (drives `init` through `--questions`/`--answers`, and runs commands with no terminal); CI Pipeline (never prompted).
**Evidence:** ran. `contract init` from `feature/pbir-slicer-default-state` at `e499393` (exported with `git archive`, fab-test 1.10.0b2) on a scratch copy of `SampleModel-DefaultState.Report`, as-of 2026-11-17; `doctor` from `dev` (`033fe6a`, 1.10.0b1) in this worktree. Windows 11, Git Bash. One finding (D3) is partly read from source and marked so.

## Summary

Both commands are fast (under a second) and mostly considerate: `init` never guesses a fiscal year, remembers answers, fails fast on bad `--answers`, and has a clean question-and-answer path for agents; `doctor` never downloads anything and says what a first run will do. The serious problem is one Windows-specific slip: with stdin on the null device, which is how coding agents run commands, `init` treats the run as interactive, takes every default, and reports ✓ for a contract nobody answered. The rest is attention and excise: `init` asks fourteen questions whose default nearly everyone takes, and `doctor` prints one remediation four times and refuses `-q`.

## Excise on the main path

`contract init` on a report with 12 slicers (one fiscal period) and 3 bookmark navigators, first run:

1. Type `fab-test pbir contract init fabric-artifacts/SampleModel-DefaultState.Report`: goal work (a path is required; the report's name is not accepted)
2. Confirm 11 non-period slicers, one prompt each, every default `keep`: excise (confirming), 11 steps
3. Choose `keep` or `current` for `'Fiscal Calendar'[Fiscal Semester]`: goal work
4. Confirm 3 bookmark navigators, default `keep`: excise (confirming), 3 steps
5. Give the fiscal year's start month: goal work (only a person knows)
6. Say whether FY27 is named by its end or start year: goal work
7. Read `✓ …Report.odcs.yaml added: …`: goal work

14 of 19 steps are excise.

## Scorecard

| Principle | Rating | Note |
|---|---|---|
| Good citizen in automation | Rude | `init` with stdin on NUL answers itself (C1); piped stdin is handled well |
| Considerate agency | Rude | the same run writes a contract no one decided (C1) |
| Minimal excise | Mixed | 14 of 19 `init` steps confirm a default (C3) |
| Keeps me informed | Mixed | `skip` on an existing rule is silently dropped (C2) |
| Respects attention | Mixed | `doctor` repeats one remediation four times (D1) |
| Few modes | Mixed | `doctor` alone rejects `-q` (D2); `doctor` and `doctor --local` grade the same state differently (D3) |
| Errors are design failures | Mixed | most errors name the fix; a missing folder is described as a malformed one (C4) |
| Actionable for an agent | Polite | `--questions --format json` with `needs_human`, exit 2 on unknown ids or answers |
| Interested in me | Polite | fiscal answers saved in the contract become the next run's defaults |
| Deferential | Polite | the fiscal year is asked, never guessed, with the months that fit listed |
| Fast enough to keep flow | Polite | every probe finished in under 2 s |
| Usable by everyone | Mixed | `doctor` lines run to 293 characters (D4) |

## Findings

### C1 [High · blocking] On Windows, an unattended `init` writes a contract nobody answered
- **Principle:** Good citizen in automation; Considerate agency (vision: one contract, three callers)
- **Callers:** agent, pipeline
- **Evidence:** ran
- **What happens:** with stdin redirected from the null device (`< /dev/null`, which is NUL on Windows, and how coding agents' shells run commands), Python's `sys.stdin.isatty()` returns True, so `_slicer_contract_init.py:206` takes the interactive path. Each prompt goes to stderr, EOF takes its default, and:
  ```
  $ fab-test pbir contract init fabric-artifacts/SampleModel-PQLAssert.Report < /dev/null
    ✓ fabric-artifacts\SampleModel-PQLAssert.Report.odcs.yaml
      added: page-1-date, page-1-alignment
  $ echo $?
  0
  ```
  On a report with a fiscal period the same run prints all 15 prompts, then fails with `calendar.fiscal_year_start_month: no answer, and it has no default` (exit 2), which doesn't name `--answers`. With a pipe instead, the check works and the message is exactly right: `no terminal to ask on: run with --questions --format json to see the questions, then pass --answers FILE`.
- **Why it's rude:** an agent asked to "set up a contract" gets ✓ and exit 0 for decisions no one made, and the contract then pins whatever the report happened to open with. The walkthrough's promise that an agent drives `init` through `--questions`/`--answers` is bypassed without a word.
- **Fix:** treat the run as interactive only when the prompts can be both shown and answered: `sys.stdin.isatty() and sys.stderr.isatty()`. On Windows also confirm a real console (`GetConsoleMode` on the stdin handle via `ctypes`, which fails for NUL). Otherwise raise the existing "no terminal to ask on" error. Add a test with a stdin whose `isatty()` is True and a non-tty stderr. This is unreleased on `feature/pbir-slicer-default-state`, so fix it before that branch merges.

### C2 [Medium · should-fix] `skip` on a rule already in the contract is silently ignored
- **Principle:** Keeps me informed; Deferential
- **Callers:** human, agent
- **Evidence:** ran
- **What happens:** after a first run, `--answers '{"standard-slicers-alignment": "skip"}'` (and the same with `--force`) prints `✓ … unchanged: <every other id>`. `standard-slicers-alignment` is not listed at all, and stays in the file. Only `-v` says `already in the contract`.
- **Why it's rude:** the walkthrough defines skip as "don't check this slicer". A person who changes their mind believes it's no longer checked, until `fab-test pbir` fails on it.
- **Fix:** name it in default output: `kept: standard-slicers-alignment (skip doesn't remove a rule already in the contract; rerun with --force to drop it)`, and make `--force` drop it.

### C3 [Medium · should-fix] Fourteen of nineteen steps confirm a default
- **Principle:** Minimal excise; Undo over confirmation
- **Callers:** human
- **Evidence:** ran
- **What happens:** every slicer and navigator gets its own `Keep checking that or skip it? [keep/skip] default keep:`. On this report, 14 of the 17 questions are routine; the 3 that need a person are the fiscal ones.
- **Why it's rude:** a long run of Enter presses trains the author to stop reading, so the one question that matters (`current` or `keep` on a period) gets the same reflexive Enter.
- **Tension:** asking about each slicer is a deliberate look at what will be pinned. Keep the look, drop the keystrokes.
- **Fix:** show the routine ones as a list and ask once (`Keep checking these 14 as they open today? [Y/review/skip-all]`), then ask only the `needs_human` questions. `review` falls back to one at a time.

### D1 [Medium · should-fix] `doctor` prints the same remediation four times
- **Principle:** Respects attention (vision's analyzer contract: the same remediation once per run)
- **Callers:** human, agent
- **Evidence:** ran
- **What happens:** bpa, pbir, a11y and rdl each print `service mode: no service principal set; would attempt DefaultAzureCredential (unverified -- run `fab-test auth status` to confirm the sign-in); or pass --interactive`.
- **Why it's rude:** 4 of 18 lines say one thing; the line that differs (what each first run downloads) is harder to find, and an agent pays for it four times.
- **Fix:** one grouped line: `service mode (bpa, pbir, a11y, rdl): no service principal set; would try DefaultAzureCredential. Check it with fab-test auth status, or pass --interactive.`

### D2 [Medium · should-fix] `doctor -q` is a usage error
- **Principle:** Few modes; Actionable for an agent
- **Callers:** agent
- **Evidence:** ran
- **What happens:** `fab-test doctor -q` exits 2 with the top-level usage (`usage: fab-test [-h] [--version] … ANALYZER ...` / `unrecognized arguments: -q`), not doctor's own.
- **Why it's rude:** the fab-test skill tells agents to make `-q` their first call, and every analyzer and `contract init` accept it; `doctor`, the command an agent runs first, doesn't.
- **Fix:** accept `-q`: print only rows that aren't ready, and nothing when all are; exit code unchanged.

### D3 [Medium · should-fix, provisional] `doctor` and `doctor --local` disagree about the same state
- **Principle:** Trustworthy; Forthcoming
- **Callers:** human
- **Evidence:** ran, plus read (`fab_test_local.py:73-91`, `_admin_output.py:166-186`); `fab-test local` itself was not run
- **What happens:** `doctor` marks bpa `ℹ … not yet downloaded`; `doctor --local` marks the same state `❌`, with `→ Would download version 2.29.0 … on first run.` It then says `fab-test local would run: pql_test, rdl`, though it just reported `❌ desktop: no running instance detected`, and pql_test needs Desktop.
- **Why it's rude:** the remedy says what would happen, not what to do to get bpa into `local` (its plan skips analyzers that aren't downloaded yet), and "would run pql_test" promises a run that needs Desktop.
- **Fix:** one status per state across both modes; in `--local`, `→ Run fab-test bpa once to download it; local includes it after that.`; mark pql_test not ready while no Desktop instance is found, or say `would run pql_test once Desktop is open`.

### C4 [Low · nit] A mistyped report name is called a malformed folder
- **Principle:** Errors are design failures; Few modes
- **Callers:** human
- **Evidence:** ran
- **What happens:** `contract init SampleModel-DefaultStat.Report` and `contract init SampleModel-DefaultState` both print `is not a PBIR report folder (no definition/pages)`, though neither folder exists; `fab-test pbir TARGET` accepts a name, `init`'s positional only a path.
- **Fix:** resolve a name the way `fab-test pbir TARGET` does; for a missing path, `No folder SampleModel-DefaultStat.Report here. Did you mean fabric-artifacts/SampleModel-DefaultState.Report?`

### C5 [Low · nit] An invalid answer lists choices the question doesn't have
- **Principle:** Errors are design failures
- **Callers:** agent
- **Evidence:** ran
- **What happens:** `"standard-slicers-alignment": "maybe"` gets `answer must be keep, current, skip or {"current": "<format>"}`; this question's choices are `keep` and `skip`, and `current` is then rejected.
- **Fix:** list the question's own `choices` from `--questions`.

### D4 [Low · nit] `doctor` lines run to 293 characters
- **Principle:** Usable by everyone
- **Callers:** human
- **Evidence:** ran
- **Fix:** wrap remediation lines at the terminal width, indented under their row.

## What it already does well

- The fiscal year is never guessed. The question lists the months that fit today's values, and `--questions` marks it `needs_human` with no suggestion.
- `--questions --format json` is a complete agent interface: ids, prompts, choices, suggestions, `needs_human`, `applies_to`.
- `--answers` with an unknown id or an invalid answer fails fast with exit 2, naming the id.
- Answers saved in the contract are the next run's defaults; a rerun reports `unchanged`, and `-q` prints nothing on success.
- With piped stdin, `init` stops at once and names `--questions --format json` and `--answers FILE`.
- The contract is written beside the report folder, never inside it, so Fabric's Git sync can't delete it.
- `doctor` is under a second, never downloads, and says what each first run will fetch and from where; `--format json` is one clean document; an unknown analyzer lists the valid names.

## Quick wins

1. C1: check stderr too, and a real console on Windows (a few lines, before the slicer branch merges).
2. D1: group the repeated service-mode line.
3. C2: name the kept rule in default output.
4. D2: accept `-q` on `doctor`.
5. C5: list the question's own choices.

## What aidd-review alone would have missed

C1, C2, C3, D1, D2 and D3. C1 survived a review that "checks every output mode" (`e499393`) because no review ran `init` with stdin on NUL; this skill's non-interactive probe does. C2 and C3 are behavior the tests encode on purpose, so only a review that asks what the caller experiences questions them. D1–D3 sit outside any recent diff. C4, C5 and D4 a careful code review could have caught.
