# Playwright Test Matrix Discovery Epic

**Status**: 📋 PLANNED
**Goal**: `fab-test playwright --env DEV` covers every page, page-scoped bookmark, and
RLS role of a report by default, instead of one screenshot of whichever tab opens first.

## Overview

A passing `fab-test playwright` run currently proves one thing about a report — that its
default tab rendered — because `page_ids` and `bookmark_ids` are only ever read from
`PLAYWRIGHT_PAGE_IDS`/`PLAYWRIGHT_BOOKMARK_IDS` or the `--page-ids`/`--bookmark-ids`
overrides, and `role` is a single scalar. With none set, `generate_test_cases` emits the
one empty-dimension row its docstring describes, the spec pops `pageName` and `bookmark`
off the embed config, and exactly one `screenshot.png` lands. The reference
implementation ([kerski/pbi-dataops-visual-error-testing](https://github.com/kerski/pbi-dataops-visual-error-testing))
discovers all three dimensions before running: pages from
`GET /v1.0/myorg/groups/{ws}/reports/{id}/pages`, bookmarks from
`bookmarksManager.getBookmarks()` with each bookmark's gzipped `state` decoded to read
`explorationState.activeSection` so a bookmark is attached to the page it belongs to, and
roles from the XMLA DMV `$SYSTEM.DISCOVER_POWERBI_ROLES` (`EVALUATE INFO.ROLES()` in its
UI path) — then emits a baseline row per page plus one row per page × bookmark, multiplied
by roles. Two-thirds of that already exists here and is unreachable: `FabricRestClient`
in `playwright_validation/service_client.py` has both `get_report_pages` and
`get_report_bookmarks`, each with tests, and **no production caller** — `invoke_playwright`
builds the *other* client (`build_fabric_service_client`) and never asks either question.
The cartesian expansion in `test_cases.py` is also the wrong shape for bookmarks, which
belong to one page each, and the single embed token minted once per report in
`_run_single_report` cannot carry more than one role. This epic wires discovery in, fixes
the matrix shape, and makes the token per-case — so the number of screenshots equals the
number of things actually tested.

---

## Discover report pages by default

Wire `FabricRestClient.get_report_pages` into config resolution so a service-resolved run
enumerates tabs instead of testing the default one.

**Requirements**:
- Given a service-resolved report and no page override, should emit one test case per page
  returned by the pages API, each carrying that page's `displayName` as `page_name` so the
  evidence directory and envelope row name the tab a human recognizes
- Given `--pages none` (or `PLAYWRIGHT_PAGE_IDS` unset with discovery disabled), should
  keep today's single default-page case, so an existing pipeline's case count cannot change
  without the caller opting in
- Given an explicit `--page-ids`, should skip discovery entirely rather than intersect —
  an override is a statement about what to test, not a filter over what was found
- Given the pages API returns 401/403/404 for a report the caller can resolve but not
  enumerate, should fall back to the single default-page case and say which call failed and
  which permission (`Report.Read.All`) resolves it, rather than failing the run
- Given a run with more than one page, should reuse the one already-authenticated client
  rather than acquiring a second access token per dimension

## Scope each bookmark to the page it belongs to

Replace the page × bookmark cartesian product in `generate_test_cases` with page-scoped
bookmarks, and teach discovery to read the association.

**Requirements**:
- Given a report whose bookmarks each target one page, should emit a baseline case for the
  page plus one case per bookmark *of that page*, and never a page paired with another
  page's bookmark — today's cartesian asks the embed SDK to apply a bookmark whose
  `activeSection` contradicts `pageName`, and the result is either a silent navigation away
  from the page under test or a spurious failure
- Given a PBIR report definition, should read bookmarks from `definition/bookmarks/` and
  each bookmark's `explorationState.activeSection` to attach it to a page —
  `get_report_bookmarks` currently looks for a single flat `definition/bookmarks.json` and
  drops the page association it would need
- Given a legacy (non-PBIR) report where `getDefinition` refuses, should run the pages and
  roles dimensions and report bookmarks as not discoverable for that report, naming PBIR
  enablement as the remedy — a report that cannot yield bookmarks is not a failed run
- Given a bookmark group with children, should test the children and not the group, which
  carries no state of its own

## Discover RLS roles from the semantic model definition

Read role names from the semantic model rather than requiring the caller to name one in
`PLAYWRIGHT_ROLE`.

**Requirements**:
- Given a semantic model with roles, should emit the page/bookmark matrix once per role and
  record the role on every emitted case, so a role that breaks one visual is attributable
- Given role discovery, should read `definition/roles/*.tmdl` (or TMSL `roles[]`) from the
  semantic model's `getDefinition` over the Fabric REST API — **not** the XMLA DMV the
  reference uses: XMLA needs ADOMD.NET and a capacity-backed endpoint, which contradicts
  the local-first constraint, while the definition is already reachable with the credentials
  and the API root this codebase has
- Given roles were discovered but `PLAYWRIGHT_USER_NAME` is unset, should fail before
  minting any token and name the variable — `GenerateToken` silently drops an `identities`
  entry with no username, so the run would otherwise pass while testing nothing under RLS
- Given `use_rls` false or no roles found, should emit the matrix once with an empty role,
  identical to today's shape

## Mint one embed token per role

`_run_single_report` builds a single `base_embed_config` and passes it to pytest as one
`PLAYWRIGHT_EMBED_CONFIG`; an embed token carries its RLS identity, so one token cannot
serve two roles.

**Requirements**:
- Given a matrix spanning N roles, should generate one embed token per distinct role and
  hand the spec a case-id-keyed map of embed configs, so each case embeds under its own
  identity
- Given the spec resolves a case with no matching embed config, should fail that case with
  the case id and the reason rather than silently reusing another case's token
- Given the run manifest, envelope, and any log line, should never contain an embed token —
  the map is passed the way the single config already is and stays out of every written
  artifact

## Report the matrix a run actually covered

A caller looking at output must be able to tell 1 page from 12 pages × 3 roles without
counting directories.

**Requirements**:
- Given a discovered matrix, should print the dimension counts and the resulting case count
  before running, and name which dimensions were discovered versus overridden versus
  unavailable
- Given a case id, should encode page, bookmark, and role so two cases of the same report
  cannot collide on one evidence directory and overwrite each other's `screenshot.png` —
  the current id is `report_page_bookmark` with no role, so every role of a page writes to
  the same path
- Given the envelope's `test_results` rows and the HTML report, should carry page name,
  bookmark name, and role as fields, so a failure reads as "page X under role Y" without
  parsing the case id
- Given a matrix large enough to exceed the per-artifact subprocess timeout, should say the
  case count and the timeout in the failure rather than reporting a render problem

## Document the three callers

**Requirements**:
- Given the fab-test skill, README, and QUICK-VALIDATION, should state that pages,
  bookmarks, and roles are discovered by default, and name the flag that turns each off
- Given the pipeline caller, should have a copy-pasteable YAML snippet showing the service
  principal permissions discovery requires (`Report.Read.All`,
  `SemanticModel.Read.All`) alongside what embedding already needed
