# Playwright Workspace Discovery Epic

**Status**: 🔄 IN-PROGRESS (targeting/compatibility approved; shared alias and workspace-wide discovery implemented and live-verified; remote RLS/paginated-parameter coverage and full documentation remain)
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
- Given an approved implementation, should update README, QUICK-VALIDATION, and relevant walkthroughs with `--workspace` name and GUID examples, both equivalent aliases, workspace-wide, named-report, and repository-denominator commands, plus the `--artifact-dir .` compatibility migration and the value-taking `--from-workspace` contract.
- Given an agent using the fab-test skill, should document selector precedence and metadata limitations in the existing SudoLang contract and references, keeping every authored and packaged skill file identical.
- Given GitHub Actions or Azure DevOps without a report checkout, should provide copy-ready examples using the preferred `--workspace` spelling with explicit credential/configuration sources, browser prerequisites, and result publication.
- Given an epic-sized source change, should apply the minor prerelease version policy and matching skill version stamps and changelog entry during implementation, not during this plan-only change.
- Given a review checkpoint, should inspect identity collisions, selector provenance, errors, matrix coverage, and all enumerated shared callers before accepting the prototype as production-ready.

---

## Quality Gates

Run the required repository-wide gates and verify the approved behavior through the installed CLI.

**Requirements**:
- Given the finished epic, should pass `ruff check .`, the complexity and module-budget ratchets with ruff installed, and the full suite with `--cov --cov-fail-under=80`, using `GITHUB_ACTIONS=true CI=true` as CI does.
- Given all three workspace aliases through the installed console script, should verify equivalent name and GUID targeting and actionable missing/ambiguous-name errors without depending on repository artifacts.
- Given the installed console script outside the checkout, should verify discovery, plan-only matrix generation, a real passing report, and intentional broken-report failures with explicit credential/configuration paths and no implicit local artifacts.
- Given every affected shared caller identified during contract approval, should exercise it through the installed CLI and confirm unaffected repository and aggregate behavior remains unchanged.
- Given doc/skill distribution changes, should pass the skill-resource guards and confirm `fab-test skill --show` reflects the packaged contract.
- Given any unverified live-service or CI-platform requirement, should leave the epic incomplete and record the blocker rather than archive it as completed.