# Review Cleanup Epic

**Status**: 🚧 IN-PROGRESS (4/6)
**Goal**: Close the five findings from the 2026-08-21 review, three of which are debt created that same day.

## Overview

The review of the Artifact Targeting, Human-Readable Reports, and Complexity and Coverage epics found five things worth fixing. Three were introduced by those epics — a duplicated pair of helpers, an inverted dependency, and a lint exemption now covering code it was never written for. The other two are older or broader: a test-assertion habit that produced four vacuous tests in a single day, and two functions left over the statement budget.

None of it is user-visible. Every task here is structural or test-quality, so the bar is the same as the last refactor: the CLI's output and every envelope must be byte-identical afterwards, proved against a real run rather than inferred from a green suite.

**Why this is worth an epic rather than a cleanup commit.** Two of the findings are cases where the *record* was wrong, not just the code: a commit message claimed a deduplication that shipped as duplication, and a lint comment justifies an exemption for a file it does not describe. Those mislead the next reader more than the code does, so each task fixes the claim as well as the thing.

---

## 1. Delete the Duplicated Finding Helpers ✅

**Done (2026-08-21)**: the copies in `fab_test_summary` are gone and its callers import from `_analyzer_envelope`. `_test_status` gained a caller outside its module, so it became public — but **not** as `test_status`: pytest collects any importable name beginning with `test_`, so a test module importing it would have produced a phantom test failing on a missing `finding` fixture. Named `finding_status` instead, with a guard asserting no `test_*` name is exported from `_analyzer_envelope`.

A second guard asserts each helper has exactly one definition across `src/`, which is the drift this task existed to end.

**The earlier commit message overclaimed.** "Rather than write a second normalization, extracted the one that already existed" described the intent; what shipped copied two helpers and left the originals live. The code now matches the claim.

The renderer epic moved `normalize_findings` into `_analyzer_envelope.py` but **copied** the two helpers it needed instead of moving them. Both originals are still live.

| Original (still used) | Copy | Bodies |
|---|---|---|
| `fab_test_summary._is_pql_test_finding` (line 276) | `_analyzer_envelope.is_test_finding` | identical |
| `fab_test_summary._pql_test_status` (line 285) | `_analyzer_envelope._test_status` | identical |

`_build_pql_test_table` and `_format_findings` still call the copies in `fab_test_summary`. So "what counts as a pql-test finding" now has two definitions, which is the exact failure the extraction was meant to prevent.

**Requirements**:
- Given `fab_test_summary.py`, then `_is_pql_test_finding` and `_pql_test_status` are deleted and their callers import from `_analyzer_envelope`.
- Given `_analyzer_envelope._test_status`, then it is renamed to a public `test_status` if it now has a caller outside its module, or stays private if `normalize_findings` remains its only user.
- Given a search for either behavior, then exactly one definition of each is found.
- Given the terminal findings tables, then their output is unchanged — the copies were byte-identical, so nothing should move.
- Given the commit, then it states plainly that the earlier message overclaimed, so the record is corrected rather than quietly amended.

**Files**: `fab_test_summary.py`, `_analyzer_envelope.py`
**Tests**: `pytest -m fab_test tests/test_report_html.py` then the full suite

---

## 2. Break the Wrapper's Dependency on the Presentation Layer ✅

**Done (2026-08-21)**: new `_table_style.py` holds `TABLE_FORMAT` and `table_padding` and imports no sibling, so both the CLI and a wrapper can reach it without dragging the other along. Measured: `fab_test_registry` and `fab_test_summary` are gone from the BPA wrapper's import graph, and its cumulative import drops **363 ms → 316 ms**, about 48 ms per artifact spawn.

Chose a new module over the alternatives because both candidates were worse: leaving the constants in `fab_test_summary` is the problem, and duplicating them into each wrapper reintroduces task 1's failure in a new place.

**The layering guard found more than the task scoped.** `tests/test_module_layering.py` asserts no wrapper imports the CLI layer or a private name from another module — and immediately flagged `_severity_counts` and `_severity_rank`, imported privately by four modules and therefore public API in all but name. Renamed to `severity_counts` and `severity_rank`; 16 references across 4 files, mechanical. Pre-existing, but exactly the rule this task set.

