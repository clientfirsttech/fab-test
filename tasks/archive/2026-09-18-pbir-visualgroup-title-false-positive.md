# PBIR Non-Default Title visualGroup False Positive Epic

**Status**: ✅ COMPLETED (2026-09-18)
**Goal**: Stop `ENSURE_NON_DEFAULT_TITLES` from flagging `visualGroup` containers that cannot carry a visual title.

## Overview

WHY a `visualGroup` item has a different PBIR schema from a visual: it owns `visualGroup.objects.general[].properties.altText`, not `visual.visualContainerObjects.title`. The title rule therefore needed to exclude the container shape rather than interpret its missing visual-title path as a failure.

---

## Exclude visualGroup From the Title Requirement

**Requirements**:
- Given a `visualGroup` container, should not be flagged by `ENSURE_NON_DEFAULT_TITLES`.
- Given a non-`visualGroup`, non-`shape`, non-`image` visual without a custom title, should remain flagged.

**Done**: added `{"!": [{"var": "visualGroup"}]}` to the rule filter. Live red/green validation against the planted `ThinReport` fixture showed the group omitted while a genuine title-less card remained. `ruff check src/`, focused tests, and the full suite had previously passed; `fab-test pbir --artifact ThinReport --format json` completed without errors in this review.

**Follow-up identified, not included**: `ENSURE_ALTTEXT` also reads a visual-only path and can falsely flag `visualGroup` alt-text. This needs a separate decision and epic.