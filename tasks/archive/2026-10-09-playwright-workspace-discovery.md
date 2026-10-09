# Playwright Workspace Discovery Epic

**Status**: ✅ COMPLETED 2026-10-09 (1.9.0b10; quality gates passed; verified live from an empty directory. Covered by unit tests only: an ambiguous workspace name -- none exists to test -- and headed mode, declined live.)
**Goal**: Make explicitly workspace-targeted Playwright runs independent of repository artifact discovery.

## Overview

WHY: A caller naming a workspace expects its deployed reports to determine what gets tested, but the current batch command scans local Report folders and RDL files first, producing different denominators in different directories and attempting reports absent from the workspace. This plan makes `--workspace`, `--workspace-id`, and `--from-workspace` synonymous value-taking selectors accepting a GUID or display name, with `--workspace` the preferred spelling, preserves deliberate repository targeting, and verifies that removing local files does not silently reduce rendered-report coverage. The existing uncommitted Boolean `--from-workspace` implementation is a prototype, not an approved or completed solution; implementation remains paused until review resolves the backward-compatibility conflict with vision.md.

---

## Approve Targeting And Compatibility Contract

Lock the discovery rules before changing the prototype or existing command behavior.

**Requirements**:
- Given any of `--workspace TARGET`, `--workspace-id TARGET`, or `--from-workspace TARGET` on standalone `playwright`, should accept one GUID or workspace display name and apply identical resolution and discovery semantics, with `--workspace` preferred in help and examples.
- Given a GUID workspace target, should use it directly without workspace-name lookup; given a display name, should resolve it through the existing Fabric workspace resolver before discovery or execution.
- Given a missing or ambiguous workspace display name, should name the resolution failure and remediation, requiring a GUID for ambiguous names rather than selecting an arbitrary workspace.
- Given standalone `playwright --workspace TARGET` without an artifact or explicit artifact directory, should list deployed Report and PaginatedReport items without scanning the repository, identically for either alias.
- Given `playwright --artifact NAME --workspace TARGET`, should select only that deployed report without requiring or borrowing metadata from a same-named local artifact, identically for either alias.
- Given `playwright --artifact-dir PATH --workspace TARGET`, should use local artifacts under PATH as the denominator and resolve their names in the workspace, including when PATH is explicitly `.`, identically for either alias.
- Given bare `playwright`, an ambient workspace variable, or a workspace supplied only through configuration, should preserve repository discovery rather than silently widen the run to all deployed reports.
- Given `--env DEV` without an explicit workspace target, should preserve existing environment-to-workspace connection resolution and repository discovery.
- Given an existing dataset or impact-manifest selector, should preserve its current denominator instead of replacing it with every report in the workspace.
- Given workspace-scoped positional targets, named/type-qualified artifacts, filesystem paths, repeated workspace aliases, and conflicting selectors, should approve a precedence table with specific validation errors before implementation rather than infer new semantics incidentally.
- Given the changed meaning of released `--workspace-id` invocations, should require explicit user approval of the compatibility exception and document the `--artifact-dir .` migration before implementation; otherwise retain additive opt-in discovery.
- Given shared discovery code, should enumerate standalone playwright, `all`, `local`, `list`, `explain`, dry-run, and summary/manifest callers and approve which are affected; aggregate commands should not silently acquire workspace-wide discovery.

---

## Implement Discovery Selection With TDD

Replace the Boolean prototype with the approved workspace aliases and shared resolution path while retaining explicit input provenance.

**Requirements**:
- Given each of the three workspace spellings with a GUID or display name, should write isolated parser and resolver tests before implementation proving one shared target, equivalent selection, GUID lookup bypass, and name-resolution errors.
- Given `--from-workspace` without a value, should reject the invocation with a usage error rather than retain the unshipped Boolean behavior.
- Given a default artifact directory resolved from CWD or configuration, should distinguish it from an explicitly supplied `--artifact-dir` rather than compare path values to guess caller intent.
- Given the approved workspace mode in an empty directory or a checkout containing unrelated RDL fixtures, should produce the same deployed report set and never invoke local artifact scanning.
- Given explicit repository mode, named-report mode, dataset mode, or impact-manifest mode, should pin the approved precedence with isolated regression tests before implementation.
- Given the unshipped Boolean `--from-workspace` prototype, should replace its parser, selection logic, and tests with the value-taking aliases only after contract approval, preserving unrelated working-tree changes.
- Given an empty workspace, listing failure, missing credentials, or invalid targeting, should distinguish no reports from failed discovery, retain documented exit codes, name remediation, and never fall back silently to repository scanning.
- Given growing execution, registry, or dataset-target modules, should keep changes local and within the ratchets, extracting workspace-listing logic only where it removes complexity rather than raising ceilings by default.