[`invoke_tabular_editor_bpa.py:39-40`](../src/fabric_ci_cd_dataops/scripts/invoke_tabular_editor_bpa.py#L39) imports `_TABLE_FORMAT` and `table_padding` from `fab_test_summary`. Two distinct problems:

1. It imports a **private** name across a module boundary and aliases it public.
2. The wrapper runs as a *subprocess per artifact*. Importing `fab_test_summary` drags in `fab_test_registry`, and through it `_credentials`, `_desktop`, `_target`, and `_rule_overlay` — **measured at ~59 ms per spawn**, to obtain two formatting constants.

**Requirements**:
- Given the two constants, then they live in a module that both the summary and the wrappers can import without pulling in the analyzer registry.
- Given `invoke_tabular_editor_bpa.py`, then it imports no private name from another module.
- Given the wrapper's import graph, then `fab_test_registry` no longer appears in it, verified with `python -X importtime`.
- Given the rendered tables, then every one is unchanged — same format, same column widths.
- Given the new module, then it is not created merely to hold two constants if a simpler placement exists; state which was chosen and why.

**Files**: `invoke_tabular_editor_bpa.py`, `fab_test_summary.py`, possibly a new small module
**Tests**: `pytest -m bpa` then a real `fab-test all` compared against saved output

---

## 3. Retire the Blanket Lint Exemption on `fab_test.py` ✅

**Done (2026-08-21)**: removed from `per-file-ignores`, and the comment above the remaining two entries now says why it was wrong to be there — otherwise the next person re-adds it. Each of the three sites carries a `# noqa: BLE001 - boundary: ...` naming its boundary: git as optional context, telemetry never failing a run, and any credential failure becoming a reported status rather than a traceback.

`_git_command_output` was restructured rather than annotated. It previously ran the command *and* read the result inside one `try`, ending in a bare `pass` that `S110` flagged. Now only the call is guarded, the early return replaces the `pass`, and a comment states the case for silence: warning here would fire on every run outside a git checkout, which is a normal way to use `fab-test`, so the noise would train people to ignore it.

`pyproject.toml` grants `fab_test.py` a file-level `BLE001, S110` exemption under the comment *"Scanners deliberately swallow per-file errors so one bad file cannot abort a scan."* It is grouped with `scan_credentials.py` and `scan_entropy.py`, which are scanners. **`fab_test.py` is the CLI orchestrator; the justification does not describe it.**

Removing the exemption surfaces exactly four diagnostics across three sites:

```
fab_test.py:264:5   S110    try-except-pass detected
fab_test.py:264:12  BLE001  blind except (_git_command_output)
fab_test.py:427:12  BLE001  blind except (telemetry publish)
fab_test.py:2080:16 BLE001  blind except (_auth_status ambient verification)
```

Each is arguably correct behavior — the point is that a file-level ignore means the *next* one lands unexamined.

**Requirements**:
- Given `pyproject.toml`, then `fab_test.py` is removed from `per-file-ignores`.
- Given each of the three sites, then it carries a `# noqa: BLE001 - <which boundary>` naming the boundary, per the `aidd-python` constraint that a blind except belongs only at a process boundary.
- Given `_git_command_output`, then its silent `pass` either logs at debug level or carries a comment stating what is being swallowed and why silence is right — an `S110` suppression with no explanation is the weakest of the three.
- Given the lint gate, then it passes without the file-level exemption.
- Given the comment above the remaining entries, then it still accurately describes only the files it covers.

**Files**: `pyproject.toml`, `fab_test.py`
**Tests**: `ruff check src tests` then the full suite

---

## 4. Replace Vacuous Test Assertions ✅

**Done (2026-08-21) — and the finding was substantially overstated.** The review counted 17 broad assertions and inferred they were weak from their shape. Mutation testing each one says otherwise: **only one was genuinely vacuous.**

| Mutation | Result |
|---|---|
| Type filter disabled in `discover_artifacts` | caught |
| `auth status` subcommand renamed away | caught |
| `--report` flag renamed | caught |
| Scope dropped from the dry-run line | caught |
| `--env` help text reworded | caught |
| Colour injected into the `--format json` payload | caught |
| **Desktop preflight message reworded** | **missed** |

The real one: `test_cli_desktop_target_without_an_instance_exits_127` asserted `"Desktop" in stdout + stderr`, which held even when the failure message changed — the word also appears in the remediation line. It now asserts the diagnosis, the artifact name, and the way out, and the same mutation is caught.

Also fixed a docstring that described a narrowing the code never received: it claimed to assert on the per-analyzer plans while the assertions still matched whole stdout. The assertions turned out to be sound, so the docstring was corrected rather than the test.

**The lesson is not the one the review drew.** Shape is a poor proxy for weakness — a broad assertion over a small, controlled output is often fine, and the way to know is to break the behavior and watch. The three earlier vacuous tests were caught by reading; a mutation pass would have caught them faster and with less argument.

Seventeen assertions across the new test files match a substring against an entire captured stdout. That shape produced **four tests that passed for the wrong reason** in one day: `Sales.Report` matching a stem, `*.Report` matching a glob text, and a bare `` `main` `` matching `deploy.py`'s function. Three of the four were only noticed by reading them.

| File | Broad assertions |
|---|---|
| `tests/test_auth.py` | 6 |
| `tests/test_target_discovery.py` | 3 |
| `tests/test_hidden_analyzers.py` | 3 |
| `tests/test_color.py` | 2 |
| `tests/test_report_generation.py` | 2 |
| `tests/test_target_reporting.py` | 1 |

**Requirements**:
- Given each assertion, then it targets a specific line, a parsed structure, or an exit code rather than the whole capture — or carries a comment explaining why the broad match is safe here.
- Given `tests/test_auth.py:301` (`assert "status" in result.stdout`), then it is replaced: "status" is near-unfalsifiable in help output.
- Given each rewritten test, then it is confirmed to fail when the behavior it covers is deliberately broken — a test that cannot fail is not yet a test.
- Given the suite afterwards, then the same number of tests pass and none was deleted to avoid fixing it.
- Given the exercise, then any assertion found to be genuinely vacuous is reported, not silently repaired.

**Files**: the six test files above
**Tests**: `pytest -m fab_test` then the full suite

---

## 5. Bring the Two Wrappers Under the Statement Budget

`run_bpa` (60) and `run_pql_test` (62) left `C901` and `PLR0912` in the last epic but still exceed the 50-statement budget in `[tool.ruff.lint.pylint]`. The remaining bulk in each is the verbosity narration and the final write-and-log branches.

Deferred last time because each further split is another chance to change behavior and the value was judged lower than the risk. It is worth doing now only because tasks 1–3 already require touching and re-verifying these files.

**Requirements**:
- Given both functions, then each is under 50 statements.
- Given the narration, then it is extracted such that a wrapper's banner can be asserted without running the analyzer.
- Given every envelope, then it is unchanged key-for-key against a real Tabular Editor and pql-test run, timing fields excepted.
- Given the complexity ceiling in `tests/test_complexity_budget.py`, then it is lowered to the new count, keeping the ratchet honest.
- Given the risk, then this task is abandoned rather than forced if a split cannot be made without changing an envelope — and the reason recorded.

**Files**: `invoke_tabular_editor_bpa.py`, `invoke_pql_test.py`, `tests/test_complexity_budget.py`
**Tests**: `pytest -m bpa` then `pytest -m pql_test`, then a real run of each

---

## 6. Document — Or State That Nothing Needs It

**Requirements**:
- Given the epic, then whether any of the three callers needs a doc change is decided explicitly rather than skipped.
- Given that no CLI behavior changes, then the `fab-test` skill, README, and QUICK-VALIDATION are confirmed unchanged, and that confirmation is written down — an untouched skill after a diff otherwise reads as an oversight.
- Given `aidd-python`'s rule about blind excepts, then task 3's outcome is consistent with it, so the skill and the code agree.

**Files**: possibly none
**Tests**: full suite with coverage

---

## Deferred — Three Pre-existing Smells

Named so they are not rediscovered as new. The TRX is parsed twice per BPA run: `_parse_vstest_counters(raw_text)` re-parses a document the caller already parsed. Three separate `_truncate` implementations exist across `fab_test_summary`, `invoke_pbir_inspector`, and `invoke_tabular_editor_bpa`. And `ET.fromstring` is used on TE2 output under an `S314` exemption — defensible while the input is a locally-run tool's output, though `defusedxml` would end the argument. All three predate this session's work and none is a correctness risk today.

## Note — Behavior Must Not Change

Every task here is structural or test-only. The suite is the safety net, but it is not sufficient on its own: three real bugs this session were caught by running the CLI and comparing output, not by the suite. So each task that touches rendering or an envelope carries a real-run comparison in its test line, and Core Principle 8 applies throughout.
