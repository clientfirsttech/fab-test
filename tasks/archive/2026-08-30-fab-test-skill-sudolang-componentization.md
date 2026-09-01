# fab-test Skill SudoLang & Componentization Epic

**Status**: ✅ COMPLETED — 3 of 3 tasks done
**Goal**: fab-test's own skill file is authored in SudoLang for its behavioral contract, split into a small main file plus `references/` components so an agent loading it doesn't pay for the whole 1065-line reference manual on every use, and a durable check keeps it from drifting back to a monolithic prose file.

## Overview

`.github/skills/fab-test/SKILL.md` grew to 1065 lines of prose/tables/examples — every load costs the full file even when only one subcommand's flags are needed, and nothing enforces the SudoLang conventions `aidd-sudolang-syntax` already documents for this project's skills. Following the `dataflows-authoring-cli` precedent (short main file + `references/` folder, linked by a table of contents), split the reference-heavy sections out and rewrite the behavioral/contract sections — exit codes, output guarantees, precedence rules, install idempotency — as SudoLang `Interfaces`/`Constraints`/`fn` blocks, while flag tables and worked examples stay plain markdown where SudoLang doesn't compress them usefully.

---

## Task: Rewrite and split the skill content

Convert `.github/skills/fab-test/SKILL.md`'s Agent Contract section (exit codes, JSON stdout guarantee, discoverability, run manifest shape) into SudoLang, and split the remaining sections into `references/`:
- `references/targeting-and-discovery.md` (Targeting, Discovery)
- `references/credentials.md`
- `references/reports.md`
- `references/configuration.md`
- `references/flags.md` (Global Flags + all Subcommand-Specific Flags)
- `references/operations.md` (Dry Run, Output Verbosity, Result Locations, Tool Resolution, Pre-flight Checks)
- `references/source-files.md`

**Requirements**:
- Given the rewritten main `SKILL.md`, should preserve every fact currently in the Agent Contract section — no behavior silently dropped in the SudoLang rewrite
- Given the main file, should carry a table of contents linking each `references/*.md` file with a one-line "when to read it" note
- Given a section moved to `references/`, should keep its content byte-equivalent in meaning (light reformatting only), not summarized or shortened
- Given the main file after the split, should be materially smaller than 1065 lines

## Task: Update packaging and install for a multi-file skill resource

The wheel packaging (`skill/*.md` glob), `resolve_skill_md`, and `fab-test skill --install/--show/--uninstall` all assume one file. Extend them to a directory of files.

**Requirements**:
- Given the packaged skill resource, should ship the main `SKILL.md` and every `references/*.md` file in the wheel (`skill/**/*.md` package-data, `check_wheel_contents.py` updated)
- Given `resolve_skill_dir` (renamed from `resolve_skill_md` -- it now resolves a directory), should resolve the whole component set (repo override first, packaged fallback), not a single file
- Given `fab-test skill --install <harness>`, should install the full component set for that harness, reporting per-file created/updated/unchanged/differs status
- Given `fab-test skill` (bare, print), should print the main file's content; `--format json` includes the reference file paths alongside `content`
- Given `fab-test skill --uninstall`, should remove only the files this command's own marker identifies as its, across the whole component set
- Given `tests/test_skill_resource.py`, should still guard that the packaged copy matches the authored source, now across every component file

## Task: Guard the skill format in vision.md

**Requirements**:
- Given vision.md, should state that this project's own skill files (starting with fab-test's) must follow `aidd-sudolang-syntax` for their behavioral/contract sections, and that this is checked by a test, not review discipline alone
- Given a CI run, should fail if fab-test's main `SKILL.md` loses its required SudoLang constructs (an `Interfaces` or `Constraints` block) — the guard that makes "never fails again" durable rather than a one-time fix
- Given vision.md's Definition of Done, should state the closing sequence explicitly as an ordered list: ruff check → documentation → update the skill file → confirm it is part of the packaged fab-test skill
