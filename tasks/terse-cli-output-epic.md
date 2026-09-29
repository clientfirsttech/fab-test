# Terse CLI Output Epic

**Status**: 🔄 IN-PROGRESS (3/7)
**Goal**: One line per artifact under `-q`, and each result stated once by default

## Overview

An AI agent in an edit loop pays ~700 tokens to learn that `fab-test bpa` passed on two models, and ~2,600 for `local`, because every result is printed three times (analyzer banner, parent progress line, summary row) alongside absolute Rules/Tool paths that never change and `::notice::` lines meant for CI. The only terse mode today is an undocumented `ANALYZER_VERBOSITY=summary` that no flag reaches, and `narrate(quiet=...)` is wired to nothing. This epic adds `-q` as one more rung on the existing verbosity ladder, rather than a new subsystem, and trims the default output for every caller without touching the envelope or `--format json` stdout. Journey: [plan/story-map/terse-cli-output.yaml](../plan/story-map/terse-cli-output.yaml).

---

## Quiet Flag

Add `-q/--quiet` and map it to `ANALYZER_VERBOSITY=summary` for the analyzer subprocess.

**Requirements**:
- Given `-q`, should pass `ANALYZER_VERBOSITY=summary` to every analyzer subprocess, including under `all` and `local`
- Given `-q` with `-v`, should exit `2` naming the conflict
- Given `ANALYZER_VERBOSITY` already set and no flag, should keep honoring it unchanged

---

## Quiet Parent Narration

Under `-q`, replace the parent's progress lines and summary block with one line per artifact.

**Requirements**:
- Given `-q`, should print exactly one line per artifact: `<analyzer> <status> e=<errors> w=<warnings> <where>`, where `<where>` is the envelope path relative to the working directory (or the artifact name when no envelope was written)
- Given `-q` with `--format json`, should leave stdout byte-identical and print nothing to stderr for passing artifacts
- Given a preflight failure, timeout, or exit `126`/`127` under `-q`, should still print the remediation line
- Given `-q` in CI, should still emit `::error::` annotations so the pipeline surfaces failures

---

## Verbosity Config Key

Let a repository pin terse output for its agents with `verbosity` in `fab-test.yml`.

**Requirements**:
- Given `verbosity: summary` in `fab-test.yml`, should behave as `-q`, with flag > `ANALYZER_VERBOSITY` > file > default precedence
- Given an unknown `verbosity` value, should fail schema validation naming the allowed values
- Given `config --show`, should report the effective verbosity and its origin

---

## State Each Result Once

Remove the duplicate lines default output prints for every artifact.

**Requirements**:
- Given pbir, pql-test, or pqlint, should print the envelope and native paths once per artifact, not twice
- Given default verbosity, should print Rules and Tool paths only at `-v`, since `doctor` and the envelope already carry them
- Given the standalone `tabular-editor-bpa` console script, should still print its own result line
- Given every artifact fails the same prerequisite check (e.g. playwright with no service principal, 8 artifacts), should print that remediation once, not once per artifact

---

## CI Notices Only In CI

Keep tool-bootstrap `::notice::` workflow commands out of local runs.

**Requirements**:
- Given neither `GITHUB_ACTIONS` nor `CI` is set, should print bootstrap download/resolve messages without the `::notice::` prefix
- Given `GITHUB_ACTIONS` is set, should emit `::notice::` exactly as today

---

## Teach Agents Terse Output

Update the skills an agent reads so it reaches for `-q` by default instead of discovering it.

**Requirements**:
- Given `.github/skills/fab-test/SKILL.md`, should state in SudoLang that an agent prefers `-q` for pass/fail and `--format json 2>/dev/null` when it needs fields, and define `-q`'s one-line shape so an agent can parse it without the envelope
- Given `references/operations.md`, `flags.md`, and `configuration.md`, should document the `summary` level, `-q`, the `-q`/`-v` conflict, and the `verbosity` key
- Given `aidd-analyzer-contract`, should require every new analyzer to honor `ANALYZER_VERBOSITY=summary`, so a future wrapper doesn't regress `-q`
- Given the packaged copy under `src/fab_test/skill/`, should match the authored source and re-stamp the frontmatter version, guarded by `tests/test_skill_resource.py`
- Given `fab-test skill --show`, should confirm an installed harness copy picks up the change

---

## Document Terse Output

Ship `-q` to the human and pipeline callers and close the epic per vision.md's Definition of Done.

**Requirements**:
- Given README and QUICK-VALIDATION, should show `-q` and the `verbosity` key with a before/after example
- Given the CI docs, should include a copy-pasteable workflow step using `-q`
- Given the `src/` changes, should bump MINOR per vision.md's Versioning
- Given the epic is done, should have exercised `bpa`, `pbir`, `a11y`, `pql-test`, `all`, and `local` through the installed console script in text, `-q`, and `--format json` modes, and recorded the measured char counts against the discovery baseline
