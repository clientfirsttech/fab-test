# Telemetry Init Scaffold Epic

**Status**: ✅ COMPLETED (2026-08-24)
**Goal**: `fab-test init` should scaffold the `telemetry.eventhouse` key it already supports, so a user can discover and enable telemetry from their own machine without reading the skill or the source.

## Overview

`telemetry.eventhouse.uri`/`.database` in `fab-test.yml` already works end to end — `_config.py` validates it, `_telemetry.py` resolves it env-var-first, `eventhouse_logger.py` ships to it ([Eventhouse Shipping](archive/2026-08-22-eventhouse-shipping.md)). But `_FAB_TEST_YML_TEMPLATE`, the file `fab-test init` writes, documents every other valid key (`artifact_dir`, `jobs`, `format`, `timeout`, `environment`, `workspace`, `rules`) and skips this one entirely. A user who runs `init` and reads the generated file — which is the whole point of a commented scaffold — has no way to know shipping telemetry is possible. One destination for the whole repository is the intended shape; this is purely a documentation-in-the-scaffold gap, not a resolution change.

---

## Scaffold The Telemetry Key

**Requirements**:
- Given `fab-test init`, the generated `fab-test.yml` should include a commented `telemetry.eventhouse.uri`/`.database` example, in the same style as the existing commented `rules:` block
- Given the comment, it should say what the two keys are (Eventhouse cluster URI and database name) and that either can instead be set via `EVENTHOUSE_URI`/`EVENTHOUSE_DATABASE`, matching the precedence note `_telemetry.py` already documents
- Given an existing repository whose `fab-test.yml` predates this change, `fab-test init` should not overwrite it — matches the existing "never overwrites, reports and leaves untouched" behavior (`fab_test.py:2103`)
- Given tests covering `_FAB_TEST_YML_TEMPLATE`'s content, should assert the new commented block is present

---

## Documentation For All Three Callers

**Requirements**:
- Given the `fab-test` skill (`.github/skills/fab-test/SKILL.md`) Telemetry section, should note that `fab-test init` now scaffolds the key
- Given README/docs, should show the scaffolded example so a reader following `init` output sees the same key documented twice, not once
- Use the `document` command so the skill and README don't drift apart, per the Definition of Done in [vision.md](../vision.md)
