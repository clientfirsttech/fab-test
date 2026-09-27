# RDL Static Analysis Epic

**Status**: 🔄 IN-PROGRESS (3/8 tasks: rule catalog+skeleton, flat-file discovery, subcommand+aggregate wiring)
**Goal**: `fab-test rdl` runs the 28 Tier A rules from [plan/rdl-rule-set.md](../plan/rdl-rule-set.md) against local `.rdl` files, with no workspace and no new dependency.

## Overview

Paginated reports are the only report type fab-test finds but never checks: `.rdl` files are read only to feed Playwright's rendering, so unused datasets, report-side filters and joins, page overflow, invalid parameter combinations, and missing alt text all surface after publish, if at all. No upstream analyzer reads RDL (Fab Inspector is PBIR/JSON only), so like `prompt_lint` this is an in-house analyzer. The checks are written in Python on stdlib `xml.etree`, and a JSON rule catalog holds each rule's ID, severity, source, and disabled flag, tuned through the same `rules.<analyzer>` overlay in `fab-test.yml` that BPA and PBIR use. Envelope, exit code, HTML report, CI annotations, and telemetry all follow the existing analyzer contract. Tier B (heuristic) and Tier C (cross-file, service, or manual) rules are left for follow-up epics.

---

## Fixture policy

Each remaining task adds one or a small set of real `.rdl` fixtures to `.fabric/artifacts/` — named for what they exercise (e.g. `PaginatedExample-SubreportInTablix.rdl`) — alongside the checks that read them, mirroring `PaginatedExample-BrokenRDL.rdl` and the existing broken-visuals samples. Real Report Builder output over hand-typed XML wherever the user can supply it; synthesized (an edited copy of an existing sample) otherwise. Fixtures land with their task, not ahead of it — a fixture with no check yet reading it goes stale silently. These feed both the `rdl` marker's contract tests and `fab-test rdl` used as a demo.

## Rule catalog and analyzer skeleton

Add `metadata/rules/rdl-rules.json` and an `invoke_rdl_lint.py` wrapper that parses an `.rdl` file and writes the standard envelope, with no rules yet.

**Requirements**:
- Given an `.rdl` in any RDL schema version (2008, 2010, 2016), should resolve elements by local name under the report's default namespace, so rules don't hard-code one xmlns
- Given a malformed or unreadable `.rdl`, should report one `error` finding naming the parse failure rather than raising or passing
- Given a `rules.rdl` overlay in `fab-test.yml` (`disable`, `severity`, `extend`), should apply it exactly as `rules.bpa`/`rules.pbir` do; today `_config.py` rejects any analyzer key other than those two, so `rdl` joins `_RULE_OVERLAY_ANALYZERS`, gains an `apply_rdl_overlay`, and is added to the config schema
- Given a High finding, should mark it `error` and fail the run; given Medium or Low, should mark it `warning` and leave the exit code at success, and an overlay's `severity` should use the existing `error`/`warning`/`info` labels, not High/Medium/Low
- Given any finding, should carry the rule ID, the offending element's `Name` attribute (or its element path when unnamed), a one-line remediation, and the catalog's source reference
- Given `--report` or `--open-report`, should call `attach_report` and populate `test_results` in the rule shape (`rule`/`severity`/`object`/`message`/`status`), including passed rules, so `report.html` gets the shared table, filter, and search; `prompt_lint` and `pqlint` skip `attach_report`, so they are not the model to copy
- Given the envelope, its `analyzer` field, the registry key, and the results folder should all be `rdl`, so telemetry, annotations, and reports show one name (unlike `pbir_a11y`/`a11y`)

---

## Flat-file discovery for static analyzers

Let `discover_artifacts` return flat files for a file-suffix glob (`*.rdl`), since today it matches only `*.Type` folders.

**Requirements**:
- Given a target of `Sales`, `Sales.rdl`, or a path to `Sales.rdl`, should select that one file; given a target typed as a folder artifact (`Sales.Report`), should select nothing for `rdl`
- Given the result folder under the artifact directory, should never rediscover it as an artifact
- Given the existing folder-based analyzers, should leave their discovery unchanged — exercise `_run_analyzer`, `list`, `explain`, and the aggregate summary through the real CLI before and after

---

## `fab-test rdl` subcommand and aggregate wiring

Register `rdl` at every touch point in the `aidd-analyzer-contract` checklist, including `analyzers.json` (`rdl`, a `PaginatedReport` static entry, `fab_test_all`) and `_LOCAL_ANALYZERS`.

