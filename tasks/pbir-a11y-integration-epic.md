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

## A11y Analyzer Wrapper  ✅

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

Done: `invoke_pbir_a11y.py` mirrors `invoke_pbir_inspector.py`'s shape (the
same `log`/`validate_path`/`Timer`/`build_envelope` primitives) with one
structural difference the real tool forced: pbir-a11y writes its `--json`
output to **stdout only** — there is no `-output`/`--output` flag the way
PBIR Inspector has — so this wrapper, not the tool, is what persists
`native.json`. The command is always built with `--json` (no human-format
branch to parse) and forwards `--fail-on` only when the caller passes one;
omitting it lets pbir-a11y's own default (`"fail"`, confirmed by reading
`check.ts` directly) take over, which already matches the requirement's
intent — warn/info findings are reported but don't fail the run unless a
caller tightens it.

Findings are flattened from the tool's page/visual-nested JSON
(`pages[].issues[]` for page-level, `pages[].visuals[].issues[]` for
visual-level) into the shared four-column schema (`rule`/`severity`/
`object`/`message`), with `category`/`page`/`visual` added as additive
extra keys — present for the `--report` task to group by, ignored by the
shared table renderer that only reads the canonical four. Severity maps
pbir-a11y's four-value vocabulary (`fail`/`warn`/`info`/`pass`) onto
fab-test's three (`error`/`warning`/`info`); `pass` is handled defensively
(mapped to `info`) though it never appears on a real reported issue in
practice.

