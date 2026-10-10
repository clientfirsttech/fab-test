# RDL Multi-Value DAX Parameter Epic

**Status**: 🔄 IN-PROGRESS
**Goal**: `fab-test rdl` flags a multi-value report parameter passed into a semantic-model (DAX) query without `RSCustomDaxFilter`, the query shape that breaks when a user selects more than one value.

## Overview

A paginated report on a Power BI semantic model (`PBIDATASET`) sends its query parameters into DAX. A multi-value parameter used directly as `@Param` (`= @Param`, `IN {@Param}`, `TREATAS({@Param}, ...)`) receives a list it can't handle. Report Builder's `RSCustomDaxFilter(@Param, EqualToCondition, [Table].[Column], Type)` placeholder is the supported way in: at run time it expands into a `FILTER` over the column's values, one OR-ed equality per selection. Credit: Chris Webb, [Power BI Report Builder And RSCustomDaxFilter](https://blog.crossjoin.co.uk/2019/11/03/power-bi-report-builder-and-rscustomdaxfilter/) (2019, updated 2024). No existing rule covers this; PRM-04 is MultiValue + Nullable.

---

## PRM-07 check

**Status**: ✅ DONE (2026-10-10)

New catalog rule PRM-07, "Multi-value parameters reach DAX through RSCustomDaxFilter", severity error, Tier A, `"status": "planned"` until its fixtures land.

**Requirements**:
- Given a PBIDATASET dataset whose QueryParameter's value is `=Parameters!X.Value` for a MultiValue parameter X, and whose own CommandText has no `RSCustomDaxFilter(@<QueryParameter Name>`, should fire once per (dataset, query parameter)
- Given `RSCustomDaxFilter(@P, ...)` in any letter case or spacing, should pass
- Given a single-value parameter, a non-PBIDATASET source, an indexed `Parameters!X.Value(0)`, or a `Join(Parameters!X.Value, ...)` value (one string, the PATHCONTAINS workaround), should pass
- Given a multi-value parameter used only in the dataset's `<Filters>`, should pass (report-side filtering works; QRY-01 already flags it)
- Given `RSCustomDaxFilter` only in `rd:DesignerState`, should still fire: only the dataset's own CommandText runs
- Given a QueryParameter named differently from its report parameter, should match on the QueryParameter's `@name`
- Given the rule, should credit the crossjoin.co.uk post in `source_urls`

---

## PRM-07 fixtures

**Status**: 📋 PLANNED, blocked on `tools/generate_rdl_fixtures.py` and `tools/deploy_rdl_fixtures.py` being committed to `dev`

Add `PRM-07` (multi-value `Alignment` filtered as `AlignmentDim[Alignment] = @Alignment`) and `PRM-07-Pass` (the same through `RSCustomDaxFilter(@Alignment, EqualToCondition, [AlignmentDim].[Alignment], String)`) to the generator, round-trip both through the deploy tool, then set PRM-07 `"status": "active"` and regenerate docs/RDL-RULES.md.

**Requirements**:
- Given each fixture, should be accepted by the service and saved from `getDefinition`; a rejection keeps PRM-07 planned with the reason recorded here
- Given `PRM-07.rdl`, should trip only PRM-07; given `PRM-07-Pass.rdl`, should trip no rule
- Given both rendered with two values selected, should confirm `PRM-07.rdl` errors and `PRM-07-Pass.rdl` renders, so the error severity rests on a real run

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
