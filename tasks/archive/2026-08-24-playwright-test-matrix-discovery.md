# Playwright Test Matrix Discovery Epic

**Status**: ✅ COMPLETED (2026-08-24)
**Goal**: `fab-test playwright --env DEV` covers every page, page-scoped bookmark, and
RLS role of a report by default, instead of one screenshot of whichever tab opens first.

## Summary

A passing `fab-test playwright` run used to prove one thing about a report — that its
default tab rendered — because `generate_test_cases` only ever crossed the explicit
`--page-ids`/`--bookmark-ids` overrides, and `role` was a single scalar with one embed
token per report. Two-thirds of the fix already existed and was unreachable:
`FabricRestClient` in `playwright_validation/service_client.py` had `get_report_pages`
and `get_report_bookmarks`, each with tests, and no production caller —
`invoke_playwright` built the *other* client (`build_fabric_service_client`) and never
asked either question.

Discovery now runs by default, in a new `playwright_validation/discovery.py` module
(split out of `invoke_playwright.py` when the combined file crossed the source-module
hard budget): pages and their own bookmarks via the Fabric REST API's `getDefinition`,
matching each bookmark to its page through `explorationState.activeSection`, and RLS
roles via `definition/roles/<name>.tmdl` part paths on the semantic model's definition
— deliberately **not** the reference implementation's XMLA DMV, which needs ADOMD.NET
and a capacity-backed endpoint and would have broken the local-first constraint. A
discovery failure (missing `Report.Read.All`/`SemanticModel.Read.All`, or no live
network at all) logs a warning and falls back to today's single-case shape rather than
failing the run; `--pages none`/`--roles none` (or an explicit `--page-ids`) turn a
dimension off outright. Bookmark *groups* — which carry no exploration state of their
own, only their children do — are expanded into their children in both the legacy flat
`definition/bookmarks.json` shape and the per-file PBIR shape, rather than tested as a
group.

Because an embed token carries its RLS identity, a matrix spanning N roles needed N
tokens: `acquire_embed_configs` mints one per distinct role and hands the pytest spec a
role-keyed map (`PLAYWRIGHT_EMBED_CONFIGS`), which the spec's `_embed_config_for_role`
resolves per case — failing that one case by id and reason rather than silently reusing
another role's token if a role is ever missing from the map. Roles discovered with no
`PLAYWRIGHT_USER_NAME` abort before any token is minted, since `GenerateToken` silently
drops the RLS `identities` entry for an empty username and the run would otherwise pass
while testing no role at all. Case ids now encode page, bookmark, and role
(`Report_page1_bmk1_role-Manager`) so two roles of the same page can no longer collide on
one evidence directory and overwrite each other's `screenshot.png`; `test_results` rows
carry `page_name`/`bookmark_name`/`role` fields for a script or agent reading
`envelope.json` directly.

**Two requirements not carried through, on purpose, for scope**: the HTML report's
table still renders the fixed six-column shape (`normalize_test_results` in
`_analyzer_envelope.py`) — page/bookmark/role are readable from the case id and from
`envelope.json`'s raw rows, but not as separate report columns. And a matrix large
enough to exceed `--timeout`/`ANALYZER_TIMEOUT` still reports through the existing
subprocess-timeout path rather than a dedicated "N cases exceeded Xs" message. Both are
reasonable follow-ups, not landed here.

11/11 requirements groups implemented across 6 source files (`discovery.py` new,
`invoke_playwright.py`, `service_client.py`, `fabric_service_client.py`, `test_cases.py`,
`fab_test.py`/`fab_test_registry.py` for the top-level `--pages`/`--roles` passthrough),
122 new/updated tests, `discovery.py` at 100% coverage; full suite **1374 passed, 84%
coverage** (held), the only 6 failures pre-existing and confirmed unrelated on a clean
checkout (pql alias stdout diff, config-show key set, run-manifest stderr capture,
telemetry-reporting message match, unrelated to this epic). One real regression caught
and fixed before landing: the refactor pushed `_run_single_report` over the
statements-per-function ratchet (30 findings vs. 29 ceiling); extracting `_log_run_header`
brought it back to exactly 29 without raising the ceiling. Verified through the real
installed entry point — `fab-test playwright --help` shows `--pages {auto,none}` and
`--roles {auto,none}` alongside the existing flags. All three callers documented: the
fab-test skill's flag table and behavior note, README's new "Playwright tests every
page, bookmark, and role by default" section, and QUICK-VALIDATION's pipeline snippet
naming the two added permission grants.
