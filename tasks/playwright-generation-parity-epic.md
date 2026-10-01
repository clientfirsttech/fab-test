# Playwright Test-Generation Parity Epic

**Status**: ✅ COMPLETED (2026-09-27)
**Goal**: Prove `fab-test playwright` builds exactly the test-case permutations the dev environment's six golden CSVs describe — and keep proving it after every change to discovery or generation.

## Overview

Today nothing outside a live run says what matrix `fab-test playwright` *should*
produce for a given report. `playwright_validation/test_cases.py` and
`discovery.py` are unit-tested against invented inputs, so a regression in the
page↔bookmark pairing, the role fan-out, or the RLS identity shows up only as a
render that quietly tested the wrong thing. The six CSVs captured from the dev environment (today in
`playwright-research/test-cases/`, moving to `tests/fixtures/playwright-parity/`)
are the missing statement of intent: they were
captured from the registered dev workspace
(`c4698d28-b05c-40bc-926c-707563ac85e7`) and cover every dimension fab-test
expands — pages alone, page-scoped bookmarks, RLS roles, RLS × bookmarks, and a
thin report whose semantic model lives apart from it. This epic turns them into
golden fixtures with a replayable discovery layer, closes the two places where
fab-test's output does not match them, and adds a credential-gated live run so
the fixtures cannot silently diverge from the real API.

Scope is **generation only**. Whether "Not Working Visuals" actually fails at
render time is a different question and stays out of this epic.

## Outcome (2026-09-27)

All seven tasks done; all six reports match their golden CSVs both replayed and
live through the installed console script. Two defects the parity work exposed,
neither of which was in the plan:

1. **Bookmark discovery returned nothing for any dev report.** The six reports
   are classic (non-PBIR) exports whose bookmarks live in `report.json`'s
   embedded `config`, a shape `get_report_bookmarks` did not read. Every
   bookmark case was silently missing from the matrix -- the actual reason the
   generated tests looked wrong. Fixed with the legacy shape added to the same
   parser, group-children expansion included.
2. **Role discovery was gated behind `PLAYWRIGHT_USE_RLS`.** With `user_name`
   moving to config, a run with a configured identity still produced no role
   cases. Role discovery now runs whenever an identity is configured, and
   `generate_embed_token` attaches it for any case carrying a named role --
   which reversed an existing test asserting the identity was dropped without
   the flag. A model with no roles is unaffected; `--roles none` still disables.

Full suite green (1,851 passed) at 87% coverage; `ruff check src/ tools/` clean.

## Discovery Answers (2026-09-27)

| Question | Decision |
|----------|----------|
| Harness | Recorded fixtures replayed in a fast unit test, **plus** an opt-in live test gated on credentials |
| Golden set | All **six** CSVs in `playwright-research/test-cases/` |
| Match rule | Unordered **semantic key set**: `workspace_id, report_id, report_name, page_id, page_name, dataset_id, bookmark_id, bookmark_name, role, user_name`. `test_case` id, extra emitted columns, and row order are ignored |
| Scope | Test-case generation only; no render/pass-fail assertions |
| Invocation | One run per report, discovery on (six invocations) |
| `user_name` | No longer supplied by the caller — resolved from a declared config key through the usual CLI > env > `fab-test.yml` > default chain |
| `user_name` on non-RLS rows | Must be blank unless the case carries a role |
| Generation-only flag | `--plan-only` — a new, additive flag; the existing `--dry-run` keeps meaning "list matching artifacts" |
| Config key spelling | Flat: `playwright_user_name` |
| Golden CSV home | `tests/fixtures/playwright-parity/` — the CSVs move out of `playwright-research/` |

## What The Golden CSVs Assert

| Report | Pages | Bookmarks | Roles | Rows |
|--------|-------|-----------|-------|------|
| Working Visuals | 1 | — | — | 1 |
| Not Working Visuals | 2 | — | — | 2 |
| Report with Bookmarks | 1 | 2 on Page 1 | — | 3 |
| Report with Bookmarks - Broken Visuals | 2 | 2 on Page A, 2 on Page B | — | 6 |
| RLSTest-ThinReport | 2 | — | Team A, Team B | 4 |
| RLSTest-WithBookmarks | 2 | 1 on Page 1, 2 on Page 2 | Team A, Team B | 10 |

