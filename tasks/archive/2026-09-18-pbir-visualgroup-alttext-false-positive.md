# PBIR visualGroup Alt-Text False Positive Epic

**Status**: ✅ COMPLETED (2026-09-18)
**Goal**: Make `ENSURE_ALTTEXT` read alt-text from non-decorative `visualGroup` containers.

## Overview

WHY grouped report elements need their group-level alt-text evaluated correctly: `visualGroup` containers store it separately from ordinary visuals, so the existing visual-only path reported a false missing-alt-text violation.

---

## Read Group Alt-Text

The PBIR Inspector rule now checks the schema-appropriate alt-text path without changing ordinary-visual validation.

**Requirements**:
- Given a non-decorative `visualGroup` with non-empty `visualGroup.objects.general[].properties.altText`, should not be flagged by `ENSURE_ALTTEXT`.
- Given a non-decorative `visualGroup` with missing or empty alt-text, should remain flagged by `ENSURE_ALTTEXT`.
- Given a non-group non-decorative visual with missing alt-text, should remain flagged by `ENSURE_ALTTEXT`.

**Done**: `ENSURE_ALTTEXT` branches on the PBIR container shape, using `visualGroup.objects.general` for groups and retaining `visual.visualContainerObjects.general` for ordinary visuals. The planted `ThinReport` group fixture was red before the change despite non-empty alt-text; it is absent from the finding after the change, while the two existing ordinary visuals remain. Clearing the group alt-text temporarily restored its finding, confirming both paths. The fab-inspector skill documents this behavior. Version bumped to `1.5.0.dev1`.