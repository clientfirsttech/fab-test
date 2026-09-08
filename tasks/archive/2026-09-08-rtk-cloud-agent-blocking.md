# RTK Cloud Agent Blocking Epic

**Status**: ✅ COMPLETED (2026-09-08)
**Goal**: Stop the repo's rtk PreToolUse hooks from blocking every tool call when rtk isn't installed in the agent's environment.

## Overview

`rtk` is a token-optimizing CLI proxy installed only on this machine
(`/c/Users/jkers/OneDrive/Documents/rtk/rtk`), but the hooks that invoke it
were committed to the repository, so they ran in any environment that opened
it. A GitHub Copilot coding agent session confirmed a real failure: every
tool call was denied — file reads, Bash, sub-agent delegation — with the
agent unable to do anything but report itself blocked.

**Root cause, and why it was Copilot-only**: `.github/hooks/rtk-rewrite.json`
ran `rtk hook copilot` with no `matcher`, so it fired on every tool type, and
GitHub Copilot's coding-agent hook runner apparently treats *any* failing
hook command as a hard deny. `[PR #21](https://github.com/kerski/fab-test/pull/21)`
(merged into `dev` 2026-09-08, commit `fee37d0`) deleted that file outright
while fixing two unrelated defects it had surfaced (BPA object details,
stale PBIR images). Verified: the file is gone from `dev`, full suite green
(1692 passed, 3 skipped, coverage 88%).

**`.claude/settings.json`'s equivalent hook needed no fix.** It runs
`rtk hook claude`, scoped to `"matcher": "Bash"` already. Checked directly
against Claude Code's own documentation
([code.claude.com/docs/en/hooks.md](https://code.claude.com/docs/en/hooks.md))
rather than assumed:

> "A hook that can't start lands in the same non-blocking bucket... For most
> hook events, the action proceeds." For `PreToolUse` specifically, only
> **exit code 2** blocks the tool call — a missing binary (exit 127), any
> other non-zero exit, or a timed-out hook are all non-blocking, and the
> call continues through the normal permission flow regardless.

So a Claude Code session — local, headless, or remote/cloud — with no `rtk`
on `PATH` already degrades safely today: the hook fails to start, Claude
Code logs it and lets the Bash call through unmodified. There is nothing to
build here; the two tasks originally planned for this side of the epic
(a fail-open wrapper, a doc note explaining the fallback) were dropped
because their premise didn't hold once checked against the primary source —
per the AIDD fix process's own rule, no change is made when none is needed.

**Scope note**: this was repo-local agent tooling config
(`.github/hooks/`, `.claude/settings.json`), not part of the `fab-test` CLI
product itself.

---

## Resolution summary

| Hook | Problem | Fix |
|------|---------|-----|
| `.github/hooks/rtk-rewrite.json` (`rtk hook copilot`) | No `matcher`; Copilot's runner fails closed on any hook error; blocked every tool call with `rtk` absent | Deleted (PR #21) |
| `.claude/settings.json` (`rtk hook claude`) | None found | No change — Claude Code's own exit-code semantics (only exit 2 blocks `PreToolUse`) already fail open |

---

## Resolved, surfaced by the blocked Copilot session, fixed by PR #21 (unrelated to this epic's own scope)

- `tabular_editor_bpa` object details were blank for tables/columns/relationships (bracket-only StackTrace filter matched only measures) — fixed
- `fab-test all --open-report` could show stale/broken PBIR images while `fab-test pbir --open-report` showed them correctly — fixed (native HTML glob now sorted newest-first by mtime)
