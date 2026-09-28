# Changelog

## 2026-09-28

- 🐛 - Paginated Report Dataset Without A Local RDL - `fab-test playwright` could not test a paginated report that exists only in the workspace: with no local `.rdl` to read its dataset binding from, `GenerateToken` refused the token (*At least one dataset is required*) and the case errored. The binding is now read from the report's own data sources, which name the Power BI dataset as `sobe_wowvirtualserver-<GUID>`; a local `.rdl` is still preferred when present.
- ✨ - Paginated Parameter Cases - A paginated report that declares parameters is now tested as two cases: a baseline with no parameters, and one with a real parameter set applied at embed time through `parameterValues` — the first valid value of each single-value parameter, the first two of each multi-value one. Values come from the parameter's static list or its own dataset query (via `executeQueries`, which needs the **Dataset Execute Queries REST API** tenant setting); parameters are read from the deployed definition when there is no local `.rdl`. **Behavior change**: this replaces clicking the first options in the parameter pane after the baseline render, so a failure is now attributed to the render that caused it, and a parameterized report reports two rows where it reported one. Each `test_results` row gains a `parameters` field.
- 🐛 - Embed-Error Rows Claimed The Report Rendered - A case that never ran because its embed token failed recorded `status: error` beside `actual: "rendered"`. It now records the failure itself.
- ✅ - Playwright Test-Result Parity - The expected pass/fail of all 32 dev-environment cases (26 interactive, 6 paginated), taken from the reference implementation `pbi-dataops-visual-error-testing`, is now pinned: an `expected_status` column on the interactive goldens, the reference's paginated JUnit run, and the four paginated case goldens. An offline contract keeps them joined and complete; a credential-gated live test runs all ten reports through the CLI and compares every case's outcome.

## 2026-09-27

- 🐛 - Playwright Bookmark Discovery - `fab-test playwright` discovered **zero** bookmarks for any report that was never converted to the PBIR folder format — the shape every report in a classic workspace still has, where bookmarks live in `report.json`'s embedded `config` rather than under `definition/bookmarks/`. The bookmark dimension silently dropped out of the test matrix with no warning; six dev-environment reports generated page-only cases. `get_report_bookmarks` now reads that shape too, expanding a bookmark group into its children as it already did for the other two.
- ✨ - Playwright Role Discovery Without An Opt-In Flag - RLS role discovery now runs whenever an effective-identity user is configured, not only when `PLAYWRIGHT_USE_RLS` is set, and the embed token attaches that identity for any case carrying a named role. **Behavior change**: a secured model with a configured user is now tested once per role instead of once under the default identity. A model with no roles is unaffected (nothing is discovered, nothing is attached), and `--roles none` remains the off switch.
- ✨ - Playwright `--plan-only` - `fab-test playwright --plan-only` discovers the page/bookmark/role matrix, writes `test-cases.csv`/`.json`, and exits `0` with a `skipped` envelope — no embed token, no browser, no `playwright install` required. `--dry-run` is unchanged on every analyzer and wins when both are passed.
- ✨ - `playwright_user_name` Config Key - The effective-identity UPN for RLS embed tokens can be declared once in `fab-test.yml` instead of set per run. `PLAYWRIGHT_USER_NAME` still wins. `user_name` is now emitted only on cases that carry a role — a token for a model with no RLS is rejected outright when it carries an identity.
- ✅ - Playwright Test-Generation Parity - Six golden CSVs captured from the dev workspace (`tests/fixtures/playwright-parity/`) now pin the exact `page × bookmark × role` matrix each report must generate, replayed from recorded discovery responses in the default suite and re-driven through the real CLI in a credential-gated live test. `tools/record_playwright_parity_fixtures.py` re-records them.
- ⬆️ - pbir_a11y Tool Version Bump - `analyzers.json`'s `pbir_a11y` entry now pins `pbir-a11y` v0.5.0 (up from v0.3.2), with a matching `install_url` and `install_sha256`. The pinned-version cache keys off `tool_install.version`, so this is a plain cache-miss upgrade — no wrapper or contract changes needed.

## 2026-09-18

- ✨ - PBIR Visual Filter Hidden And Locked - The core PBIR rules now require visual-level filters to be hidden and locked in view mode whenever the filter pane is enabled. The rules remain independent error findings, treat an omitted pane visibility value as Power BI's default enabled state, and traverse only visual filters so page- and report-level consumer controls remain outside the policy. ThinReport fixtures and focused contracts guard the hidden-only, locked-only, neither-state, default-pane, and visual-scope behavior.

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
