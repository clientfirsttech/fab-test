# Analyzer Runtime Readiness Epic

**Status**: ✅ COMPLETED (2026-09-03)
**Goal**: Stop `doctor` from reporting an analyzer ready when its language runtime is absent, and stop the PBIR wrapper from reporting a pass when the tool never ran.

## Overview

A developer runs `fab-test doctor`, sees `pbir` ready, runs the analyzer, and gets
a clean pass — on a machine with no .NET 8 runtime, where PBIR Inspector never
executed a single rule. Two independent defects compound into a silent false
negative, which is the worst outcome the vision allows: a green report that
proves nothing. This epic makes "ready" mean "will actually run" and makes a
tool that could not start report as an error instead of a pass.

---

## Defect 1 — `doctor` reports readiness from binary presence alone

`check_readiness("pbir")` delegates to `probe_executable`, which resolves and
reports on the *binary file* only ([_analyzer_tool_bootstrap.py:322](src/fab_test/scripts/_analyzer_tool_bootstrap.py#L322)).
The only environmental gate it applies is `requires_platform`. The
fab-inspector release is a framework-dependent .NET build, so a present,
executable, correctly-versioned binary is still unrunnable without the .NET 8
runtime — and `doctor` says `ready: true`.

**Blast radius**: this is not pbir-only. `_BOOTSTRAPPED_ANALYZERS` is
`{bpa, pbir, a11y}` and all three route through the same probe. `a11y` already
demonstrates the gap from the other side: its wrapper resolves Node itself at
run time and fails with a remediation string ([invoke_pbir_a11y.py:304](src/fab_test/scripts/invoke_pbir_a11y.py#L304)),
a check `doctor` never performs. Fixing pbir alone leaves a11y lying the same way.

**Requirements**:
- Given an analyzer whose tool needs a language runtime that is not installed, `doctor` should report it not ready and exit non-zero
- Given that not-ready row, `doctor` should name the runtime and the version needed in the remediation, per the "tell the caller how to fix it" principle
- Given a runtime that is installed but older than the declared minimum, `doctor` should report not ready rather than ready
- Given an analyzer whose tool needs no runtime, `doctor` should behave exactly as it does today
- Given `doctor` runs on any machine, it should still never download anything

**Decided (discovery)**: the runtime requirement is declared in
`analyzers.json` beside `requires_platform`, as a `requires_runtime` key, and
`probe_executable` honors it. One fix covers pbir (.NET), a11y (Node), and bpa
if it proves to need one. Detection runs the runtime's own CLI
(`dotnet --list-runtimes`, `node --version`), which means `probe_executable`'s
contract is relaxed from "never spawns a subprocess" to "never downloads;
cheap local probes allowed" — and its docstring is corrected to say so rather
than being left to contradict the code.

---

## Defect 2 — the PBIR wrapper reports a pass when the tool never ran

`_classify_inspector_result` derives status "from findings alone -- no I/O"
([invoke_pbir_inspector.py:544](src/fab_test/scripts/invoke_pbir_inspector.py#L544)).
`proc.returncode` is accepted as a parameter but only ever interpolated into a
message string; it never influences status. So a binary that exits non-zero
having produced no output yields `findings == []`, which maps to
`status: "passed"`, message "PBIR Inspector passed with no findings".
`run_inspector` then hits `if not findings: return 0` — and the `proc.stderr`
print that would have surfaced "You must install .NET to run this application"
sits *below* that early return, so it never executes.

Three things must line up for the pass to be believable: the process succeeded,
it produced parseable output, and that output contained no violations. Today
only the third is checked.

**Requirements**:
- Given the inspector exits non-zero having produced no parseable output, the envelope should report an error status rather than passed
- Given that same run, the wrapper should exit non-zero so a pipeline fails the build
- Given that same run, the tool's stderr should reach the caller instead of being discarded
- Given the inspector exits non-zero but did produce findings, the existing findings-driven status should be preserved
- Given the inspector exits zero with no findings, it should still report passed exactly as today

**Precedent to follow**: [invoke_pql_test.py:229-300](src/fab_test/scripts/invoke_pql_test.py#L229-L300)
already distinguishes "asserted nothing because it could not connect" from
"asserted and passed". The distinction here is that a missing runtime is a
broken installation, not an optional condition — so this warrants `error`,
not `warning` as pql-test chose for an unreachable model.

---

## Version Bump

**Requirements**:
- Given both defects are fixed, the version in [src/fab_test/\_\_init\_\_.py](src/fab_test/__init__.py) should be `1.1.0.dev2`
- Given the bump, `fab-test --version` should report the new string through the installed console script

Single source of truth is `src/fab_test/__init__.py`; `pyproject.toml` reads it
dynamically and must not gain a static version.

---

## Documentation (Definition of Done)

Per vision.md, not done until all three callers are covered:
- Agent: `.github/skills/fab-test/` and the packaged mirror `src/fab_test/skill/`
- Human: README, `docs/QUICK-VALIDATION.md`, CHANGELOG
- Pipeline: prerequisite runtimes stated where the YAML snippet lives

---

## Verification

- New coverage in `tests/test_doctor.py` and `tests/test_invoke_pbir_inspector.py`
- Blast radius: exercise `doctor`, `doctor --format json`, `doctor --only a11y`,
  `doctor --local`, and a real `fab-test pbir` run through the installed console
  script — not just pytest against the source tree
- Full suite with coverage at the commit checkpoint; floor stays at 80%

---

## Decisions (Discovery)

| Question | Decision |
|----------|----------|
| Scope | Declarative `requires_runtime` across pbir, a11y, and bpa — not a pbir-only patch |
| Detection | Run the runtime CLI (`dotnet --list-runtimes`); relax and correct `probe_executable`'s no-subprocess docstring |
| Exit code | Missing runtime ⇒ not ready ⇒ `doctor` exits non-zero, same as a missing binary |
| Version | `1.1.0.dev2` |

**Accepted consequence**: pipelines running on a runner without the required
runtime will go from green to red. That is the defect becoming visible, not a
regression — but it belongs in the CHANGELOG as a behavior change so nobody
debugs it twice.

## Remaining Unknown — RESOLVED

Confirmed via the v3.4.0 release notes: "**.NET 8.0 dependency not included**" —
this is a framework-dependent build on all three platforms. `requires_runtime`
applies to `pbir` with a minimum of .NET 8.

---

## Implementation Notes

- `requires_runtime: {name, min_major}` added to `analyzers.json` for `pbir_inspector` (`dotnet`, min 8) and `pbir_a11y` (`node`, min 18). `tabular_editor_bpa` (Tabular Editor 2) does not need one — it runs on the .NET Framework Windows ships with.
- `_analyzer_tool_bootstrap.probe_executable` now runs a cheap, read-only runtime probe (`dotnet --list-runtimes` / `node --version`) ahead of local-candidate/cache resolution, so it applies whether the tool is on disk, cached, or would still need downloading. Its docstring is corrected: no longer "never spawns a subprocess."
- `invoke_pbir_inspector._classify_inspector_result` gained a `has_output` parameter: a nonzero exit with no parseable output now classifies as `error` (not `passed`), and `run_inspector`'s early return was changed from `if not findings: return 0` to `if outcome["status"] == "passed": return 0` so the tool's stderr and annotation are no longer skipped on that path.
- `tests/test_invoke_pbir_inspector.py` crossed its 900-line hard budget once the new tests landed; split `TestRunInspector`/`TestMain` into `tests/test_invoke_pbir_inspector_run.py` (process-outcome contract) per the module-budgets skill's behavior-seam rule.
- Verified live against this machine's real `dotnet`/`node`: `fab-test doctor` (real console script) reports both ready; with `PATH` cleared, `check_readiness` correctly reports both not-ready with the documented remediation.
- Full suite: 1688 passed, 0 failed, 3 skipped (plus the 4 new tests already counted in-suite); coverage 88%, well above the 80% floor; module-budget, complexity-budget, and skill-resource sync checks all pass.
- Version bumped to `1.1.0.dev2`; reinstalled editable and confirmed via `fab-test --version`.
