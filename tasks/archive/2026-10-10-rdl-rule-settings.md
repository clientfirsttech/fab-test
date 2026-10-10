# RDL Rule Settings Epic

**Status**: ✅ COMPLETED (2026-10-10)
**Goal**: Tune and disable `fab-test rdl` rules from `fab-test.yml` without forking the catalog, with every value validated as data.

## Overview

Teams need to raise QRY-07's line limit or turn off LAY-04 for a product that wants interactive sort, and today the only way is to fork `rdl-rules.json` through `--rdl-rules-path`, the drift that overlays exist to prevent. Overlays also can't say why a rule is off, and `extend` accepts an RDL rule with no check, which then shows `skip` forever. The checks stay in Python; the overlay becomes a validated data surface that `init` writes out from the catalog, so nothing from a config file is ever executed, evaluated, or rendered unescaped.

---

## Declared settings

**Status**: ✅ DONE (2026-10-10)

Each tunable rule declares its parameters in the catalog with a type and an inclusive range: QRY-07 `max_lines`, PRM-03 `max_parameters`, SUB-02 `max_subreports`, DS-04 `min_similarity`, ACC-06 `min_contrast`/`min_contrast_large`.

**Requirements**:
- Given a rule with a numeric threshold its check reads, should declare it under `settings` with `type` (`integer`/`number`), `min` and `max`
- Given the packaged catalog, should have every declared default inside its own range

---

## Settings overlay

**Status**: ✅ DONE (2026-10-10)

`rules.rdl.settings: {RULE-ID: {name: value}}` overrides a declared parameter for one run.

**Requirements**:
- Given a rule ID, setting name or value type the catalog doesn't declare, should exit 2 naming the valid choices
- Given a boolean, string, null, list, NaN or infinity where a number is declared, should exit 2, never coercing it
- Given a value outside the declared range, or a float where an integer is declared, should exit 2 naming the range
- Given an invalid overlay, should report the error on one line with no traceback and run no analysis

---

## Disable with a reason

**Status**: ✅ DONE (2026-10-10)

`disable` also takes `{RULE-ID: reason}`; the list form keeps working.

**Requirements**:
- Given a reason, should show it in that rule's `skip` row in `test_results`, the HTML report and telemetry
- Given a reason that isn't a string, is over 200 characters, or contains control characters, should exit 2
- Given a reason containing markup, should render it as text, never as HTML

---

## Honest extend

**Status**: ✅ DONE (2026-10-10)

Every built-in RDL check already has a catalog entry, so an extended rule is either a duplicate or has no check and would show `skip` forever.

**Requirements**:
- Given `rules.rdl.extend`, should exit 2 explaining that RDL checks are built in and pointing to `settings`, `severity` and `disable`

---

## Init writes the RDL section

**Status**: ✅ DONE (2026-10-10)

**Requirements**:
- Given `fab-test init`, should write `rules.rdl` with every declared setting commented out at its default, with the rule's name and range
- Given the catalog changes, should fail a test until the template matches it
- Given an existing `fab-test.yml`, should leave it untouched

---

## Effective settings shown

**Status**: ✅ DONE (2026-10-10)

**Requirements**:
- Given `fab-test config --show`, should list each overridden RDL setting and disabled rule with its origin

---

## Documentation

**Status**: ✅ DONE (2026-10-10)

**Requirements**:
- Given `docs/RDL-RULES.md`, should show each rule's settings with default and range, and how to override them
- Given the fab-test skill and QUICK-VALIDATION, should document `settings` and disable reasons for the agent and the pipeline

---

## Quality gates

**Status**: ✅ DONE (2026-10-10)

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
