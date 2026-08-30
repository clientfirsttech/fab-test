# PBIR Accessibility Integration Epic

**Status**: 📋 PLANNED
**Goal**: Run `pbir-a11y` accessibility checks as a first-class `fab-test` analyzer, surfaced in `--report`, with third-party licenses documented.

## Overview

A Power BI report can pass every PBIR structural rule and still be unusable for someone relying on a screen reader, keyboard navigation, or sufficient contrast. `pbir-a11y` already performs those checks against a PBIP/PBIR folder on disk, but it is a separate Node CLI with its own invocation, output shape, and exit-code meaning — exactly the fragmentation `fab-test` exists to absorb. This epic brings it behind the one contract: one envelope, one set of exit codes, one result path, discoverable through `list`/`explain`/`doctor`, and included in the HTML report. Because it is the first Node-based tool in the fold, `doctor` must also learn to check that Node is installed and say how to fix it when it is not, the way it already does for `.NET`-based and PyPI-based tools. It is also source-available under PolyForm Shield rather than a permissive license, which — together with Tabular Editor 2 and fab-inspector — makes an explicit third-party notices file overdue.

---

## Node Toolchain Bootstrap  ✅

Extend the analyzer tool bootstrap with a source-build path: fetch pbir-a11y from GitHub at a pinned ref, `npm install`, `npm run build`, and cache the built CLI the way the zip-extract path caches an unpacked binary.

**Requirements**:
- Given no cached install, should fetch the pinned git ref, build it, and resolve the built `dist/cli.js` entry point without the caller doing anything but run the analyzer
- Given a cached build for the pinned ref, should reuse it rather than rebuilding on every run
- Given `PBIR_A11Y_PATH` is set, should use that executable and never fetch or build
- Given the pinned ref changes, should rebuild rather than silently serve the previous build
- Given `npm` is absent, the network is unreachable, or the build fails, should fail with a message naming which step failed and the manual install as a fallback — never a partially built cache left behind for the next run to trust
- Given the existing zip-extract analyzers, should keep resolving exactly as before, since the bootstrap now has two acquisition shapes and one is new
- Given acquisition method is chosen, should be selected by a declared `analyzers.json` key rather than a branch on the analyzer's name, so a later npm-published pbir-a11y is a new method plus a metadata edit and no change to resolution order, caching, doctor, or the wrapper
- Given a resolved executable, should reach every downstream caller as a plain path carrying no trace of how it was acquired

