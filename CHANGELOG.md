# Changelog

## 2026-09-08

- 🐛 - RTK Cloud Agent Blocking - `.github/hooks/rtk-rewrite.json`'s PreToolUse hook denied every Copilot coding agent tool call (Bash, file reads, sub-agent delegation) when `rtk` wasn't installed, since Copilot's hook runner fails closed on any hook error. `copilot-setup-steps.yml` now installs rtk from `rtk-ai/rtk` before the agent's session starts; the hook's command now guards with `command -v rtk` and exits clean if it's still missing, restoring rtk's token savings in Copilot sessions without reopening the blocking risk. `.claude/settings.json`'s equivalent hook needed no change — Claude Code's own `PreToolUse` semantics already fail open on anything but exit code 2.
- 📝 - Stale four-segment version pin - `README.md`, `docs/RELEASE.md`, `docs/QUICKSTART-LOCAL.md`, and both `fab-test` skill copies pinned an install example (`fab-test==1.0.0.0.dev1`/`dev15`) that violated vision.md's three-part-semver rule and was stale against `__version__`. Corrected to `fab-test==1.1.0.dev2`; doc-only, no version bump. Found during the Promptfoo Skill Evaluation epic's discovery.

## 2026-09-05

- 🐛 - BPA Object Details - `tabular_editor_bpa`'s Object column now shows table, column, and relationship names, not just measures. TE2 only brackets measure names (`[Total Sales]`); tables, columns, and relationships are single-quoted DAX (`'Sales'`, `'Sales'[Amount]`), so filtering StackTrace lines by a leading `[` silently dropped every one of those, leaving the report's Object column blank for the affected rules.
- 🐛 - PBIR Report Image Reliability - `fab-test all --open-report` could show broken PBIR screenshot images even though a standalone `fab-test pbir --open-report` did not. `_locate_native_html` picked an unsorted `*.html` glob match from the reused native-output folder, which could return a stale report left over from an earlier run instead of the freshly generated one. It now sorts by modified time (newest first), matching the pattern `_read_native_output` already used for its JSON glob.

## 2026-09-03

- 🐛 - Analyzer Runtime Readiness - `doctor` now checks for the .NET/Node.js runtime an analyzer's tool needs (`requires_runtime` in `analyzers.json`), not just the binary's presence — a resolved `pbir` or `a11y` tool used to report `ready: true` even without .NET 8 / Node 18 installed. The PBIR Inspector wrapper also no longer reports `passed` when the tool exits non-zero having produced no output (e.g. .NET missing); that case now writes an `error` envelope, exits non-zero, and surfaces the tool's stderr. **Behavior change**: a pipeline running on a machine without the required runtime now fails at `doctor`/`pbir` instead of silently passing — this is the defect becoming visible, not a regression.

## 2026-09-02

- 🐛 - pql-test Connection-Failure Reporting - A run that reached nothing warns

## 2026-08-31

- 🐛 - Open Report Flag - Single-analyzer multi-artifact runs open an index too
