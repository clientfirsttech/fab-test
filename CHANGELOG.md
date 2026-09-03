# Changelog

## 2026-09-03

- 🐛 - Analyzer Runtime Readiness - `doctor` now checks for the .NET/Node.js runtime an analyzer's tool needs (`requires_runtime` in `analyzers.json`), not just the binary's presence — a resolved `pbir` or `a11y` tool used to report `ready: true` even without .NET 8 / Node 18 installed. The PBIR Inspector wrapper also no longer reports `passed` when the tool exits non-zero having produced no output (e.g. .NET missing); that case now writes an `error` envelope, exits non-zero, and surfaces the tool's stderr. **Behavior change**: a pipeline running on a machine without the required runtime now fails at `doctor`/`pbir` instead of silently passing — this is the defect becoming visible, not a regression.

## 2026-09-02

- 🐛 - pql-test Connection-Failure Reporting - A run that reached nothing warns

## 2026-08-31

- 🐛 - Open Report Flag - Single-analyzer multi-artifact runs open an index too
