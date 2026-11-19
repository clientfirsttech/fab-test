# fab-inspector 4.0.1 Update Epic

**Status**: ✅ IMPLEMENTED 2026-11-19, 4/4 tasks.
**Goal**: `fab-test pbir` downloads and runs fab-inspector `v4.0.1`, requires the .NET 10 runtime it needs, and every workflow and document that restates the pin or the runtime says so.

## Overview

fab-inspector `v4.0.1` (2026-11-19) is the first stable CLI release since the `v3.4.0` pin; `v3.5.0` and `v4.0.0` were prereleases, which the stable-only update policy skips. Discovery compared upstream's changelog and the `v3.4.0...v4.0.1` diff:

| Area | `3.4.0` → `4.0.1` | Effect on fab-test |
|---|---|---|
| Runtime | .NET 8 → **.NET 10** (4.0.0, marked Breaking upstream; .NET 8 support ended 2026-11-10) | `requires_runtime.min_major` 8 → 10; `live-ci.yml` and `playwright-demo.yml` install `8.0.x`; `flags.md` (both copies) says .NET 8 |
| Assets | same `{platform}-FabInspCLI.zip` names and `{platform}/FabInspCLI/fab-inspector[.exe]` layout | URLs, `version`, `install_sha256s` change; subpaths don't (checked in the characterization task) |
| Rule tags (3.5.0) | new optional `-tags` CLI flag; JSON gains `TagsFilter` per run and `Tags` per result; the HTML template gains a Tags filter | additive; nothing in fab-test passes `-tags` |
| HTML template | Tags filter and fields only; the favicon (`../icon/pbiinspector.png`) and screenshot (`PBIInspectorPNG\<Id>.png`) paths fab-test repairs are unchanged | fixups should keep applying (checked live) |
| SqlClient (4.0.1) | 6.1.7 → 7.1.2, smaller release archives | none; the `sqlquery` operator isn't used by fab-test's rules |
| License | MIT, unchanged | `THIRD-PARTY.md` unchanged |

Decisions (approved by the user, 2026-11-19):

1. **.NET 10 is required, not optional.** `doctor` reports `pbir` not-ready on a machine with only .NET 8, naming the .NET 10 download. This is a behavior change for those machines, recorded in the CHANGELOG; it follows from the pin, since 4.x won't run on .NET 8.
2. **macOS stays on `osx-x64`.** 4.0.1 ships `osx-arm64-FabInspCLI.zip`, but the bootstrap keys install URLs by `sys.platform` only. Choosing by architecture is a separate change, listed as a follow-up.
3. **`-tags` isn't exposed.** Running a subset of rules by tag is a new surface; out of scope for a pin bump.

---

## Characterize 4.0.1 ✅

**Requirements**:
- Given the same local report and rules, should produce native JSON with the same top-level and per-result keys as `3.4.0` (plus the additive `TagsFilter` and `Tags`), and the same findings
- Given `--report`, should still have the favicon and every screenshot inlined in `TestRun.html`
- Given the 4.0.1 archives, should find the executable at the existing `executable_subpaths`

Done live on Windows, not by a fixture: `fab-test pbir --artifact-dir fabric-artifacts --report` with the pinned `3.4.0`, then again with `--inspector-path` on the `v4.0.1` `win-x64-FabInspCLI.zip` (sha256 matched upstream's published digest; executable at `win-x64/FabInspCLI/fab-inspector.exe`, `LICENSE` still MIT). All five PBIR reports gave the same status, the same result and failure counts (29/5, 40/9, 223/1, 51/10, 29/6), identical envelope findings and envelope keys, and the same inlined favicon and screenshot counts in `TestRun.html`. The native JSON gained only `TagsFilter` (run) and `Tags` (result). The wrapper needs no change, so no test was added for it.

---

## Pin consistency test and bump ✅

**Requirements**:
- Given `analyzers.json`'s pbir `tool_install`, every install URL should name `v{version}`, and every platform should have a sha256 (red first: no such test exists for fab-inspector)
- Given the pin is `4.0.1`, should download each platform's archive verified against upstream's published sha256
- Given only .NET 8 is installed, `doctor --analyzer pbir` should report not-ready naming .NET 10 and its download page

`tests/test_pbir_inspector_pin_consistency.py`: red on a half-bump (`version` moved, URLs not), green after. sha256s are upstream's published asset digests (the Windows one also hashed locally). Through the real CLI: the bootstrap downloaded and verified `4.0.1`, `doctor` reports `ready ... (version 4.0.1)`, and `tools/check_tool_updates.py` reports `4.0.1 (current)`. With a stub `dotnet` listing only 8.x, `doctor` prints `❌ pbir: .NET 10+ runtime not found (installed: 8.x)` with the .NET 10 link, exit 1. With `DOTNET_ROOT` on a folder holding only the 8.0 runtime, `fab-inspector.exe` refuses to start ("Framework: 'Microsoft.NETCore.App', version '10.0.0'"), and `fab-test pbir` writes an `error` envelope, exits 1 and shows that message: the floor is real, not cautious.

---

## Workflows and docs name .NET 10 ✅

**Requirements**:
- Given `requires_runtime.min_major`, every workflow that installs .NET should install at least that major, and the skill's `flags.md` and the human prerequisites (`docs/QUICK-VALIDATION.md`) should name it (test, so the next runtime bump can't miss one)
- Given the packaged skill, should match its authored source (`flags.md`, and `SKILL.md`'s `doctor` example version)
- Given the behavior change, the CHANGELOG should say a machine with only .NET 8 now fails `doctor`/`pbir` for `pbir`

Red first on `live-ci.yml:60`, `playwright-demo.yml:130`, both `flags.md` and `QUICK-VALIDATION.md:9`; green after. `playwright-demo.yml`'s .NET also serves the RLS lookup's XMLA fallback (pythonnet coreclr loads ADOMD.NET's `net8.0` build, on the newest runtime installed). Checked on Windows with coreclr and a runtime root holding only .NET 10: the `net8.0` ADOMD.NET loads and constructs an `AdomdConnection` on `.NET 10.0.14`. That's a load check, not a live XMLA query; the next `playwright-demo` run on Linux is the live check.

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)

**Result** ✅: `ruff check .` clean; `pytest -n auto -m "not playwright" --cov` 3350 passed, 2 skipped (includes the complexity and module-budget ratchets); `pytest -m playwright --cov --cov-append --cov-fail-under=80` 220 passed, floor held at 91% (exit 0).
