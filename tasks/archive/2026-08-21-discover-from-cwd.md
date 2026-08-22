# Discover From CWD Epic

**Status**: ✅ COMPLETED (2026-08-21)
**Goal**: `fab-test` finds your artifacts where you ran it, by folder suffix, without a `.fabric/artifacts` layout or a `.pbip` file.

## Overview

A developer with Fabric artifacts in a repository runs `fab-test bpa` and gets exit 2: *"--artifact-dir does not exist: .../.fabric/artifacts"*. That path is this reference repository's CI layout, not anything Power BI Desktop or Fabric produces, so the first command a new user types fails against a directory they have never heard of. Meanwhile `fab-test local` starts at the working directory and finds things — so the tool answers "where are my artifacts?" two different ways depending on which subcommand you picked. That is the opposite of the one-contract promise in [vision.md](../vision.md), and it undercuts **Local first** directly.

Underneath the default sits a wrong assumption about what identifies an artifact. Discovery today is a *top-level* glob of `--artifact-dir`, plus folders paired with a `.pbip` found recursively. So `deployed/Sales.SemanticModel` with no `.pbip` is invisible, which is exactly the shape of artifacts committed for CI. The real signal is the folder suffix, and this repository already declares it: [`.github/metadata/artifact-map.json`](../.github/metadata/artifact-map.json) maps nine suffixes to Fabric types. `fab-test` never reads it, and instead carries three hardcoded copies of the same knowledge that each know two types.

**Scope decision (2026-08-21, user)**: every subcommand defaults to the working directory and discovers recursively — not just `bpa`. `artifact-map.json` becomes the source of artifact types, with a packaged fallback so an install from PyPI works outside this repository's layout.

**An exclusion list is load-bearing, not a polish item.** Measured on this repository: today's discovery finds 3 artifacts; a naive recursive scan of the working directory finds **8**, of which **5 are duplicates inside `.claude/worktrees/`**. Without exclusions this feature would report every artifact three times on the author's own machine the day it shipped. [`_pbip_discovery`](../src/fabric_ci_cd_dataops/scripts/_pbip_discovery.py) already skips nested git checkouts for precisely this reason; that guard becomes shared rather than `.pbip`-specific.

**Blast radius.** Discovery has four callers — `_run_analyzer`, `list`, `explain`, and `build_all_summary_rows` — plus `local`, which has its own path. Per the constraint added to [vision.md](../vision.md) after five defects of exactly this kind, every one is exercised through the real CLI before a task is called done.

---

## 1. Read `artifact-map.json`, With a Packaged Fallback

Make the repository's own declaration the source of truth, without breaking an install that has no repository.

**Requirements**:
- Given `.github/metadata/artifact-map.json` exists, then its suffix-to-type mapping is what `fab-test` uses.
- Given it is absent — an install from PyPI, or a directory that is not this repository — then a copy packaged with the distribution is used and the run proceeds normally.
- Given the packaged copy, then it ships via `[tool.setuptools.package-data]` alongside `schemas/*.json`, which is the existing precedent for shipped metadata.
- Given a malformed or unreadable map, then the packaged fallback is used and a warning names the file — a broken file must not be worse than a missing one.
- Given the two copies, then a test asserts they agree, so the shipped fallback cannot drift from the repository's version.

**Files**: new `_artifact_types.py`, `pyproject.toml`, packaged `metadata/artifact-map.json`
**Tests**: `pytest tests/test_artifact_types.py`

---

## 2. Collapse the Three Hardcoded Type Lists

The same knowledge lives in four places and they disagree: `artifact-map.json` knows nine types, the other three know two.

| Location | Today |
|----------|-------|
| `.github/metadata/artifact-map.json` | 9 types |
| `_target.KNOWN_ARTIFACT_TYPES` | 2 |
| `fab_test_registry._SUFFIX_TO_ANALYZERS` | 2 |
| `ANALYZER_REGISTRY` globs | 2 |

**Requirements**:
- Given `_target.KNOWN_ARTIFACT_TYPES`, then it is derived from the map rather than declared, so `Sales.Notebook` parses as a Notebook instead of failing as an unknown type.
- Given `_SUFFIX_TO_ANALYZERS`, then it maps a suffix to the analyzers that handle it and is not also the definition of which suffixes exist.
- Given a search for the list of Fabric artifact types, then exactly one definition is found outside the map itself.
- Given the existing drift test asserting `KNOWN_ARTIFACT_TYPES` matches the analyzer globs, then it is replaced: that assertion enforced the wrong invariant, since the set of types and the set of types an analyzer handles are different questions.

**Files**: `_target.py`, `fab_test_registry.py`, `tests/test_target.py`
**Tests**: `pytest -m fab_test tests/test_target.py`

---

## 3. Discover By Suffix, Recursively, With Exclusions

**Requirements**:
- Given a folder whose name ends in a known suffix, then it is discovered at any depth, whether or not a `.pbip` sits beside it.
- Given a `.pbip` pairing, then it still enriches the result — the `[from X.pbip]` note and the Desktop binding — but is no longer what makes an artifact visible.
- Given a nested git checkout (a worktree, a vendored clone), then everything inside it is skipped, reusing the guard `_pbip_discovery` already has.
- Given `.venv`, `node_modules`, `__pycache__`, `dist`, `build`, `.git`, and the configured `--output-dir`, then they are not scanned.
- Given this repository, then discovery finds the same 3 artifacts it finds today and not the 8 a naive scan returns.
- Given a large repository, then the scan time is measured and recorded here; if it is not comfortably under a second, an exclusion is missing. **Measured: 216 ms over this repository, returning the same 3 artifacts discovery found before the change.**
- Given an artifact discovered twice by two routes, then it appears once.