The shape — one baseline row per page plus one row per that page's *own*
bookmark, repeated per role — is what `_generate_discovered_cases` already
builds. The fixtures are therefore expected to pass on the current generator for
the four non-RLS reports; the two RLS reports are where the `user_name` work
below changes behavior. Two traps the fixtures must not paper over:

- **Page and bookmark ids repeat across reports.** Page `5da315eb042003e41290`
  is "Page 1" in *Working Visuals*, "Page 1" in *Report with Bookmarks*, and
  "Page B" in *Broken Visuals*; bookmark `4069a31f88c3cdcda01c` is "Bookmark 1"
  in one report and "DDC" in another. Fixtures and assertions are keyed per
  report, never by id alone.
- **Bookmark names are not identifier-safe.** `---` and `-DC` are real bookmark
  names in the dev environment and must survive into the CSV verbatim while
  `sanitize_case_id` keeps evidence directories safe.

---

## Record the discovery fixtures

Capture the Power BI REST responses that back each golden CSV so the parity test
runs with no network.

**Requirements**:
- Given the six golden CSVs, should move them to
  `tests/fixtures/playwright-parity/` (they are test input, not research notes),
  leaving `playwright-research/` for notes only, and should update any path that
  referenced them.
- Given the six dev reports, should store one fixture per report under
  `tests/fixtures/playwright-parity/<report-id>.json` holding exactly what
  `get_report_pages`, `get_report_bookmarks`, and `get_semantic_model_roles`
  return for it, so the replay exercises the real `_discover_pages` mapping
  rather than a hand-built `DiscoveredPage` list.
- Given a fixture, should carry the report's `workspace_id`, `report_id`,
  `report_name`, `dataset_id`, and `use_rls` alongside the responses, so one
  fixture fully determines one `PlaywrightValidationConfig`.
- Given the fixtures are recorded from a live tenant, should contain no tokens,
  secrets, or member UPNs beyond the `user_name` already present in the golden
  CSVs (vision.md: secrets never land in committed artifacts).
- Given a recording script is needed, should add it under `tools/` and document
  its invocation in the epic, so re-recording after a dev-environment change is
  a command and not an archaeology exercise.

---

## Add the golden parity test

Assert generated cases equal the golden CSVs under the agreed match rule.

**Requirements**:
- Given a golden CSV and its fixture, should build the config, run
  `resolve_discovery` against the replayed client and then `generate_test_cases`,
  and compare the **set** of semantic keys against the CSV's — failing with a
  diff that names the missing and extra combinations, not just a count.
- Given a golden CSV that omits `role`, `user_name`, or the bookmark columns
  entirely, should treat the absent column as empty for every row rather than
  skipping the comparison for that field.
- Given the comparison, should ignore `test_case`, `report_type`,
  `render_wait_seconds`, `report_parameters`, and row order.
- Given all six reports, should run as one parameterized test marked
  `playwright` so `pytest -m playwright` covers it in the edit loop.
- Given a new golden CSV dropped into `tests/fixtures/playwright-parity/` with no
  matching fixture, should fail rather than silently test five of six — the
  parameterization is driven by the CSV directory, not a hard-coded list.

---

## Resolve `user_name` from configuration, not the caller

`PLAYWRIGHT_USER_NAME` will not be supplied. The effective-identity UPN becomes a
declared setting resolved the same way every other fab-test setting is.

**Requirements**:
- Given no `PLAYWRIGHT_USER_NAME`, should resolve the effective-identity user
  from the flat `playwright_user_name` key in `fab-test.yml` through
  `resolve_setting`, so precedence is CLI flag > `PLAYWRIGHT_USER_NAME` >
  `fab-test.yml` > unset, and `fab-test config --show` reports the value and its
  origin like every other key.
- Given the new key, should be registered in `_VALID_KEYS` and in
  `src/fab_test/schemas/fab-test.schema.json`, and documented as a commented
  entry in `fab-test.yml`, so a typo is caught with a suggestion instead of
  being ignored.
- Given `PLAYWRIGHT_USER_NAME` is still set (as `playwright-demo.yml` sets it
  today), should keep winning over the config file — vision.md's backward-compat
  constraint: released env vars keep working.
- Given roles are discovered and no user is resolvable from any source, should
  keep today's guard — an embed-error envelope naming *both* the env var and the
  config key that fix it, never a run that mints identity-less tokens and passes.
