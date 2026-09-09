# PBIR TestRun.html Log Type Filter Epic

**Status**: 📋 PLANNED
**Goal**: Fix PBIR Inspector's native `TestRun.html` report so its "Error" Log Type filter actually shows Error findings.

## Overview

PBIR Inspector's own bundled report template (`FabInspector.ClientLibrary/Files/html/TestRunTemplate.html`, part of the `NatVanG/fab-inspector` CLI we invoke) filters results by Log Type client-side in JavaScript. Its `matchLogType()` function checks `item.LogType === 2` to decide whether a row is an Error, but the CLI's own `MessageTypeEnum` (`Error = 0, Warning = 1, Information = 2, ...`) never assigns `2` to a rule result — `ConvertRuleLogType` in `Inspector.cs` only ever returns `Error` (0) or `Warning` (1) for a `TestResult`, regardless of what a rule's `logType` string says. So selecting "Error" in the filter dropdown always returns zero rows, while "Warning" (which correctly checks `=== 1`) works. This is confirmed against the vendor's actual source (`MessageIssuedEventArgs.cs`, `Inspector.cs`, `TestRunTemplate.html`) — not a bug in fab-test's own rules file or Python parsing, both of which already match the real enum direction (`invoke_pbir_inspector.py`'s `_is_error_finding`: `LogType == 0` is error). Since the broken file ships baked into the PBIRInspectorCLI release rather than living in this repo, the fix is a post-processing patch on the emitted `TestRun.html`, following the exact precedent already set by `fix_favicon_link`/`fix_screenshot_images` in `invoke_pbir_inspector.py`: patch a known-broken literal marker, no-op if it's absent (already fixed upstream, or template changed), never raise.

---

## Patch the Log Type Filter

Add `fix_log_type_filter(report_path: Path) -> None` to `invoke_pbir_inspector.py`, alongside `fix_favicon_link` and `fix_screenshot_images`, and wire it into `_locate_native_html` so every emitted `TestRun.html` gets it.

**Requirements**:
- Given a `TestRun.html` containing the broken `matchLogType` marker (`item.LogType === 2 || normalizedLogType === "2"`), should rewrite it to check `=== 0`/`"0"` so the "Error" filter option matches Error-severity rows.
- Given a `TestRun.html` that does not contain the marker (already patched, or a template version that changed), should leave the file untouched and not raise.
- Given a missing or unreadable `report_path`, should return without raising, matching `fix_favicon_link`'s contract.
- Given the "Warning" filter's own check (`item.LogType === 1`), should remain unchanged — it is already correct.

---

## Correct the Stale Doc

`.github/skills/fab-inspector/SKILL.md`'s "Rules File Format" / "RuleLogTypes" section currently states `0 => Warning, 1 => Error`, which is backwards from the real `MessageTypeEnum` ordinals (`Error = 0, Warning = 1`) and from the rules file's actual string schema (`"logType": "error" | "warning"`, not an int).

**Requirements**:
- Given the "Rules File Format" example, should show `"logType": "warning"` (string), matching the real `Rule.LogType` schema and the vendored `pbi-inspector-custom-rules.json`.
- Given the "RuleLogTypes" callout, should read `Error = 0, Warning = 1` to match `MessageTypeEnum` and `invoke_pbir_inspector.py`'s own `_is_error_finding`.
