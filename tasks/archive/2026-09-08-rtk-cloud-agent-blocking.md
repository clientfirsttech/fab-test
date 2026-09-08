# RTK Cloud Agent Blocking Epic

**Status**: ✅ COMPLETED (2026-09-08)
**Goal**: Get rtk's token savings working in both the local Claude Code session and the GitHub Copilot coding agent, without either one risking a blocked session when rtk is unavailable.

## Overview

`rtk` is a token-optimizing CLI proxy, installed locally from
[rtk-ai/rtk](https://github.com/rtk-ai/rtk) via its public install script.
The hooks that invoke it are committed to the repository, so they run in any
environment that opens it. A GitHub Copilot coding agent session confirmed a
real failure before rtk was ever installed there: every tool call was denied
— file reads, Bash, sub-agent delegation — with the agent unable to do
anything but report itself blocked.

**Root cause**: `.github/hooks/rtk-rewrite.json` ran a bare `rtk hook
copilot`, with no `matcher` (so it fired on every tool type, not just
shell calls) and no fallback for `rtk` missing. GitHub Copilot's
coding-agent hook runner treats *any* failing hook command as a hard deny —
unlike Claude Code, see below — so an absent binary took the whole session
down.

**First pass — stop the bleeding**: [PR #21](https://github.com/kerski/fab-test/pull/21)
(merged into `dev`, commit `fee37d0`) deleted the hook file outright while
fixing two unrelated defects it had surfaced (BPA object details, stale
PBIR images). That made Copilot sessions safe again, but at the cost of
losing rtk's token savings there entirely — a regression from "works
locally," not full parity.

**Second pass — restore it properly, in both places**:
1. `.github/workflows/copilot-setup-steps.yml` now installs rtk from
   `rtk-ai/rtk`'s public install script before the agent's session starts,
   and puts `~/.local/bin` on `$GITHUB_PATH` so the agent's own tool calls
   (not just the setup job) can find it.
2. `.github/hooks/rtk-rewrite.json` is back, but its command is now
   `command -v rtk >/dev/null 2>&1 && rtk hook copilot || exit 0` — it
   checks for rtk before calling it, and exits clean if the setup step was
   skipped, failed, or rtk itself errors for any reason. Verified for real
   (not just read as text): run through `sh -c` with rtk hidden from
   `PATH`, it exits 0 with no output (`tests/test_rtk_hook_safety.py`).
3. `.claude/settings.json`'s equivalent hook (`rtk hook claude`, already
   `matcher`-scoped to `Bash`) needed no code change. Checked directly
   against Claude Code's own documentation
   ([code.claude.com/docs/en/hooks.md](https://code.claude.com/docs/en/hooks.md))
   rather than assumed:

   > "A hook that can't start lands in the same non-blocking bucket... For
   > most hook events, the action proceeds." For `PreToolUse` specifically,
   > only **exit code 2** blocks the tool call — a missing binary (exit
   > 127), any other non-zero exit, or a timed-out hook are all
   > non-blocking, and the call continues through the normal permission
   > flow regardless.

   So a Claude Code session — local, headless, or remote/cloud — with no
   `rtk` on `PATH` already degrades safely: the hook fails to start, Claude
   Code logs it and lets the Bash call through unmodified. Nothing was
   built for this side; per the AIDD fix process's own rule, no change is
   made when none is needed.

**Scope note**: this was repo-local agent tooling config
(`.github/hooks/`, `.github/workflows/copilot-setup-steps.yml`,
`.claude/settings.json`), not part of the `fab-test` CLI product itself.

---

## Resolution summary

| Hook | Problem | Fix |
|------|---------|-----|
| `.github/hooks/rtk-rewrite.json` (`rtk hook copilot`) | No `matcher`; Copilot's runner fails closed on any hook error; blocked every tool call with `rtk` absent | rtk now installed by `copilot-setup-steps.yml`; hook command wraps the call in a `command -v rtk` guard that exits 0 either way — restores token savings without reopening the blocking risk |
| `.claude/settings.json` (`rtk hook claude`) | None found | No change — Claude Code's own exit-code semantics (only exit 2 blocks `PreToolUse`) already fail open |

**Verification**: `tests/test_workflow_triggers.py` (new
`test_copilot_setup_installs_rtk`, plus a fix to
`test_every_path_the_copilot_setup_checks_exists` so a URL/shell-expanded
path isn't mistaken for a missing local file) and the new
`tests/test_rtk_hook_safety.py` (asserts the guard is present, and actually
runs the hook's shell command with `rtk` hidden from `PATH` to confirm exit
0 / no output). Full suite green. Not verified end-to-end in a real Copilot
cloud session from this environment — and `copilot-setup-steps.yml` only
takes effect once merged to the repository's default branch (`main`), not
merely to `dev` — flagged rather than claimed.

---

## Resolved, surfaced by the blocked Copilot session, fixed by PR #21 (unrelated to this epic's own scope)

- `tabular_editor_bpa` object details were blank for tables/columns/relationships (bracket-only StackTrace filter matched only measures) — fixed
- `fab-test all --open-report` could show stale/broken PBIR images while `fab-test pbir --open-report` showed them correctly — fixed (native HTML glob now sorted newest-first by mtime)