**Requirements**:
- Given `fab_test_registry.py` (977/977) and `fab_test_parser.py` (1045/1050) are at their `test_module_budget` ceilings, should split on each module's seam or record the growth in its exemption before the suite fails on it
- Given `fab-test list` and `fab-test explain rdl`, should show `rdl` with its display name and its rules catalog path, like `bpa` and `pbir`
- Given the `rdl` pytest marker, should be declared in both `pytest.ini` and conftest's `_ANALYZER_MARKERS`/`_MARKER_SUFFIX`
- Given no external tool installed, `doctor` should report `rdl` ready, since it needs only Python
- Given `fab-test all` or `fab-test local` in a repo containing `.rdl` files, should run `rdl` on each alongside the existing analyzers, and show each file once in the summary
- Given a repo with no `.rdl` files, `all` should skip `rdl` without an error or empty result folder
- Given `fab-test all --open-report`, the run index should link each `.rdl`'s report alongside the other analyzers' reports, once per file
- Given telemetry enabled, an `.rdl` record should report `artifact_type` as `PaginatedReport`, not `rdl`; `_build_telemetry_payload` derives the type from the path suffix and is shared by every analyzer, so re-run a folder analyzer's telemetry after the change

---

## Structure and data source rules

Implement STR-01, DS-01, DS-02, DS-05, and DS-07.

**Requirements**:
- Given a connect string containing a password or secret, DS-01 should say that credentials are embedded without echoing the value into stdout or the envelope
- Given a dataset whose name appears only inside an expression (e.g. `Lookup(..., "Sales")`), DS-02 should treat it as used
- Given a `PBIDATASET` or `PQO` data source, DS-05 and DS-07 should apply only their relational form to SQL providers; DS-05 should flag a bare `EVALUATE 'Table'` as the DAX equivalent of `SELECT *`

---

## Query pushdown rules

Implement QRY-01 through QRY-07.

**Requirements**:
- Given `PaginatedExample-WithFilter.rdl` and `PaginatedExample-WithMultiFilter.rdl`, QRY-01 should flag their `Filters` blocks, pinning the rule to real Report Builder output
- Given a type-conversion function applied to the same field in more than one expression, QRY-05 should report once per field, not once per occurrence
- Given CommandText over the line threshold or with several CTEs, QRY-07 should fire only for SQL providers, with the threshold held in the catalog entry

---

## Parameter rules

Implement PRM-01, PRM-03, PRM-04, and PRM-05.

**Requirements**:
- Given `MultiValue` true together with `Nullable` true, PRM-04 should fail as High; given `MultiValue` with `AllowBlank`, should not fire
- Given separate parameters named like Year, Month, and Day, PRM-03 should suggest a single DateTime parameter even when the total count is under the threshold
- Given a parameter referenced as `Parameters!X.Label` rather than `.Value` in a textbox, PRM-05 should count it as displayed

---

## Layout and subreport rules

Implement LAY-01 through LAY-06, SUB-01, and SUB-02.

**Requirements**:
- Given page and body sizes in mixed units (`in`, `cm`, `mm`, `pt`), LAY-01 should normalize before comparing body width plus margins against page width
- Given a `Subreport` nested at any depth inside a `Tablix`, should emit a single finding carrying both LAY-03 and SUB-01, not two findings
- Given 50 or more `Subreport` elements, SUB-02 should fail as High

---

## Accessibility rules

Implement ACC-01, ACC-02, ACC-03, and ACC-08.

**Requirements**:
- Given a `ToolTip` that is an expression (`=...`), ACC-01 should treat it as present and ACC-02 should not judge its wording
- Given a chart `ToolTip` equal to the chart's own `Name` or a default like `Chart1`, ACC-02 should flag it as a placeholder rather than as missing
- Given a `Tablix` with no `ToolTip`, should report ACC-03 only, not ACC-01 as well, so one gap produces one finding

---

## Documentation

Update all three callers with the `document` skill, then bump the MINOR version.

**Requirements**:
- Given the README, should show `fab-test rdl` running on a sample `.rdl` and list each rule ID with its severity and source
- Given the fab-test skill, should document `rdl`'s targets, exit codes, and finding shape in SudoLang, with the packaged copy kept identical (`tests/test_skill_resource.py`)
- Given the pipeline docs, should give a copy-paste YAML step that fails only on High findings
