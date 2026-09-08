# Changelog

## 2026-09-05

- 🐛 - BPA Object Details - `tabular_editor_bpa`'s Object column now shows table, column, and relationship names, not just measures. TE2 only brackets measure names (`[Total Sales]`); tables, columns, and relationships are single-quoted DAX (`'Sales'`, `'Sales'[Amount]`), so filtering StackTrace lines by a leading `[` silently dropped every one of those, leaving the report's Object column blank for the affected rules.
- 🐛 - PBIR Report Image Reliability - `fab-test all --open-report` could show broken PBIR screenshot images even though a standalone `fab-test pbir --open-report` did not. `_locate_native_html` picked an unsorted `*.html` glob match from the reused native-output folder, which could return a stale report left over from an earlier run instead of the freshly generated one. It now sorts by modified time (newest first), matching the pattern `_read_native_output` already used for its JSON glob.

## 2026-09-03

- 🐛 - Analyzer Runtime Readiness - `doctor` now checks for the .NET/Node.js runtime an analyzer's tool needs (`requires_runtime` in `analyzers.json`), not just the binary's presence — a resolved `pbir` or `a11y` tool used to report `ready: true` even without .NET 8 / Node 18 installed. The PBIR Inspector wrapper also no longer reports `passed` when the tool exits non-zero having produced no output (e.g. .NET missing); that case now writes an `error` envelope, exits non-zero, and surfaces the tool's stderr. **Behavior change**: a pipeline running on a machine without the required runtime now fails at `doctor`/`pbir` instead of silently passing — this is the defect becoming visible, not a regression.

## 2026-09-02

- 🐛 - pql-test Connection-Failure Reporting - A run that reached nothing warns

## 2026-08-31

- 🐛 - Open Report Flag - Single-analyzer multi-artifact runs open an index too
