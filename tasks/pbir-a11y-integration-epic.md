# PBIR Accessibility Integration Epic

**Status**: 📋 PLANNED
**Goal**: Run `pbir-a11y` accessibility checks as a first-class `fab-test` analyzer, surfaced in `--report`, with third-party licenses documented.

## Overview

A Power BI report can pass every PBIR structural rule and still be unusable for someone relying on a screen reader, keyboard navigation, or sufficient contrast. `pbir-a11y` already performs those checks against a PBIP/PBIR folder on disk, but it is a separate Node CLI with its own invocation, output shape, and exit-code meaning — exactly the fragmentation `fab-test` exists to absorb. This epic brings it behind the one contract: one envelope, one set of exit codes, one result path, discoverable through `list`/`explain`/`doctor`, and included in the HTML report. Because it is the first Node-based tool in the fold, `doctor` must also learn to check that Node is installed and say how to fix it when it is not, the way it already does for `.NET`-based and PyPI-based tools. It is also source-available under PolyForm Shield rather than a permissive license, which — together with Tabular Editor 2 and fab-inspector — makes an explicit third-party notices file overdue.

---

## Node Toolchain Bootstrap

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

---

## Node and pbir-a11y Readiness in Doctor

Teach `fab-test doctor` to probe the Node toolchain and the built pbir-a11y CLI, with remediation that names the failing step.

**Requirements**:
- Given Node is not on PATH, should report the `a11y` analyzer as not ready with a reason naming Node and a remediation naming the minimum version (>= 18)
- Given Node is present but `npm` is not, should say so distinctly, since the source-build path needs both and only one is missing
- Given the toolchain is present but nothing is built or cached yet, should report not ready with a remediation naming the bootstrap that would build it and the `PBIR_A11Y_PATH` override
- Given everything resolves, should report ready and include the resolved executable path and the pinned ref it was built from
- Given `--format json`, should emit these checks in the same row shape as every other doctor check so an agent parses one schema
- Given `fab-test doctor --local`, should include the same readiness rows, since the analyzer reads files on disk and needs no workspace

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