**Files**: `fab_test_registry.py`, `_pbip_discovery.py`
**Tests**: `pytest -m fab_test tests/test_target_discovery.py`

---

## 4. Default Every Subcommand to the Working Directory

**Requirements**:
- Given any analyzer subcommand with no `--artifact-dir`, then it discovers from the working directory.
- Given `all` and `local`, then they behave identically to a single analyzer in where they look — one answer to "where are my artifacts?", not two.
- Given an existing `.fabric/artifacts` layout, then every artifact found today is still found, because that directory sits under the working directory. This is the backward-compatibility line and it is asserted, not assumed.
- Given a CI job passing `--artifact-dir` explicitly, then nothing about its behavior changes.
- Given `--artifact-dir` pointing at a directory that does not exist, then the run still exits `2` — an explicit wrong path is an error, whereas an absent default is not.
- Given the `artifact_dir` config key, then it still overrides the default through the existing precedence chain.

**Files**: `fab_test.py`
**Tests**: `pytest -m fab_test`, then `bpa`, `all`, `local`, `list`, and `explain` each run from a directory with no `.fabric/`

---

## 5. Refuse an Unhandled Type Accurately

Accepting nine types means a caller can name one no analyzer reads. The refusal has to say so properly.

**Requirements**:
- Given `fab-test bpa Sales.Notebook`, then the message says `bpa` reads SemanticModel artifacts and that `Sales.Notebook` is a Notebook — not "unknown artifact type".
- Given a type no configured analyzer handles at all, then the message says that plainly rather than naming a flag that would not help.
- Given `fab-test list`, then each row shows which suffixes its analyzer handles, so the answer is discoverable before the error.
- Given the exit code, then it stays `2` — this is still a caller error.

**Files**: `fab_test_registry.py`, `fab_test.py`
**Tests**: `pytest -m fab_test tests/test_target_scopes.py`

---

## 6. Document for All Three Callers

**Requirements**:
- Given the README's "Assumed project format", then it no longer implies `.fabric/artifacts` is required, and states that discovery starts at the working directory.
- Given the `fab-test` skill, then it documents suffix-based discovery, the exclusion list, and `artifact-map.json` as the type source with its packaged fallback.
- Given a pipeline author, then the guidance says whether to keep passing `--artifact-dir` explicitly in CI — and recommends it, because an explicit root is a better contract for a build than a default that follows the working directory.
- Given a reader with an existing `.fabric/artifacts` repository, then the docs say plainly that nothing they do needs to change.

**Files**: `README.md`, `docs/QUICK-VALIDATION.md`, `.github/skills/fab-test/SKILL.md`
**Tests**: full suite with coverage

---

## Deferred — Analyzers for the Other Seven Types

Recognising `Notebook`, `Dataflow`, `Lakehouse`, and the rest as valid targets does not make `fab-test` able to analyze them; no analyzer reads those formats. Task 5 makes the refusal honest. Adding real analyzers is a separate question, and one that starts with whether an upstream tool exists to wrap — per the facade principle, not by writing one here.

## Deferred — Walking Up for a Repository Root

Running from a subdirectory finds only that subtree. Walking up to a `.git` boundary would be friendlier and is what most tools do, but it is a second behavior to explain and this epic already changes where every subcommand looks. Revisit once the cwd default has been used in anger.

## Note — This Changes What a Bare Command Scans

Unlike the last three epics, this one is not behavior-preserving: that is its point. The safeguard is the backward-compatibility requirement in task 4 — every artifact found today is still found — plus running all five discovery callers through the real CLI before each task is closed.

---

## Outcome (2026-08-21)

| Measure | Before | After |
|---------|--------|-------|
| Artifacts found in this repository | 3 | 3 |
| Artifacts a naive recursive scan finds | 8 | — (5 pruned as worktree copies) |
| Scan time over this repository | — | 216 ms |
| Places that know the Fabric type list | 4, disagreeing | 1 (`artifact-map.json`) |
| Types accepted as targets | 2 | 9 |
| `deployed/Sales.SemanticModel` with no `.pbip` | invisible | found |
| Suite | 992 passed | 1049 passed, 3 skipped |
| Coverage | 82.27% | 83% |

**One defect found during execution, by the suite rather than the CLI.** Passing
`output_dir` into `build_all_summary_rows`' discovery introduced a local
binding that shadowed the function's existing `output_dir` *parameter*, so the
aggregate summary read envelopes from `None`. Two tests caught it. Worth
recording because the blast-radius constraint is aimed at the opposite
failure — code the tests do not reach — and this was the case where they did.

**What the real-CLI passes proved that the suite could not.** The five
discovery callers were run after each task and produced byte-identical output
for this repository: `list` counts, `explain` paths, `bpa`/`all`/`local`
dry-run sets. The new capability was proved the same way, from a directory
that is not this repository and holds no `.fabric/`.
