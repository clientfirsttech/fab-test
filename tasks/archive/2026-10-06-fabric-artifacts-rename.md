# Fabric Artifacts Rename Epic

**Status**: ✅ COMPLETED (2026-10-06)
**Goal**: Replace this repository's `.fabric/artifacts` fixture convention with `fabric-artifacts`, since a dot-prefixed `.fabric` directory is rejected by Fabric Git Integration.

## Overview

A workspace connected via Fabric Git Integration cannot sync into a `.fabric/` folder, so a repository that keeps its deployed-artifact fixtures there — as this one does, and as the docs and skill tell every reader to — cannot actually be git-connected to the workspace it tests against. The fix is a rename, not a redesign: `fab-test`'s own discovery already defaults to the working directory (Discover From CWD), so `.fabric/artifacts` was never a baked-in default, only this repository's convention for where its sample `.pbip`/`.rdl` fixtures live — in code comments, one completion script, one change-detector, test fixtures, and every doc/skill example. Each needs the literal path updated; one (`detect_changes.py`) needs more, because the new name drops a path segment and its grouping logic keys off a fixed index into the split path. Historical record — CHANGELOG entries, archived epics, `plan/story-map/*.yaml` — stays untouched; it describes what was true at the time.

---

## Rename the fixture directory and its retired config

`git mv .fabric/artifacts fabric-artifacts` and remove the now-empty `.fabric/`; update the one config file that still names the old path as a default.

**Requirements**:
- Given the current `.fabric/artifacts/` tree, should become `fabric-artifacts/` at the repository root with every fixture file intact, and `.fabric/` should no longer exist once it is empty
- Given `.fab-test/metadata/environments.yml`'s `defaults.repository_directory`, should read `"fabric-artifacts"`

---

## Fix path-dependent production code

Three places read the literal path in running code, not just comments; one of them assumes the path has two segments before the artifact name.

**Requirements**:
- Given `detect_changes.py`'s `group_changes_by_artifact`, should key off a single-segment `fabric-artifacts` root instead of the two-segment `.fabric/artifacts` — the function's `parts[:3]`/`parts[2]` indexing must shift by one, not just have its string literal swapped, or every changed-file grouping silently reports the wrong artifact name
- Given `fab_test_parser.py`'s bash and zsh `--print-completion` scripts, should look up artifact stems under `fabric-artifacts` at completion time
- Given `fab_test_admin.py`'s `init`-scaffolded example config comment and `src/fab_test/schemas/fab-test.schema.json`'s `artifact_dir` description, should name `fabric-artifacts` so a new user is never pointed at a path Fabric Git Integration rejects

---

## Update tests that depend on the literal path

Some tests read real fixtures from disk at the old path; others assert the old literal string. Both break silently rather than loudly — an empty glob reads as "nothing to test", not a failure.

**Requirements**:
- Given `tests/test_rdl_fixture_rules.py`'s `_FIXTURES` glob and `tests/test_conftest_zero_artifact.py`'s `skipif` guard and artifact lookup, should read from `fabric-artifacts/` — and should still skip cleanly, not pass vacuously, if the directory were ever absent
- Given `tests/test_detect_changes.py`'s grouping assertions, should exercise the corrected single-segment logic, including a case shaped to catch the `parts[:3]`/`parts[2]` class of bug this rename exposed
- Given `tests/test_cwd_default.py`'s backward-compatibility test (`test_the_existing_fabric_layout_is_still_found`) and `tests/test_fab_test_config.py`'s completion-script test, should assert against `fabric-artifacts` content, not the old path
- Given `tests/test_environments_config.py` and `tests/test_environments_yaml.py`'s default-config fixtures, should use `"fabric-artifacts"` as the example `repository_directory`

---

## Update living documentation for all three callers

A global find-and-replace is not enough where the surrounding sentence explains *why* the old path doesn't work — that explanation needs to land, not just the new string.

**Requirements**:
- Given README.md, docs/QUICK-VALIDATION.md, docs/QUICKSTART-LOCAL.md, docs/RDL-RULES.md, docs/RELEASE.md, and `tools/generate_rdl_rules_doc.py`'s generated text, should name `fabric-artifacts` and state the Fabric Git Integration conflict as the reason for the rename
- Given CHANGELOG.md entries, `plan.md`'s completed-epic summaries, `tasks/archive/**`, and `plan/story-map/*.yaml`, should stay untouched since they are historical record, not living reference

---

## Update the fab-test skill, authored and packaged copies together

**Requirements**:
- Given `.github/skills/fab-test/references/configuration.md` and `flags.md`, should be edited first and mirrored byte-for-byte into `src/fab_test/skill/references/`, per `tests/test_skill_resource.py`'s parity guard
- Given `src/fab_test/skill/SKILL.md`'s packaged copy and the `fab-inspector`/`pql-test` skills' worked examples, should show `fabric-artifacts` paths

---

## Version bump and changelog

**Requirements**:
- Given vision.md's versioning rule that anything tracked as an epic bumps MINOR, should bump `__version__` (resetting PATCH to 0) and record the rename and its Fabric Git Integration reason in CHANGELOG.md

---

## Quality gates

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
