# fab-test Skill Distribution Epic

**Status**: 📋 PLANNED
**Goal**: `fab-test` ships its own versioned skill and installs it to whatever harness is running, so the skill file can never drift from the installed CLI version.

## Overview

Today `.github/skills/fab-test/SKILL.md` is a hand-maintained file synced to the CLI by the `document` skill's discipline alone — nothing stops a consumer repo from running fab-test 1.2 against a SKILL.md written for 1.0. Ship the skill content inside the wheel (same layering fab-test already uses for `.fab-test/metadata/`), and add a subcommand that prints or installs it, version-matched, into whichever agent harness (Claude Code, Copilot, Cursor, Codex, Windsurf, ...) the consumer repo is using — following the `rtk init` precedent of harness-detection, idempotent writes, `--dry-run`, `--show`, `--uninstall`.

### Prior art (researched 2026-08-29)

- **`rtk init`** is the closest reference model: `--agent <claude|cursor|windsurf|cline|kilocode|antigravity|pi|hermes>`, plus `--gemini`/`--codex`/`--copilot`/`--opencode`, `--show`, `--dry-run`, `--uninstall`, `--auto-patch`/`--no-patch`. Its release notes frame this explicitly as anti-drift — same motivation here.
- **Anthropic's Agent Skills (SKILL.md)** is now an open spec (agentskills.io, 26+ adopters), but it standardizes the *format* only; skills are distributed via a separate plugin/marketplace flow (`claude-plugins-official`), decoupled from any single CLI's own release cadence.
- **MCP** is orthogonal — tool/function-calling, not instruction docs, even under the "skills over MCP" pattern.
- **Microsoft APM (Agent Package Manager)** is the mirror image: an *external* registry (`apm.yml`/git repos) that pulls skills into harnesses, not a CLI emitting its own bundled skill.
- **`@mongez/agent-kit`, `@netresearch/agent-skill-coordinator`, `agent-install`** are architecturally closest (postinstall hook fans a skill out to multiple harness config formats), but they distribute *third-party* skills discovered in `node_modules`, not a tool's own instructions pinned to its own version.
- No major vendor or OSS project ties skill content to the CLI's own binary version as a first-class anti-drift guarantee — this is a genuine gap, not a reinvention.

`fab-test` already has two of the load-bearing pieces: the metadata layering (`.fab-test/metadata/` → `.github/metadata/` → wheel-packaged copy, see [SKILL.md](../.github/skills/fab-test/SKILL.md)) and `fab-test init`'s "never overwrite, `--dry-run` reports, idempotent" pattern in [fab_test_admin.py:300](../src/fabric_ci_cd_dataops/scripts/fab_test_admin.py#L300).

---

## Task: Package the skill content with the wheel

Move `SKILL.md` under a packaged resource path (mirroring the existing `.fab-test/metadata/` → `.github/metadata/` → wheel-fallback layering) so it ships with every install and always matches `__version__`.

**Requirements**:
- Given a `pip install`d fab-test, should have a packaged SKILL.md resolvable without network access
- Given a repo with a local override skill file, should prefer the local copy over the packaged one (same override precedent as metadata)
- Given the packaged SKILL.md, should have its `description` frontmatter reflect `_FAB_TEST_VERSION` so drift is visible even if someone hand-copies it

## Task: Add `fab-test skill` command (print/explain)

Add a `_skill` handler alongside `_init`/`_doctor`/`_explain_analyzer` in `fab_test_admin.py`. Bare `fab-test skill` prints the resolved SKILL.md to stdout; `--format json` wraps it with version metadata for programmatic consumption.

**Requirements**:
- Given `fab-test skill`, should print the packaged (or overridden) SKILL.md content to stdout
- Given `fab-test skill --format json`, should emit `{version, source_path, content}`
- Given no fab-test installed correctly (e.g. resource missing), should fail with a clear exit code, not a stack trace

## Task: Add harness install targets (`--install <harness>`)

Reuse the `_init` idempotency pattern: detect existing harness config, never clobber a differing local copy without `--dry-run` warning first, support `--show` and `--uninstall`.

**Requirements**:
- Given `fab-test skill --install claude`, should write/update `.github/skills/fab-test/SKILL.md` (or `.claude/skills/...` per current Claude Code convention) and report created/updated/unchanged
- Given `fab-test skill --install copilot`, should write the Copilot custom-instructions equivalent
- Given `fab-test skill --install --dry-run`, should report what would change without writing
- Given `fab-test skill --show`, should report install state per harness (found/missing/version-mismatched), mirroring `rtk init --show`
- Given `fab-test skill --uninstall --install claude`, should remove only the artifacts this command created
- Given an unrecognized `--install` value, should list valid harness names and exit non-zero

## Run `ruff check` before documentation

Per [vision.md](../vision.md#definition-of-done--documentation), run `ruff check` over `src/` and fix anything it flags before the documentation-facing work in the task below.

---

## Task: Retire the manual sync path

Update the `document` skill and `aidd.agent.md`'s Definition of Done so "skill in sync" means "packaged copy in sync," not "repo copy in sync." Keep `.github/skills/fab-test/SKILL.md` as the checked-in *source* the packaging step in Task 1 pulls from, so authoring still happens in markdown.

**Requirements**:
- Given a CI run, should fail if the packaged SKILL.md resource is stale relative to `.github/skills/fab-test/SKILL.md` (prevents exactly the drift this epic exists to close)
- Given `document` skill's workflow, should reference `fab-test skill --show` instead of manual diffing