Classification keys off **pbir-a11y's own exit code** rather than
re-deriving fail/pass from severities alone — exit `2` (bad/unreadable
path) always yields envelope `status: "error"`, distinct from `"failed"`
(exit `1`, a real violation at/above the fail-on threshold) and `"warning"`
(exit `0` with findings below the threshold) — proven with a dedicated test
(`test_run_reports_tool_error_distinctly_from_findings`) rather than
inferred from reading the code. `126`/`127` preflight exit codes were
already delivered for free once Task 2 registered `a11y` into
`_BOOTSTRAPPED_ANALYZERS` (unsupported-platform/missing-tool are caught
before this wrapper ever spawns); a runtime-only failure discovered *after*
a tool is already resolved and cached — the machine actually running the
check lacks `node`, or `node` disappears mid-session — mirrors PBIR
Inspector's own convention of returning 1 with a clear failure envelope
rather than a traceback (`FileNotFoundError` from `subprocess.run`, same as
every other wrapper's crash-boundary handling).

Verified against the **real, live tool**, not a synthetic fixture, before
writing a single test: resolved the real `pbir_a11y` build in this actual
checkout (Task 1's bootstrap), then invoked the wrapper module directly
against a real fab-test fixture (`ThinReport.Report`) — 4 real findings (1
error, 3 warnings), correct envelope, exit code 1. This surfaced a second
real, previously-unknown defect: `subprocess.run(..., text=True)` decodes
Node's UTF-8 stdout using the OS default locale encoding, which corrupted
the middle-dot character (`·`) in a real alt-text finding's message into
mojibake on this Windows machine (`cp1252` decode of UTF-8 bytes) — the
same class of encoding defect already on record elsewhere in this repo
(`validate_environments_schema.py`'s emoji crash, `check_tool_updates.py`'s
console symbols), but manifesting as silent corruption rather than a crash,
so it would not have surfaced from a mocked-subprocess unit test alone.
Fixed by passing `encoding="utf-8"` explicitly to `subprocess.run` rather
than relying on `text=True`'s locale default; re-verified against the same
real finding by reading its exact Unicode codepoints (`0xb7`, correct)
rather than trusting a terminal's own rendering, since the terminal itself
turned out to be an unreliable way to confirm this on this machine. A
regression test (`test_run_uses_utf8_explicitly_for_subprocess_decoding`)
pins the fix.

`tests/test_invoke_pbir_a11y.py` (new, 32 tests) added a registered `a11y`
pytest marker (`pytest.ini`) alongside the existing per-analyzer markers,
covering: command building and `--fail-on` forwarding, severity mapping,
finding extraction from a realistic nested fixture, all three classification
branches (passed/warning/failed/error), missing artifact/tool path exits,
node-absent-at-resolve-time and node-absent-at-run-time (two different
failure points, both must degrade to a clear envelope), the UTF-8 fix, and
`main()`'s `--verbose` plumbing. Full suite: **1525 passed, 0 failed, 3
skipped**, coverage held (floor 80%); complexity and module budgets
re-confirmed clean.

---

## Analyzer Registration and Targeting  ✅

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

Done: `build_a11y_command` (mirrors `build_bpa_command`/`build_pbir_command`
exactly) resolves the tool path from `args._resolved_tool_path` first
(the real cached build, once `resolve_tool` has run), falling back to an
explicit `--a11y-path`/`PBIR_A11Y_PATH` override or the packaged default,
and forwards `--fail-on` only when the caller passed one. Registered in
`_COMMAND_BUILDERS`, and a new `_add_a11y_subparser` (`fab_test_parser.py`)
adds the real `fab-test a11y` subcommand with `--a11y-path`/`--fail-on`
flags, following `_add_pbir_subparser`'s exact shape. Removed `"a11y"` from
`HIDDEN_ANALYZERS` (added there temporarily in Task 2, before this task's
command builder/subparser existed) — it is now a fully first-class,
advertised analyzer, not tucked away like `pql_lint`. Added `"a11y":
"pbir-a11y"` to `fab_test_admin.py`'s `_TOOL_DISPLAY_NAMES` so `fab-test
list`'s "Required Tool" column reads `pbir-a11y` rather than `(none)`.

Every requirement verified against the **real installed CLI**, not just
unit tests: `fab-test a11y --help` shows the full flag set; `fab-test list`
advertises `a11y` with its glob (`*.Report`) and description; `fab-test
explain a11y` shows the resolved tool path, output path, and full command
line; `fab-test a11y "WORKSPACE.Workspace/Foo.Report"` refuses with "a11y
reads artifact files on disk and cannot fetch a deployed item", naming the
forms that do work; `fab-test a11y "Sales.SemanticModel"` refuses naming
both halves ("a11y reads Report artifacts; ... is a SemanticModel");
`fab-test a11y --jobs 4` against 4 real artifacts completed in ~3.8s
(parallelized, not run serially); a real end-to-end run against a fixture
with real findings produced pure-JSON stdout under `--format json`
(confirmed by piping `2>/dev/null` — an earlier same-terminal `2>&1` test
had merged stderr narration into the stream and looked like a purity
violation until re-tested correctly, a false alarm caught before it was
recorded as a defect); and manually appending `"a11y"` to `analyzers.json`'s
`fab_test_all` list made `fab-test all --dry-run` pick it up immediately,
confirming the opt-in mechanism works as designed (reverted immediately
after, via `git checkout --`, since the edit was for verification only —
the accidental side effect of a Python `json.dump` rewriting the whole
file's formatting was caught by `git diff --stat` before it was mistaken
for legitimate work).

Two pre-existing behaviors were confirmed unaffected by registering a
visible `.Report`-glob analyzer, not newly broken by it:
`applicable_analyzers()`'s per-artifact dry-run annotation for *other*
analyzers now also lists `a11y` for every Report artifact (the same
discovery-glob derivation `pql_lint` already exercises for `.SemanticModel`
artifacts) — expected, not a regression, and `tests/test_fab_test_discovery.py`'s
`test_applicable_analyzers_for_report`'s exact-tuple assertion was updated
to include it. `tests/test_readiness.py`'s Task-2-era hidden-state test was
rewritten to assert the opposite (visible, not hidden) now that this task
completed the wiring it was waiting on. `tests/test_target_scopes.py` and
`tests/test_fab_test_command_builders.py` each gained dedicated tests for
`a11y`'s workspace refusal, type refusal, and command-building (default
path, resolved-tool-path precedence, `--fail-on` forwarding).
`tests/test_module_budget.py`: `fab_test_parser.py`'s exemption ceiling
raised 911 → 938 (the new subparser), `fab_test_registry.py`'s raised
842 → 872 (the command builder). Documenting `fab_test_all`'s opt-in path
for a team that wants `a11y` running by default is carried by the
Documentation task below, not repeated here.

Full suite: **1531 passed, 0 failed, 3 skipped**, coverage held (floor 80%);
complexity and module budgets re-confirmed clean.

---

## Accessibility Findings in `--report`  ✅

Include a11y results in the HTML report and its index alongside the other analyzers.

**Requirements**:
- Given `--report` and an a11y run, should write the HTML report beside the envelope and name the written path on stdout exactly once
- Given `fab-test all --report`, should list the a11y report in the index without duplicating any other analyzer's entry
- Given findings across several categories, should group or filter them so a reader can isolate one category without reading the whole table
- Given zero findings, should still write a report that says so rather than omitting the analyzer from the index

Done: `_report_html.py`'s own docstring states the design this task fits
into: "one renderer for every analyzer... computes no finding of its own."
`invoke_pbir_a11y.py` was the only piece actually missing — it built an
envelope but never called `attach_report`, unlike `bpa`/`pql_test`/
`playwright`. One import plus one call in `write_results` (mirroring
`invoke_tabular_editor_bpa.py`'s exact pattern) was the entire code change.

The category-grouping requirement turned out to already be satisfied by
existing, analyzer-agnostic machinery once traced through rather than
needing new code: the report's search box (`_SEARCH_SORT_SCRIPT`) filters
on `row.textContent`, matching against every column including "Message" —
and Task 3's finding mapping already prefixes each message with
`[category]` specifically so a reader could isolate one this way. Clicking
a column header sorts alphabetically, which clusters same-category rows
together for the same reason. Confirmed live, not just reasoned about:
generated a real report against `ThinReport.Report`'s findings and grepped
the actual HTML for `altText`/`pageTitles`/`visualTitles` — present and
readable, not escaped away. The index requirement (`render_index`) was
confirmed structurally rather than by adding a special case: it iterates
whatever `rows` list the aggregate summary already built, with zero
analyzer-specific branches — the same generic path `bpa`/`pbir`/`pql_test`
already exercise, so there is no code path that *could* duplicate an
entry regardless of which analyzer produced it.

Verified against the **real CLI**, not only a unit test: `fab-test a11y
"ThinReport.Report" --report` wrote `report.html` beside the envelope and
printed `Report: fab-test-results\a11y\ThinReport\report.html` exactly once
in the run summary. A new unit test
(`test_run_writes_a_report_when_enabled_even_with_zero_findings`) pins the
zero-findings case specifically, since that path has no findings to prove
anything rendered correctly by eye — asserting the artifact's own name
still appears in the written report.

Full suite: **1532 passed, 0 failed, 3 skipped**, coverage held (floor 80%);
complexity and module budgets re-confirmed clean.

---

## Third-Party Notices  ✅

Add `THIRD-PARTY.md` documenting each wrapped tool, its license, and where the license text lives.

**Requirements**:
- Given a reader deciding whether they may use `fab-test` commercially, should find Tabular Editor 2, fab-inspector, and pbir-a11y each named with its license and a link to the license text
- Given pbir-a11y's PolyForm Shield license, should state plainly that it is source-available with a non-compete restriction, and that `fab-test` wraps rather than redistributes it
- Given a tool that is downloaded at run time rather than vendored, should say so, since nothing is bundled into the distributed package
- Given a new wrapped tool added later, should have a stated place and format to record it so the file does not go stale

Done: Verified each license against the real upstream source rather than
assuming — `gh api repos/TabularEditor/TabularEditor`/`repos/NatVanG/
fab-inspector` both confirm MIT (matching the SPDX field GitHub reports);
pbir-a11y's `package.json` already confirmed PolyForm Shield 1.0.0 during
Task 1's research. `THIRD-PARTY.md` (new, repo root) tables all three with
a link to each repo's actual `LICENSE` file at its real default branch
(`master` for TabularEditor/TabularEditor, `main` for the other two —
checked individually rather than assumed uniform), states plainly that
nothing is vendored (every tool is downloaded or built at runtime, cached
under `.fab-test-tools/`, called as an external process), and gives
PolyForm Shield its own section spelling out the can/cannot split in plain
language plus why wrapping it as a subprocess call doesn't trigger the
non-compete restriction. README's License section gained a two-sentence
pointer to it, since a reader checking a repo's license normally starts
there, not at a file they'd have to already know existed.

`tests/test_third_party_notices.py` (new) is the "stated place and format"
requirement made enforceable rather than just written down: it reads every
`analyzer_registry` entry with a `tool_install` block straight out of the
real `analyzers.json` and fails, naming which one, if `THIRD-PARTY.md`
doesn't mention it — so a future wrapped tool added without a matching row
fails a test instead of going stale silently, the same discipline
`test_pql_test_pin_consistency.py` already applies to the `pql-test` pin.
Also asserts the PolyForm Shield section reads as source-available (not
blending in with the two MIT rows) and that README actually points at the
file. Verified the drift-detection actually works, not just that the tests
exist: temporarily redacted every "pbir-a11y" mention from the file,
watched `test_every_tool_install_analyzer_is_named_in_third_party_md` fail
naming exactly `pbir_a11y`, then restored the file and re-confirmed green
(the redaction couldn't be `git checkout --`-reverted since the file was
still untracked at that point — rewritten back to the verified-correct
content directly rather than left corrupted).

Full suite: **1537 passed, 0 failed, 3 skipped**, coverage held (floor 80%);
complexity and module budgets re-confirmed clean.

---

## Documentation for Three Callers

Close out the epic against the Definition of Done in vision.md.

**Requirements**:
- Given an AI agent, should find the new subcommand, flags, exit codes, and envelope shape in the `fab-test` skill
- Given a human, should find the analyzer, its Node prerequisite, and a worked example in README and docs
- Given a pipeline author, should find a copy-pasteable workflow snippet that installs Node, installs the tool, and runs the check
