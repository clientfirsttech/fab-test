# RDL Quiet Output Epic

**Status**: 📋 PLANNED
**Goal**: `fab-test rdl` joins the verbosity ladder `main` already defines for every other analyzer: `-q/--quiet` prints one line per artifact, `-v` and `-vv` add detail, and the default states each result once.

## Overview

An AI agent running `fab-test rdl` in an edit loop should pay tens of tokens to learn that a report passed, not a banner, a count and a table. `main` shipped that for the existing analyzers in the Terse CLI Output epic ([archived on main](https://github.com/kerski/fab-test/blob/main/tasks/archive/2026-09-29-terse-cli-output.md)): `-q` prints `<analyzer> <status> e=<errors> w=<warnings> <where>`, and the skill and `operations.md#output-verbosity` document the ladder. This branch forked before that merged (it is 75 commits behind `main`), so `rdl` only has `--verbose` and its own `ANALYZER_VERBOSITY` read, and the verbose output added in the RDL Finding Clarity epic copies the older PBIR Inspector shape that `main` has since trimmed.

---

## Bring in the verbosity ladder

**Requirements**:
- Given this branch, should merge or rebase `main` first, so `-q`/`-v`/`-vv`, the `verbosity:` config key and `narrate(quiet=...)` exist before `rdl` is wired to them
- Given the merge, should re-run the whole suite and compare against `main`'s results before touching `rdl`, since the module budgets and `_config.py` both changed on `main`

---

## Quiet flag for `rdl`

**Requirements**:
- Given `fab-test rdl -q`, should pass `ANALYZER_VERBOSITY=summary` to the wrapper, including under `all` and `local`
- Given `-q` with `-v`, should exit `2` naming the conflict
- Given `ANALYZER_VERBOSITY` set and no flag, or `verbosity:` in `fab-test.yml`, should honor them with the same flag > env > file > default precedence as the other analyzers
- Given the wrapper's own `--verbose`, should keep working and map to the same level as `-v`; `-vv` should be accepted

---

## The `-q` line for `rdl`

**Requirements**:
- Given `-q`, should print exactly one line per artifact: `rdl <status> e=<errors> w=<warnings> <where>`, with the analyzer named `rdl` and `<where>` the envelope path relative to the working directory
- Given a passing run under `-q`, should print nothing else
- Given a parse failure or any error the findings cannot explain, should still print the remediation or the analyzer's message under `-q`
- Given `-q --format json`, should leave stdout byte-identical to the same run without `-q` and print nothing to stderr for a passing artifact
- Given CI is detected, should still pass the `::error::` and `::warning::` annotations through verbatim
- Given `all` or `local`, should print `rdl`'s own line as it finishes, with the aggregate table left out, as for the other analyzers

---

## State each result once

The banner and closing lines added in the RDL Finding Clarity epic print the Envelope path twice and the Rules path at the default level, as PBIR Inspector did before `main` changed it.

**Requirements**:
- Given default verbosity, should print the envelope and native paths once per artifact and leave out the Rules path
- Given `-v`, should add the Rules path and the per-finding table
- Given `-vv`, should add the wrapper's resolved inputs and anything else the other analyzers print at debug
- Given the findings table helper in `_table_style.py`, should stay shared with PBIR Inspector, and follow whatever `main` did to that file

---

## Documentation

**Requirements**:
- Given the fab-test skill (authored and packaged copies), README, QUICK-VALIDATION and `docs/RDL-RULES.md`, should document `rdl -q` and the `rdl` line next to the other analyzers, and keep the two skill copies identical
- Given `tests/test_rdl_documentation.py`, should assert the quiet flag is documented for all three callers