Done: `_analyzer_tool_bootstrap.py` gained a second acquisition shape,
selected by `tool_install.archive_type: "npm_build"` (the existing
`archive_type` field, previously single-valued at `"zip"`) rather than a
branch on the analyzer's name — `resolve_executable`'s dispatch is now
`if archive_type == "zip": ... elif archive_type == "npm_build": ...`,
sharing every version-keyed-cache/local-candidate/shadow-note mechanism the
zip path already had. `_download_build_and_cache` mirrors
`_download_and_cache`'s download/verify/extract steps, then adds
`_find_build_root` (locates `package.json` inside the archive — GitHub's
tag-archive zip nests everything under one `<repo>-<ref>/` folder whose name
isn't knowable in advance, so this is an `rglob`, not a fixed path) and
`_run_npm_build` (runs `npm install`, then any declared
`build_extra_dependencies`, then `npm run build`, each step wrapped by
`_run_build_step` so a failure names *which* step broke — including npm's
own absence, which surfaces as `FileNotFoundError` the same way a missing
tool binary does elsewhere in this module). On any failure the partially
extracted/built cache directory is removed (`shutil.rmtree` in the `except`
clause) before re-raising, and the marker file — the only thing a later run
consults — is written only after `_find_executable` locates a real entry
point, so a broken build never gets mistaken for a working one on the next
run.

Verified against the **real upstream tool**, not a synthetic fixture, before
writing a single test: downloaded `Juls-BI/pbir-a11y`'s real tag archives and
ran `npm install && npm run build` by hand. This surfaced a genuine upstream
defect: `v0.3.2` (the newest tag)'s `package.json` dropped the `docx`
dependency that `src/lib/docxReport.ts` still `require()`s unconditionally
at module load, so a plain build produces a `dist/cli.js` that crashes on
*any* invocation (`Error: Cannot find module 'docx'`), not just `--docx`
usage — confirmed by diffing `package.json` at `v0.2.0` (declares `docx`
correctly) against `v0.3.2` (doesn't) and reproducing the crash directly.
Asked the user whether to pin the last known-good tag (`v0.2.0`) or keep
`v0.3.2` with a workaround; chose to keep `v0.3.2` and paper over the gap —
`tool_install.build_extra_dependencies: ["docx@^9.6.1"]` (the exact version
`v0.2.0` pinned) becomes a second, distinct `npm install` call after the
first, confirmed live to fix the build (exit 0) and produce a working
`check --json` against a real fab-test fixture (`ThinReport.Report`). Then
ran the *actual* `resolve_executable("pbir_a11y", ...)` end-to-end against
the real `analyzers.json` entry in a scratch repo root — real network
download, real `npm install`/`npm install docx@^9.6.1`/`npm run build`,
real resolved `dist/cli.js` — and ran the resolved CLI against a real
artifact before writing any test; confirmed a second resolve at the same
version is instant (0.013s, no rebuild).

`probe_executable`'s wording is now acquisition-method-aware: `archive_type:
"npm_build"` reports "not yet built" (not "not yet downloaded") and checks
Node/npm presence before reporting what *would* happen, returning a
distinctly worded, distinctly remediated result for Node missing vs. npm
missing vs. toolchain-present-nothing-cached — the split was pulled into a
new `_probe_pending_install` helper specifically to keep `probe_executable`
itself under the complexity ratchet's return-statement ceiling (adding the
two new branches inline pushed it to 7 returns against a ceiling of 6).

`tests/test_pbir_a11y_tool_bootstrap.py` (new, 11 tests) exercises real
`npm`/`node` subprocesses against synthetic zero-dependency fixtures (a
`build.js` that just writes a marker file, so no real package is fetched
and each test runs in ~2-4s) rather than mocking `subprocess.run` for the
integration-shaped tests: build-from-source end-to-end, cache reuse without
rebuild (`_download`/`_run_npm_build` patched to raise if called), a version
bump forcing a fresh build while the old version's cache is left alone
(mirrors the zip path's equivalent test — both share `_cache_dir`), build
failure leaving no partial cache, npm absence reported clearly, and each of
`probe_executable`'s three npm_build branches. `_run_npm_build`'s extra-
dependency argument order is the one place `subprocess.run` is mocked
directly, since asserting exact argv shape doesn't need a real process.
This pushed the original `test_fab_test_tool_bootstrap.py` from 708 to 1020
lines (over the 900-line hard budget), so the new section was split into
its own file rather than exempted — matching the Test Module Split epic's
precedent of splitting by behavior rather than raising the ceiling. Full
suite: **1491 passed, 0 failed, 3 skipped**, coverage held (floor 80%);
`test_complexity_budget.py` and `test_module_budget.py` re-confirmed clean
after the split and the `_probe_pending_install` extraction.

---

## Node and pbir-a11y Readiness in Doctor  ✅

Teach `fab-test doctor` to probe the Node toolchain and the built pbir-a11y CLI, with remediation that names the failing step.

**Requirements**:
- Given Node is not on PATH, should report the `a11y` analyzer as not ready with a reason naming Node and a remediation naming the minimum version (>= 18)
- Given Node is present but `npm` is not, should say so distinctly, since the source-build path needs both and only one is missing
- Given the toolchain is present but nothing is built or cached yet, should report not ready with a remediation naming the bootstrap that would build it and the `PBIR_A11Y_PATH` override
- Given everything resolves, should report ready and include the resolved executable path and the pinned ref it was built from
- Given `--format json`, should emit these checks in the same row shape as every other doctor check so an agent parses one schema
- Given `fab-test doctor --local`, should include the same readiness rows, since the analyzer reads files on disk and needs no workspace

Done: The Node/npm-aware probing itself (distinct reasons for Node missing,
npm missing, and "not yet built") landed in Task 1's `probe_executable`
extension — this task is what wires `a11y` into `fab_test_registry.py`'s
tables so `doctor` can reach it at all: `ANALYZER_REGISTRY` (`*.Report`),
`ANALYZER_SCOPES` (`path`, `desktop` — same as `pbir`, no workspace), `
_BOOTSTRAPPED_ANALYZERS`, `_BOOTSTRAP_REGISTRY_NAME` (`"a11y" ->
"pbir_a11y"`, since the CLI subcommand and the `analyzers.json` key
deliberately differ, matching `pbir`/`pbir_inspector`'s existing precedent),
`_TOOL_FLAG_HINTS`, and a `getattr(args, "a11y_path", None)` branch in both
`resolve_tool` and `_readiness_without_version` — safe to add before the CLI
flag itself exists, since `getattr`'s default just returns `None` until
Task 4's `--a11y-path` argument lands.

Registering it in `ANALYZER_REGISTRY` also made it eligible everywhere else
that table drives — `fab-test list`, the default `doctor` report, and
discovery's glob-matching — before its command builder and subparser exist
(Task 3/4), which would have exposed a subcommand argparse doesn't actually
accept yet. Added `"a11y"` to the existing `HIDDEN_ANALYZERS` set (previously
just `{"pql_lint"}`) to hold that surface back: `doctor --analyzer a11y`
answers a direct question (confirmed live: reports `"not yet built"` with
the exact remediation text, including the `PBIR_A11Y_PATH` override
mention added to `_probe_pending_install` for this requirement), while
`fab-test list` and the default `fab-test doctor` correctly still omit it —
both confirmed against the real installed CLI, not just a unit test. This
mirrors `pql_lint`'s exact existing precedent (hidden but fully invocable),
including one pre-existing wrinkle that precedent already had and this
change inherits rather than introduces: `applicable_analyzers()` (the
per-artifact "(analyzers: ...)" annotation another analyzer's `--dry-run`
prints) does not filter `HIDDEN_ANALYZERS` — `pql_lint` already appeared
there for `.SemanticModel` artifacts before this epic, and `a11y` now does
the same for `.Report` artifacts. Fixing that filter gap was judged
out of scope here: it would change `pql_lint`'s behavior too, is not named
in any requirement above, and risks the exact kind of undirected cleanup
this repo's constraints ask reviewers to push back on.

Blast Radius re-verified through the real CLI after the registry edit, not
just the one path that prompted it: `fab-test doctor` (a11y absent from the
default view), `fab-test doctor --analyzer a11y --format json` (reports
correctly), `fab-test list` (a11y absent), `fab-test bpa --dry-run` and
`fab-test pbir --dry-run` (both still run correctly; the latter's per-
artifact annotation now includes `a11y`, the expected discovery-glob
consequence of registration, not a regression). `_LOCAL_ANALYZERS`
(`fab-test local`'s run set and `doctor --local`'s row set) deliberately
was **not** touched yet — adding `a11y` there would make `fab-test local`
try to actually run it, which fails today with no command builder (Task 3);
picking that up once the wrapper exists is more honest than reporting a
readiness row for a bundle member that cannot yet run.

`tests/test_readiness.py` gained two tests: `check_readiness("a11y", args)`
delegating via its own `--a11y-path`-shaped attribute (mirrors the existing
`bpa` delegation test), and a dedicated hidden-but-answerable contract test.
The pre-existing `test_check_readiness_returns_same_shape_for_every_analyzer`
(iterates `ANALYZER_REGISTRY` directly, not filtered by `HIDDEN_ANALYZERS`)
already covered `a11y`'s five-key shape for free once registered.
`tests/test_fab_test_discovery.py`'s `test_applicable_analyzers_for_report`
needed its exact expected tuple updated from `("pbir", "playwright")` to
`("pbir", "a11y", "playwright")` — a genuine, expected consequence of
registration, not a defect. `tests/test_module_budget.py`:
`fab_test_registry.py`'s exemption ceiling raised from 829 to 842 lines (13
lines for the registration surface above). Full suite: **1493 passed, 0
failed, 3 skipped**, coverage held (floor 80%).

---

## A11y Analyzer Wrapper

Add `invoke_pbir_a11y.py`, wrapping `pbir-a11y check --json` and emitting a standard result envelope.

**Requirements**:
- Given a `*.Report` artifact path, should invoke the CLI with `--json` and write an envelope plus the native JSON output under the standard result path
- Given no explicit severity flag, should invoke with the tool's default `--fail-on error`, so warnings are reported without failing the run
- Given `--fail-on <severity>`, should pass the value through so a pipeline can tighten to `warn` without a fab-test-specific concept of severity
- Given the CLI exits 1 for findings at or above the fail-on severity, should write a `failed` envelope and exit 1
- Given the CLI exits 2 for a bad or unreadable path, should distinguish that tool error from a rule violation in both the envelope status and the process exit code
- Given the CLI is missing or the run exceeds its timeout, should fail with the same preflight exit codes the other bootstrapped analyzers use (126/127) rather than a traceback
- Given a finding, should map its rule, category, page, visual, and severity into the envelope finding shape so the summary table and report need no analyzer-specific branches
- Given `--verbose`, should surface the invoked command and the tool's own output the way the other wrappers do

---

## Analyzer Registration and Targeting

Register the analyzer so it is discoverable and targetable through the existing grammar rather than a special case.

**Requirements**:
- Given the analyzer is invoked, should be spelled `fab-test a11y` on the command line, registered under `pbir_a11y` in `analyzers.json`, and consistent with that pair everywhere it is named
- Given `fab-test list`, should advertise the analyzer with its artifact glob and description
- Given `fab-test explain a11y`, should describe what it checks, what it needs, and what its exit codes mean
- Given a `local/NAME` or path target, should accept it; given a workspace target, should refuse with a message saying it reads files on disk
- Given a non-Report artifact, should be skipped by discovery rather than run and failed
- Given `fab-test all`, should not run the analyzer, since it is deliberately left out of the configured `fab_test_all` list — a pipeline that passed before this epic passes after it
- Given a team that wants it in `fab-test all`, should be able to add it by editing the `fab_test_all` list in `analyzers.json`, with that documented as the supported opt-in
- Given a run with `--jobs N`, should parallelize per artifact like every other analyzer

---

## Accessibility Findings in `--report`

Include a11y results in the HTML report and its index alongside the other analyzers.

**Requirements**:
- Given `--report` and an a11y run, should write the HTML report beside the envelope and name the written path on stdout exactly once
- Given `fab-test all --report`, should list the a11y report in the index without duplicating any other analyzer's entry
- Given findings across several categories, should group or filter them so a reader can isolate one category without reading the whole table
- Given zero findings, should still write a report that says so rather than omitting the analyzer from the index

---

## Third-Party Notices

Add `THIRD-PARTY.md` documenting each wrapped tool, its license, and where the license text lives.

**Requirements**:
- Given a reader deciding whether they may use `fab-test` commercially, should find Tabular Editor 2, fab-inspector, and pbir-a11y each named with its license and a link to the license text
- Given pbir-a11y's PolyForm Shield license, should state plainly that it is source-available with a non-compete restriction, and that `fab-test` wraps rather than redistributes it
- Given a tool that is downloaded at run time rather than vendored, should say so, since nothing is bundled into the distributed package
- Given a new wrapped tool added later, should have a stated place and format to record it so the file does not go stale

---

## Documentation for Three Callers

Close out the epic against the Definition of Done in vision.md.

**Requirements**:
- Given an AI agent, should find the new subcommand, flags, exit codes, and envelope shape in the `fab-test` skill
- Given a human, should find the analyzer, its Node prerequisite, and a worked example in README and docs
- Given a pipeline author, should find a copy-pasteable workflow snippet that installs Node, installs the tool, and runs the check