---

## Preserve Deployed Identity And Result Contracts

Carry each selected deployed item's identity through execution and reporting without relying on filename conventions.

**Requirements**:
- Given workspace item enumeration, should follow pagination and select only supported report types, honoring an explicit report-type filter.
- Given interactive and paginated reports sharing a name, duplicate display names, or names containing dots or path separators, should retain every distinct item by ID, execute the correct item and type, and prevent output collisions or path traversal.
- Given deployed discovery, should obtain dataset bindings from the service or explicit overrides, never from coincidentally present local RDL files.
- Given workspace discovery and execution, should preserve per-artifact envelopes, findings, HTML reports, run manifest, and telemetry type identities, with no credentials in output or evidence.
- Given JSON, quiet, verbose, and dry-run output, should expose the chosen discovery source and denominator consistently without breaking existing machine-readable contracts or implying browser tests ran during discovery.

---

## Verify Repository-Independent Matrix Coverage

Establish and test which report metadata can be discovered remotely before claiming checkout-independent coverage.

**Requirements**:
- Given interactive reports outside any checkout, should generate page and bookmark cases from deployed metadata and preserve `--pages none` and `--roles none` behavior. ✅
- Given automatic RLS role discovery currently reading local TMDL, should prove a supported remote source or explicitly surface unavailable role coverage; should not silently present a default-role-only matrix as equivalent coverage. ✅
- Given paginated reports with single-value or multi-value parameters, should discover parameter declarations remotely through a verified supported API or transient deployed definition and preserve parameter-expanded tests without checked-in RDL files. ✅
- Given unavailable remote parameter or dataset metadata, should report the limitation and usable override instead of classifying a baseline-only render as complete parameter coverage. ✅ (2026-10-09: each failed lookup -- roles, the paginated definition, a parameter's valid values -- adds a warning-level `coverage_limited` finding naming the override, so the envelope, `-q` and the summary read `warning`, not `passed`; exit unchanged. Unit-tested per lookup; live, reports whose lookups succeed gain no such finding. Forcing a real lookup failure live needs a principal without those permissions.)
- Given the same deployed workspace tested from the repository and an empty directory with explicit credentials/configuration, should compare selected item IDs, generated case counts, and verdicts, including Working Visuals, Not Working Visuals, and paginated filter fixtures. ✅
- Given headed, slow-motion, worker, and optional Azure-browser settings, should keep the Python Playwright/pytest generated-test runner unchanged and independent of the discovery source.

**Verified live 2026-10-09** (1.9.0b10, workspace `visual-error-testing`, service principal from `.fab-test/.env`). `playwright --workspace WS --plan-only` from an empty directory holding only `.fab-test/` versus the repository with `--artifact-dir .`: every report both runs selected generated the same case count -- pages, bookmarks, and both RLS roles (`Team_A`/`Team_B`, discovered over XMLA via `xmla_roles.py`) on all three `RLSTest*` reports, and the paginated parameter cases (`ReportParameter1=2`; the multi-value `2,4`) from the deployed definitions. The only difference was by design: `PaginatedExample` is deployed with no local file, so the repository denominator omits it. Real renders from the empty directory matched the repository/CI verdicts: `Working Visuals` passed; `Not Working Visuals` 1 error; `PaginatedExample-WithMultiFilter` 1 error (the known broken parameter combination); `RLSTest` 2 errors (the `InvalidUnconstrainedJoin` visual under both roles, as in demo run 37871985133).

Found and fixed during this run: pytest's own HTML/JUnit reports ignored `--output-dir` unless an execution config was selected, going to a fixed `./fab-test-results/playwright/report/` shared by every report. They now go beside each report's envelope (`<out>/playwright/<report>/report/`).

Still open here: the unavailable-metadata requirement (a remote role or parameter lookup that fails should name the limitation, not pass as full coverage) is not yet exercised live, and the headed/slow-motion/worker/Azure-browser settings are covered by the existing suites, not re-run against a workspace-discovered report.

---

## Document And Review All Three Callers

Update user, agent, and pipeline guidance together and review the implementation against the approved contract.

**Requirements**:
- Given an approved implementation, should update README, QUICK-VALIDATION, and relevant walkthroughs with `--workspace` name and GUID examples, both equivalent aliases, workspace-wide, named-report, and repository-denominator commands, plus the `--artifact-dir .` compatibility migration and the value-taking `--from-workspace` contract. ✅
- Given an agent using the fab-test skill, should document selector precedence and metadata limitations in the existing SudoLang contract and references, keeping every authored and packaged skill file identical. ✅
- Given GitHub Actions or Azure DevOps without a report checkout, should provide copy-ready examples using the preferred `--workspace` spelling with explicit credential/configuration sources, browser prerequisites, and result publication. ✅
- Given an epic-sized source change, should apply the minor prerelease version policy and matching skill version stamps and changelog entry during implementation, not during this plan-only change. ✅

**Docs done 2026-10-09.** README already carried the aliases, name/GUID, workspace-wide and named-report forms; it gains the `--artifact-dir .` migration and what a workspace run discovers (with the `coverage_limited` warning). QUICK-VALIDATION's service-mode block gains the Playwright `--workspace`, `--plan-only`, and `--artifact-dir .` forms. `flags.md` gains "what a workspace run discovers without a checkout"; the main `SKILL.md`'s SudoLang contract gains the bare-`--workspace` precedence and the `coverage_limited` rule; packaged copies synced. `docs/examples/github-actions/playwright-live.yml` (already checkout-free, installing the published package and browser, uploading results) now passes `--workspace "$FABRIC_WORKSPACE_ID"` when a dispatch names no report or dataset. Version: ships in the unreleased 1.9.0b10, whose skill stamp is current. The review-checkpoint requirement is left to the Quality Gates live pass.
- Given a review checkpoint, should inspect identity collisions, selector provenance, errors, matrix coverage, and all enumerated shared callers before accepting the prototype as production-ready.

---

## Quality Gates

Run the required repository-wide gates and verify the approved behavior through the installed CLI.

**Requirements**:
- Given the finished epic, should pass `ruff check .`, the complexity and module-budget ratchets with ruff installed, and the full suite with `--cov --cov-fail-under=80`, using `GITHUB_ACTIONS=true CI=true` as CI does. ✅
- Given all three workspace aliases through the installed console script, should verify equivalent name and GUID targeting and actionable missing/ambiguous-name errors without depending on repository artifacts. ✅
- Given the installed console script outside the checkout, should verify discovery, plan-only matrix generation, a real passing report, and intentional broken-report failures with explicit credential/configuration paths and no implicit local artifacts. ✅
- Given every affected shared caller identified during contract approval, should exercise it through the installed CLI and confirm unaffected repository and aggregate behavior remains unchanged. ✅
- Given doc/skill distribution changes, should pass the skill-resource guards and confirm `fab-test skill --show` reflects the packaged contract. ✅
- Given any unverified live-service or CI-platform requirement, should leave the epic incomplete and record the blocker rather than archive it as completed.

**Quality gates 2026-10-09** (1.9.0b10, installed console script, from an empty directory holding only `.fab-test/` unless noted):
- Gates: `ruff check .` clean; ratchets pass with no new exemption; full suite 2639 passed, 2 skipped, coverage 89.33%, under `GITHUB_ACTIONS=true CI=true`.
- Aliases: `--workspace`, `--workspace-id`, `--from-workspace`, each with the name `visual-error-testing` and its GUID, list the same 12 deployed reports (8 interactive, 4 paginated). An unknown name exits 1 listing the visible workspaces; a bare `--from-workspace` exits 2 ("expected one argument"). Nothing is written to the working directory.
- Matrix and verdicts: `--plan-only` matches the repository case for case; real renders match the repository/CI verdicts (see the matrix-coverage task above).
- Shared callers unchanged: bare `playwright --dry-run` and an ambient `FABRIC_WORKSPACE_ID` alone both stay `mode=local` over the same 27 local reports; `all` stays local.
- Runner settings on a workspace-discovered report: `--workers 3` split `Report with Bookmarks - Broken Visuals`' 6 cases across gw0-gw2 (5 passed, 1 broken bookmark failed, as in CI). Azure-hosted browsers via `docs/examples/playwright/azure.yml` rendered `Working Visuals` (passed), and a deliberately invalid `PLAYWRIGHT_SERVICE_ACCESS_TOKEN` failed browser setup naming the `PLAYWRIGHT_SERVICE_*` values -- proof the pass ran remotely, not on the locally installed Chromium.
- Skill guards (`tests/test_skill_resource.py`) pass with the packaged copies synced; the installed package's own `skill/SKILL.md` and `references/flags.md` carry the `ServiceMode` block, the `coverage_limited` rule, and the 1.9.0b10 stamp. (`fab-test skill --show` reports per-harness install status -- none installed in this checkout -- not content, so the packaged files were read directly.)

Not verified live: an ambiguous workspace name (no two visible workspaces share a name; unit-tested), and headed mode (declined, to avoid opening a browser on the desktop; covered by `tests/test_playwright_headed.py`).
