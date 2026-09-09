# PBIR Non-Default Title visualGroup False Positive Epic

**Status**: ✅ COMPLETED
**Goal**: Stop `ENSURE_NON_DEFAULT_TITLES` from flagging `visualGroup` containers that already carry alt-text.

## Overview

`ENSURE_NON_DEFAULT_TITLES` (`src/fab_test/metadata/rules/pbi-inspector-custom-rules.json`)
reads `visual.visualContainerObjects.title` to decide whether a visual has a custom title.
Confirmed against Microsoft's published `visualContainer` schema
(`microsoft/json-schemas`, `fabric/item/report/definition/visualContainer`): a grouping
container is a structurally different shape of `visual.json` — its root object carries a
sibling `visualGroup` key (`displayName`/`groupMode`/`objects`) instead of a `visual` key,
and `visualGroup` has no `visualContainerObjects` concept at all; its own alt-text lives at
`visualGroup.objects.general[].properties.altText`. So `visual.visualContainerObjects.title`
always resolves to nothing for a `visualGroup` item — not because a title is genuinely
missing, but because the item has no `visual` object for the path to walk — and the
rule's `none` check reads that absence as a failure. This is not fixable by adding
`visualGroup` to the existing `visual.visualType` exclusion list (alongside `shape`/
`image`): `visual.visualType` is *also* absent on a `visualGroup` item, so that check was
already trivially passing and excluding nothing. The real fix is a new filter clause that
skips any item carrying a `visualGroup` key outright, mirroring the intent of the
`shape`/`image` exclusion (a container that cannot structurally carry a title) rather than
its mechanism. This ruleset is a JSON-logic document executed by the external PBI
Inspector binary, not fab-test's own Python, so it can't get a Python unit test —
verified red/green through the real CLI against a planted fixture instead.

---

## Exclude visualGroup From the Title Requirement

**Requirements**:
- Given a `visualGroup` container (with or without alt-text set), should not be flagged
  by `ENSURE_NON_DEFAULT_TITLES` — a group container has no title concept to satisfy.
- Given a non-`visualGroup`, non-`shape`, non-`image` visual with no non-empty custom
  title, should still be flagged (no change to existing behavior).

**Done**: added a `{"!": [{"var": "visualGroup"}]}` clause to the rule's filter
(`pbi-inspector-custom-rules.json`). Live-verified against a planted `visualGroup`
fixture added to `ThinReport` (`.fabric/artifacts/ThinReport.Report/definition/pages/
6c8284d4d466918cdb1c/visuals/7a1f92c4d8b344e0a112/visual.json`, alt-text set, no title,
matching the real Microsoft schema shape) via `fab-test pbir --artifact ThinReport
--format json`: red before the fix (visualGroup listed in
`ENSURE_NON_DEFAULT_TITLES`'s failing result), green after (only the genuine
title-less `cardVisual` remains). `ruff check src/` clean; narrowed
`pytest -k "pbir_inspector or skill_resource"` (63 passed, 2 skipped) and the full
suite both held.

**Found, not fixed — separate bug, flagged for a follow-up decision**: `ENSURE_ALTTEXT`
has the identical structural blind spot — it reads `visual.visualContainerObjects.general`,
which is also always absent for a `visualGroup`, so it can never see a group's real
alt-text at `visualGroup.objects.general[].properties.altText`. Every `visualGroup` with
a `tabOrder` will fail `ENSURE_ALTTEXT` regardless of whether alt-text is set (confirmed
live: the planted fixture still fails alt-text after this fix). Left untouched —
out of scope for the title-rule bug report that opened this epic.
