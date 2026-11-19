# fab-inspector .NET 8 Fallback Epic

**Status**: ✅ IMPLEMENTED 2026-11-19, 5/5 tasks; decisions 4-7 provisional, awaiting review.
**Goal**: on a machine with the .NET 8 runtime but not .NET 10, `fab-test pbir` runs fab-inspector `3.4.0` (the last release that runs on .NET 8) instead of failing, and says so every run, until the fallback is removed.

## Overview

The fab-inspector 4.0.1 Update epic made .NET 10 a hard requirement (its decision 1). On a machine with only .NET 8, `4.0.1` refuses to start, `doctor` reports `pbir` not-ready, and `fab-test pbir --report` writes an `error` envelope whose page says "PBIR Inspector wrote no page this run". The user hit this on a second machine and asked for a fallback (2026-11-19).

.NET has no backward roll-forward: `4.0.1` can't run on .NET 8 at any setting. So the fallback is a second, older pin, not a runtime switch. That epic's characterization showed `3.4.0` and `4.0.1` give identical findings, envelopes and HTML on every PBIR report in `fabric-artifacts/`; `3.4.0` lacks only the additive `TagsFilter`/`Tags`.

Decisions (user, 2026-11-19, reversing the 4.0.1 epic's decision 1):

1. **Fallback to `3.4.0` when .NET 10 is missing and .NET 8 is present.** Neither present: not-ready naming .NET 10, as today.
2. **Temporary.** .NET 8 reached end of support on 2026-11-10, so the fallback keeps fab-test on a runtime without security fixes. Remove it when a fab-inspector release needs what 4.x adds, or by **2027-02-10** at the latest (tracked in plan.md).
3. **Said every run.** A fallback run prints one line naming the version used and how to get 4.0.1 (a `::warning::` annotation in CI); `doctor` reports ready with the same note.

Provisional (made while working, awaiting review):

4. **The envelope doesn't record the tool version.** No analyzer's envelope records one today; it would mean threading the version from the resolver through the command builder into the wrapper, for a temporary path. The per-run line and `doctor` carry it instead.
5. **Declared in `analyzers.json` as `tool_install.runtime_fallback`**: the keys that differ (`version`, `install_urls`, `install_sha256s`, `requires_runtime`), laid over the pin. Generic in shape, but only `pbir` uses it; no abstraction past that one merge.
6. **`doctor` shows a ready fallback as ⚠ `warning`**, the status that prints its remedy; exit 0, but `doctor --strict` fails it. Without that, the text `doctor` printed the fallback reason but not how to get 4.0.1 (it prints remedies only for rows that aren't ready).
7. **The line is stderr only, `-q` included; the HTML report doesn't repeat it**, the same as the bootstrap's download notices. `--format json` stdout stays one document.

---

## Move runtime checks out of the bootstrap module ✅

`_analyzer_tool_bootstrap.py` is 798 lines against the 800-line hard budget (`aidd-module-budgets`), so the fallback can't be added to it. The runtime probes (`dotnet --list-runtimes`, `node --version`) and `_runtime_gap` are their own seam.

**Requirements**:
- Given the move to `_tool_runtime.py`, every existing bootstrap and readiness test should pass unchanged

Moved verbatim (`_runtime_gap` → public `runtime_gap`); the bootstrap went 798 → 715 lines before the fallback, 750 after. Three tests patched `_analyzer_tool_bootstrap.subprocess.run`; they now name the module that runs the subprocess (`_tool_runtime`, and `_npm_toolchain` for the npm-build test). 86 passed.

---

## Fall back to the older pin ✅

**Requirements**:
- Given .NET 10 missing and .NET 8 present, `doctor` should report ready, with the fallback version and a remediation naming .NET 10
- Given .NET 10 missing and .NET 8 present, `resolve_executable` should download, verify and cache the fallback's archive under its own version, and print the fallback line
- Given .NET 10 present, should resolve the pin exactly as before, without a fallback line
- Given neither runtime, should report not-ready naming .NET 10, the pin's runtime, not the fallback's
- Given an analyzer without `runtime_fallback`, should behave exactly as before
- Given a binary of the caller's own (`--inspector-path`, the env var or the default path), should not claim a fallback

`tests/test_tool_runtime_fallback.py`: 5 red (the fallback behaviors) and 5 green guards (unchanged behaviors) before `select_tool_install` existed; 10 green after, plus `status == "warning"` red then green (decision 6).

---

## Declare the 3.4.0 fallback ✅

**Requirements**:
- Given `runtime_fallback`, its install URLs should name its own version and every platform should have a sha256 (extend the pin-consistency test)
- Given the docs, should name both runtimes: .NET 10 for the pin, .NET 8 for the fallback
- Given a machine with only .NET 8 (live, `DOTNET_ROOT` on a .NET 8-only folder), `fab-test pbir --report` should give `3.4.0`'s findings and its page

Pin-consistency cases now run for `pin` and `fallback`: red on `KeyError: 'runtime_fallback'`, green once declared. The fallback's sha256s are upstream's v3.4.0 asset digests (re-read from the release today). Live on Windows with a stub `dotnet` listing only 8.x and `DOTNET_ROOT` on a .NET 8-only folder: with the 3.4.0 cache deleted, `fab-test pbir ThinReport --report` printed the fallback line, downloaded and verified 3.4.0, gave 6 findings and wrote `TestRun.html`; across all five reports, results, failures, findings and inlined images matched this morning's 3.4.0 baseline. `doctor` showed `⚠ pbir: … using fallback version 3.4.0 …` and `→ Install the .NET 10 runtime to use 4.0.1: …`, exit 0 (`--strict` 1). `--format json` stdout parsed as one document with the line on stderr; `-q` printed the line and the result.

---

## Docs ✅

**Requirements**:
- Given the fallback, `flags.md` (both copies), `QUICK-VALIDATION.md` and the CHANGELOG should say what runs on .NET 8, that it's temporary, and the removal date
- Given decision 2, plan.md should carry a standalone task to remove the fallback

---

## Quality gates ✅

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)

**Result** ✅: `ruff check .` clean; `pytest -n auto -m "not playwright" --cov` 3362 passed, 2 skipped (includes the complexity and module-budget ratchets); `pytest -m playwright --cov --cov-append --cov-fail-under=80` 220 passed, floor held at 91% (exit 0).
