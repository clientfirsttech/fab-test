# Empty Discovery Diagnostics Epic

**Status**: ✅ COMPLETED (2026-08-23)
**Goal**: When discovery finds nothing because it deliberately pruned git checkouts, say so and name the fix — instead of implying the artifacts are not there.

## Overview

A developer runs `fab-test pbir` one directory above their repository and is told
*"no `*.Report` artifacts or `.pbip` projects found under `C:\Users\jkers\Git`"*.
The artifacts **are** there — three of them, in `Git\fab-test` — and discovery
found none of them on purpose. `C:\Users\jkers\Git` holds eight sibling git
repositories, and [`_scan._is_nested_checkout`](../src/fabric_ci_cd_dataops/scripts/_scan.py#L50)
prunes every directory below the root that carries a `.git` entry. So the message
reports absence where the truth is refusal, and it names no way forward. That is
a direct miss on principle 4 of [vision.md](../vision.md) — *"every failure names
the flag, environment variable, or config key that resolves it"* — and it costs
the AI caller most, since a parseable `{"artifacts": []}` is indistinguishable
from a genuinely empty repository.

**This is not the recursion bug that was fixed.** [Discover From CWD](archive/2026-08-21-discover-from-cwd.md)
made discovery recursive and added the exclusion list, and that work is intact:
from inside the repo, discovery still finds exactly 3 artifacts in ~100 ms. The
nested-checkout guard it introduced is doing what it was written to do — suppress
the five worktree copies under `.claude/worktrees/`. What it was never asked is
what to do when the root is *not itself a repository*, and there is no outer repo
for a child checkout to be a copy of. That same epic deferred "walking up to a
repository root", which is the other half of this same gap.

**Scope decision (2026-08-22, user)**: **keep the pruning, explain it.** Discovery
does not start descending into sibling repositories. The defect being fixed is the
silence, not the scan. This keeps output tight for the common in-repo case and
avoids a `foo.worktrees/` sibling flooding results from an unrelated project.

## Reproduction

```
PS C:\Users\jkers\Git> fab-test pbir
  ⚠ fab-test pbir: no *.Report artifacts or .pbip projects found under C:\Users\jkers\Git
```

**An artifact is a folder whose name ends in a Fabric type suffix** — the nine in
[`artifact-map.json`](../.github/metadata/artifact-map.json): `.SemanticModel`,
`.Report`, `.Agent`, `.Notebook`, `.Dataflow`, `.Eventhouse`, `.Warehouse`,
`.Lakehouse`, `.Environment`. A `.pbip` file only *enriches* a result with its
Desktop binding; it has not decided whether an artifact exists since
[Discover From CWD](archive/2026-08-21-discover-from-cwd.md). Measuring against
all nine suffixes over `C:\Users\jkers\Git`, with `_is_nested_checkout` stubbed
out to show what the guard is suppressing:

| Scan | Artifacts | Time |
|------|-----------|------|
| Today (prune on) | **0** | 0.08 s |
| Prune lifted | **27** — `.Report` 12, `.SemanticModel` 9, `.Environment` 3, `.Notebook` 2, `.Eventhouse` 1 | 0.91 s |

**The guard is earning its keep.** Of those 27, **12 are copies**: eight under
`fab-test\.claude\worktrees\{metadata-layers,pbir-images,python-lint}`, two under
`fabric-agent-ci-cd.worktrees\copilot-worktree-*`, and two more duplicated in
`fabric-ci-cd-dataops\pypi-package\`. Lifting the prune would report
`SampleModel-PQLAssert.Report` four times. This is the measured case for the scope
decision below — the pruning is right, and only its silence is wrong.

## Blast Radius

Empty discovery surfaces through more than the one command that reported it.
Per the constraint in [vision.md](../vision.md), each is exercised through the
installed console script before its task is done.

| Entry point | Today, from `C:\Users\jkers\Git` |
|-------------|----------------------------------|
| `fab-test pbir` | `⚠ ... no *.Report artifacts ... found under` |
| `fab-test pbir --dry-run` | same message, no plan |
| `fab-test pbir --format json` | `{"analyzer": "pbir", "artifacts": []}` |
| `fab-test list` | every analyzer shows `Matched: 0`, unexplained |
| `fab-test local` | `⚠ fab-test pql_test: no *.SemanticModel artifacts ...` |

---

## 1. Surface What the Scan Pruned

`iter_artifact_dirs` prunes nested checkouts silently, so no caller can tell an
empty repository from a pruned one. Counting them in a second pass would walk
twice and duplicate the prune rules — the drift this epic exists to close.

**Requirements**:
- Given a scan of a root, then the pruned nested checkouts are returned alongside the artifacts, from the **same single walk**.
- Given the existing `find_artifact_dirs(root, suffixes)` callers, then their signature and return value are unchanged — the new detail arrives through a separate entry point, not a breaking change to the one two modules already call.
- Given a root that is itself a repository, then its own `.git` is still not counted as a pruned checkout.
- Given `.venv`, `node_modules`, and the rest of `EXCLUDED_DIR_NAMES`, then they are pruned as today and are **not** reported as checkouts — the caller cannot act on those and listing them is noise.
- Given a scan that finds artifacts, then the pruned list is still populated, so `list` and `--dry-run` can use it too.

**Files**: `src/fabric_ci_cd_dataops/scripts/_scan.py`
**Tests**: `pytest -m fab_test tests/test_scan.py`

---

## 2. Make the Empty Message Explain Itself

The message misstates the search on two counts. It says *"no `*.Report` artifacts
**or `.pbip` projects**"*, which offers a `.pbip` as an alternative route to being
found — it stopped being one when discovery went suffix-based, and a reader who
believes it goes looking for the wrong file. And it reports absence when the truth
is refusal.

**Requirements**:
- Given an empty result, then the message names the **folder suffix** as the thing that was searched for and drops the `.pbip` clause — `.pbip` pairing enriches a result and has not made one visible since Discover From CWD.
- Given discovery returned nothing **and** one or more git checkouts were pruned, then the message says how many were skipped, that a scan does not descend into a nested repository, and names both remedies: `cd` into one, or pass `--artifact-dir <path>`.
- Given at least one pruned checkout, then up to three are named by path, so the remediation is a command the caller can paste rather than a hint they must resolve.
- Given discovery returned nothing and **nothing** was pruned, then the message gains no checkout note — the in-repo case must not get noisier to serve the out-of-repo one, and its only change is the `.pbip` correction above.
- Given a path target (`--artifact <path>`), then the existing "no artifact at X" message still wins and gains no checkout note; the caller named a location and did not ask what a scan found.
- Given `--format json`, then the payload carries `skipped_checkouts` and a `remediation` string beside `artifacts`, and stdout stays pure JSON with narration on stderr.
- Given `--quiet`, then the note honours it exactly as the message it extends does.

Target shape:

```
PS C:\Users\jkers\Git> fab-test pbir
  ⚠ fab-test pbir: no *.Report artifacts found under C:\Users\jkers\Git
    8 git checkouts below this root were skipped — a scan does not descend
    into a nested repository. cd into one, or name it directly:
      --artifact-dir C:\Users\jkers\Git\fab-test
```

**Files**: `src/fabric_ci_cd_dataops/scripts/fab_test.py` (`_report_no_artifacts`)
**Tests**: `pytest -m fab_test tests/test_fab_test_cli.py -k no_artifacts`
**Verify**: `fab-test pbir`, `fab-test pbir --format json`, `fab-test pbir --quiet`, and `fab-test local`, each run from `C:\Users\jkers\Git` through the installed console script.

---

## 3. Explain a Table of Zeroes in `fab-test list`

`list` is the discovery command — the one an agent calls to learn what can run —
and from a non-repo root it reports `Matched: 0` for every analyzer with no
indication that anything was skipped.

**Requirements**:
- Given every analyzer matched 0 artifacts and checkouts were pruned, then a note below the table carries the same count and remedy as task 2.
- Given `--format json`, then the same `skipped_checkouts` key appears at the top level of the `list` payload.
- Given at least one analyzer matched an artifact, then no note appears — a partial result is not a problem to explain.
- Given `list` in this repository, then its output is unchanged from today.

**Files**: `src/fabric_ci_cd_dataops/scripts/fab_test.py` (`_list_analyzers`, `_print_list`)
**Tests**: `pytest -m fab_test tests/test_fab_test_cli.py -k list`
**Verify**: `fab-test list` and `fab-test list --format json` from both roots.

---

## 4. Document It for All Three Callers

Per principle 7, the epic is not done until the agent, the human, and the
pipeline each have it.

**Requirements**:
- Given the `fab-test` skill, then it records that discovery does not descend into nested git checkouts and what the empty result's `skipped_checkouts` key means.
- Given any doc that describes discovery, then it states the rule as **a folder whose name ends in a Fabric type suffix**, and does not imply a `.pbip` is needed — the same correction task 2 makes to the message.
- Given README's discovery section, then it states the checkout rule in the human's words, with the `--artifact-dir` remedy.
- Given a pipeline that checks out submodules or vendored repos, then the YAML snippet shows the `--artifact-dir` it needs.
- Given the `document` command, then all three are updated in one pass so they cannot drift.

**Files**: `.github/skills/fab-test/SKILL.md`, `README.md`, `docs/`
**Command**: `document`

---

## Verification Status (2026-08-23)

The two loose ends from the 2026-08-22 concurrent-session round trip are both
closed:

1. **`tests/test_fab_test.py` collects cleanly.** The `_redact_pii` import
   that blocked collection is gone — it was deleted deliberately (the file
   now carries a comment recording that removal), not a stale import left by
   the other session's TDD work. All eight empty-discovery tests in the file
   run: `pytest tests/test_fab_test.py -k "skipped_checkout or no_artifact or
   nested_checkout"` → 4 passed, and `test_scan.py` → 40 passed.
2. **Coverage re-baselined on a quiet tree.** Full suite: **1317 passed, 0
   failed, 3 skipped**, line coverage **84%** over `src/fabric_ci_cd_dataops`
   — above the 80% floor.

Blast Radius table re-verified through the installed console script, run
from `C:\Users\jkers\Git` (the pruned root) and from the repository root:

- `fab-test pbir` — names 9 skipped checkouts (repo count grew from 8 to 9
  since the epic was written; the plumbing is what's under test, not the
  fixed number) and the `--artifact-dir` remedy, capped at three paths.
- `fab-test pbir --dry-run` — same message, no plan, as required.
- `fab-test pbir --format json` — narration on stderr, stdout carries
  `skipped_checkouts` (all 9, not capped) and `remediation`.
- `fab-test local` — `pql_test`'s empty-discovery leg carries the same note.
- `fab-test list` from the pruned root — note appears below the table,
  keyed off the glob-having rows only (`playwright-impact`/`dependencies`
  are repository-scoped and always report 1, correctly excluded from the
  "did everything match zero" check).
- `fab-test list --format json` from the pruned root — top-level
  `skipped_checkouts` present.
- From the repository root — `pbir` finds its 2 real artifacts and runs
  them, `list` shows no note (some analyzers matched), both byte-for-byte
  the pre-epic behavior for the in-repo case.
- `--quiet` is not a real CLI flag anywhere in this codebase today (only
  `narrate()`'s `quiet=` parameter, unit-tested but never wired to an
  argparse option) — so there is nothing for the new checkout note to
  differ from; it goes through the same unwired `narrate()` call as the
  message it extends. Confirmed by grep, not assumed.

Documentation (task 4) was already in place for all three callers:
`.github/skills/fab-test/SKILL.md` and `README.md` both describe the
pruning rule, the message shape, and `skipped_checkouts`; `docs/QUICK-VALIDATION.md`
already keeps `--artifact-dir` explicit in its CI YAML example.

## Definition of Done

- [x] Tasks 1–4 complete
- [x] Every entry point in the Blast Radius table verified through the **installed console script**, from both `C:\Users\jkers\Git` and the repository root
- [x] From the repository root, discovery still returns the same 3 artifacts in ~100 ms — this epic changes what is *said* about an empty scan, not what a scan finds
- [x] Full suite green, line coverage over `src/` still above 80% (84%)
- [x] All three callers documented (task 5)
- [x] Conventional commit; epic archived to `tasks/archive/2026-08-23-empty-discovery-diagnostics.md`

## Deliberately Not Doing

- **Descending into sibling repositories.** Considered and declined by the user on 2026-08-22, and the measurement above backs it: 27 artifacts where 12 are copies, with `SampleModel-PQLAssert.Report` appearing four times.
- **Re-plumbing `.pbip` discovery.** [`_pbip_discovery`](../src/fabric_ci_cd_dataops/scripts/_pbip_discovery.py#L58) still uses `rglob` and so walks `.venv`, `node_modules`, and every tree the scanner prunes — 9.7 s against `C:\Users\jkers\Git` versus 0.08 s for the suffix scan. Real, and **out of scope**: it sits in the enrichment path, not the suffix scan that decides whether an artifact exists, and the reported command never reaches it (the empty path short-circuits first, which is why the failing run took 1.8 s). Recorded under Standalone Tasks in [plan.md](../plan.md) instead of distorting this epic.
- **Walking up to a repository root** to relocate the scan. Deferred by Discover From CWD and still deferred: it changes where `fab-test` looks based on something the caller did not say, which is the opposite of the explicit-remediation approach chosen here.
