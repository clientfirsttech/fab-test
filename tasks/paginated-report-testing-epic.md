# Paginated Report Testing Epic

**Status**: 📋 PLANNED
**Goal**: `fab-test playwright` can validate a Power BI **paginated (RDL)** report the same way it validates an interactive report today, so a broken RDL report blocks promotion instead of only being caught by a person opening it by hand.

## Overview

The original spec for this harness (`fabric-ci-cd-dataops/tasks/dynamic-playwright-visual-error-testing-epic.md`) already called for paginated-report support — "Generate JSON test cases for RDL reports and detect error modals after a configurable wait" — but the static `.env` MVP that shipped into `fab-test` never implemented it: `resolver.py::resolve_item` only ever resolves item type `"Report"`, `TestCase.report_type` defaults to `"report"` with nothing that ever sets it to `"paginated"`, and the pytest spec's render check (`rendered`/`error` events racing on `document.body`) does not apply to RDL reports at all — paginated reports don't fire the interactive embed SDK's page-render events the same way, which is exactly why the original spec called for a different detection strategy (embed, wait, then scan for an error modal). Today, pointing `fab-test playwright` at a paginated report either mis-resolves it as an interactive report or silently validates nothing.

**Non-goal for this epic**: the report-page deep link added in the HTML-report hyperlink work does not apply to paginated reports (RDL reports have no page/bookmark dimension and the Fabric portal's paginated-report viewer uses a different URL shape) — that stays a documented follow-up, not blocking work here.

### Integration test fixtures (DEV)

Two real paginated reports are published to the DEV environment for `integration`-marked live verification:

- `PaginatedExample-BrokenRDL` — expected to **fail** (error modal detected)
- `PaginatedExample-WithFilter` — expected to **pass**

---

## Resolve and discover paginated report items

`resolver.py` only ever asks the service client for Fabric item type `"Report"`. A paginated report is a distinct Fabric item type (`PaginatedReport`) and needs its own resolution path so `--artifact "MyRDLReport"` finds it at all.

**Requirements**:
- Given an artifact name that is a paginated report, `resolve_item`/`resolve_report` should resolve it against Fabric item type `PaginatedReport`, not `Report`
- Given a paginated report has no bound semantic model the way an interactive report does, resolution should not require a `dataset_id` to succeed
- Given `--report-type paginated` (or equivalent config/env setting), `invoke_playwright.py` should skip page/bookmark discovery entirely — RDL reports have neither dimension
- Given `PLAYWRIGHT_REPORT_TYPE` is unset, resolution should keep resolving `Report` items exactly as it does today (no behavior change for existing interactive-report runs)

---

## Generate a paginated test case

`TestCase.report_type` already exists (default `"report"`) but nothing ever produces `"paginated"`, and `generate_test_cases`'s cartesian/discovered paths both assume a page/bookmark matrix that doesn't exist for RDL reports.

**Requirements**:
- Given a paginated report target, test-case generation should emit exactly one `TestCase` with empty `page_id`/`page_name`/`bookmark_id`/`bookmark_name` and `report_type="paginated"`
- Given a paginated report, the case id should not encode `"no-bookmark"`/`"default-page"` placeholders that only make sense for the page/bookmark matrix
- Given `PLAYWRIGHT_RENDER_WAIT_SECONDS` (or equivalent), the generated case should carry that wait duration through to the pytest spec so the embed-then-wait check (below) has a configurable budget instead of a hardcoded number

---

## Embed a paginated report and detect the error modal

The interactive-report check races `rendered` vs `error` events on `document.body` — the original spec is explicit that this does not apply to paginated reports, which instead need an embed, a fixed wait, then a DOM scan for Power BI's error modal.

**Requirements**:
- Given a paginated `TestCase`, `build_embed_config` should build an embed configuration with no `pageName`/`bookmark` (both are meaningless for RDL) rather than passing empty strings that mimic a real page/bookmark value
- Given a paginated report is embedded, the pytest spec should wait the configured render-wait duration (not race `rendered`/`error`) before inspecting the page
- Given the wait elapses, the spec should search the page HTML and every iframe's contents for the error-modal marker (Power BI's `ms-Dialog-content`, matching the original spec's reference) and fail the case if found
- Given the wait elapses with no error modal found, the case should record `pass`
- Given a failed paginated case, it should capture the same evidence (screenshot, console, network) as an interactive-report failure, so the report's Evidence column works unchanged for either report type
- Given the DEV fixtures above, a live `integration`-marked run against `PaginatedExample-BrokenRDL` should record `fail` and against `PaginatedExample-WithFilter` should record `pass`

---

## Reporting: paginated cases read correctly in the HTML/JSON output

The full `test_results` table and terminal summary must not imply a page/bookmark that never existed, and must not gain a broken deep link now that Plan 1's Report Page column exists.

**Requirements**:
- Given a paginated case's row in `test_results`, `page_name`/`bookmark_name` should render as empty (not a placeholder) rather than being dropped from the row shape other analyzers rely on
- Given a paginated case, `report_link` should stay `{}` (no Report Page link) so the report never offers a link built from the wrong URL shape
- Given a mixed run of interactive and paginated reports, the aggregate summary counts (pass/fail/error) should include both without needing a separate code path

---

## Run `ruff check` before documentation

Per [vision.md](../vision.md#definition-of-done--documentation), run `ruff check` over `src/` and fix anything it flags before writing the documentation below.

---

## CI/config documentation

- Given `fab-test.yml`/the CLI help/README, should document `PLAYWRIGHT_REPORT_TYPE=paginated` (or the chosen setting name) and that page/bookmark options are ignored for it
- Given the composite-model limitation already documented for interactive reports, should add the equivalent paginated-report caveat if one exists (needs confirming against a real RDL report before this line is written — flag as an open question rather than guessing)