- Given the resolution lives in `playwright_validation/config.py`, which is read
  by `invoke_playwright.py`, the `fab-test playwright` command, and `doctor`,
  should exercise each caller through the real CLI before the task is called done
  (vision.md: Blast Radius).

---

## Blank `user_name` on non-RLS cases

**Requirements**:
- Given a case with no role, should emit an empty `user_name` even when one is
  configured, matching the four non-RLS golden CSVs and avoiding an effective
  identity sent to a model that has no RLS.
- Given a case with a role, should emit the resolved `user_name` unchanged.
- Given a paginated report, should follow the same rule — `_build_paginated_case`
  carries `user_name` today regardless of role.
- Given the change, should be covered by the golden parity test rather than only
  by a new unit test, so the two cannot disagree.

---

## Add a `--plan-only` generation mode

Make the live parity check cheap enough to run, and give the human and the agent
a way to see the matrix before spending minutes in a browser. `--dry-run` already
means "list the artifacts that would run" for every analyzer
(`fab_test_execution.py:772`); `--plan-only` goes one step further for
`playwright` -- it resolves the target and builds the matrix -- so the two stay
distinguishable rather than one flag meaning two things.

**Requirements**:
- Given `fab-test playwright --plan-only`, should run discovery, write
  `test-cases.csv`/`.json` to the per-artifact directory
  `playwright_test_cases_dir` already defines, print the matrix summary, and
  exit `0` without minting an embed token or launching a browser.
- Given `--plan-only`, should not require the Playwright browser binaries, so it
  works on a machine where `playwright install` has never run.
- Given `--dry-run`, should behave exactly as it does today, on `playwright` and
  on every other analyzer -- `--plan-only` is additive, and a released surface
  does not change meaning under it (vision.md: backward compat).
- Given both flags together, should take the cheaper one: `--dry-run` wins and
  no discovery call is made, rather than silently ignoring one of the two.
- Given `--plan-only --format json`, should emit the matrix in the same envelope
  shape a real run's caller already parses rather than a second, parallel one.
- Given credentials are absent or discovery fails, should degrade the way a real
  run does (warn, fall back to the default case) rather than erroring -- a plan
  is a preview, not a readiness gate; `doctor` is the readiness gate.
- Given the flag is `playwright`-only, should be rejected with a clear message on
  analyzers that have no matrix to plan, not silently accepted and ignored.
- Given the flag exists, should be what the live parity test and the epic's
  re-recording script both use.

---

## Gate the live parity run on credentials

**Requirements**:
- Given service-principal credentials and the dev workspace are reachable, should
  run `fab-test playwright --plan-only` once per report through the real console
  script and diff each emitted CSV against its golden file under the same match
  rule.
- Given no credentials, should skip with a message naming what to set — never
  fail CI and never silently pass as if it ran.
- Given the live run disagrees with a fixture, should fail naming the report and
  the differing combinations, since that means the recorded fixture has gone
  stale against the real API — which is the whole reason this test exists.
- Given the test is marked `integration` and `playwright`, should be excluded
  from the default suite the coverage gate measures.

---

## Documentation (Definition of Done)

**Requirements**:
- Given a human, should document in `docs/` what matrix `fab-test playwright`
  generates for a report (the baseline-plus-page-bookmarks × roles rule), the new
  `user_name` config key, and `--plan-only`.
- Given a pipeline, should provide a copy-pasteable snippet for a `--plan-only`
  matrix preview step.
- Given an agent, should update `.github/skills/fab-test/` with the new flag,
  config key, and generation contract in SudoLang, and mirror it into the packaged
  copy `src/fab_test/skill/` so `tests/test_skill_resource.py` passes.
- Given the epic is closing, should run `ruff check src/` and the full suite with
  coverage at or above the 80% floor.

---

## Decisions Taken (2026-09-27)

- **Flag**: add `--plan-only` rather than overloading `--dry-run`. `--dry-run`
  keeps its released meaning on every analyzer (list matching artifacts, no
  discovery call); `--plan-only` is the new, additive flag that resolves the
  target and writes the matrix. Two flags, two meanings, no behavior change to
  an existing surface.
- **Config key**: flat `playwright_user_name`, matching today's `_VALID_KEYS`.
  Revisit a nested `playwright:` section only when a second key arrives.
- **Golden CSV home**: `tests/fixtures/playwright-parity/`, beside the recorded
  discovery fixtures. `playwright-research/` keeps notes only.
