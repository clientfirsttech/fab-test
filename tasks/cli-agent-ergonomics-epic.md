# CLI Agent Ergonomics Epic

**Status**: 📋 PLANNED
**Goal**: Make `fab-test` equally callable by a human at a prompt and by an AI agent parsing stdout.

## Overview
`fab-test` is a facade over Tabular Editor, PBIR Inspector, pql-test, pqlint, and Playwright, so the value it adds is a *uniform contract*: one way to discover what can run, one way to see whether the machine is ready, one shape of result, one meaning per exit code. Today that contract leaks — `--format json` prints human banners and child-process output on stdout before the JSON document, a missing tool exits `1` exactly like a real rule violation, and nothing tells a caller which analyzers are even runnable here without invoking them. A human recovers from all of this by reading the screen; an agent cannot. This epic closes those gaps without changing any analyzer behavior.

Tasks are ordered so each builds on the previous. Every task carries the narrow test command that validates it, per the troubleshooting constraint in [vision.md](../vision.md).

---

## 1. Add an Output Channel Helper ✅

Introduce one helper that decides where a line goes — stdout for machine payloads, stderr for everything a human reads — so no other task has to reason about it.

**Requirements**:
- Given `--format json`, then `narrate()` writes to stderr and only the final payload writer touches stdout.
- Given `--format text`, then `narrate()` writes to stdout exactly as `print` does today.
- Given `--quiet`, then `narrate()` suppresses the line in both formats while the summary and exit code are unchanged.
- Given the helper is unit-tested, then capturing stdout and stderr separately proves the routing for all three modes.

**Files**: `src/fabric_ci_cd_dataops/scripts/_cli_utils.py`, `fab_test.py`
**Tests**: `pytest tests/test_cli_utils.py`

---

## 2. Route CLI Narration Through the Helper ✅

Replace direct `print` calls in the CLI with the helper so banners, per-artifact progress, and warnings stop polluting stdout.

**Requirements**:
- Given `fab-test <any> --format json`, then no progress, banner, or warning line appears on stdout.
- Given `--format text`, then the output is byte-for-byte what it is today.
- Given a preflight failure message, then it is narrated rather than printed directly.

**Files**: `fab_test.py` (`_run_one_artifact`, `_run_analyzer`, `main`), `fab_test_summary.py`
**Tests**: `pytest -m fab_test tests/test_fab_test.py`

---

## 3. Capture Subprocess Output Under JSON ✅

Analyzer subprocesses currently inherit stdout, so their banners land in the middle of the JSON document. Capture and re-emit them.

**Requirements**:
- Given `--format json`, then analyzer subprocess stdout is captured and re-emitted on stderr rather than inherited.
- Given `--format json -v`, then the captured output is still shown on stderr and stdout stays a single valid document.
- Given `--format text`, then subprocess output streams as it does today with no added latency.
- Given a subprocess times out, then captured output produced before the timeout is still re-emitted.

**Files**: `fab_test.py` (`_run_one_artifact` subprocess call)
**Tests**: `pytest -m fab_test tests/test_fab_test.py -k json`

---

## 4. Propagate Output Mode to Wrapper Scripts ✅

The wrappers print their own emoji banners. Give them the same discipline through the existing environment-variable channel.

**Requirements**:
- Given `--format json`, then the subprocess environment carries an output-mode variable alongside `ANALYZER_VERBOSITY`.
- Given a wrapper sees that variable, then its human banners go to stderr and only its envelope write touches disk.
- Given the variable is absent, then wrapper output is unchanged for direct invocation.

**Files**: `invoke_tabular_editor_bpa.py`, `invoke_pbir_inspector.py`, `invoke_pql_test.py`, `invoke_pqlint.py`
**Tests**: `pytest -m analyzers`

---

## 5. Prove stdout Purity for Every Subcommand ✅

Lock the guarantee with a test that would have caught today's behavior.

**Requirements**:
- Given every subcommand invoked with `--format json`, then a test asserts stdout parses in one `json.loads` call.
- Given the same runs, then a test asserts stderr is non-empty so narration was not silently dropped.
- Given a new subcommand is added later, then the test enumerates subcommands from the parser so it fails until covered.

**Files**: `tests/test_fab_test.py`
**Tests**: `pytest -m fab_test tests/test_fab_test.py -k stdout`

---

## 6. Exit `127` for Missing Prerequisites ✅

Let a caller distinguish a machine that is not set up from an artifact that failed.

**Requirements**:
- Given a required external tool cannot be resolved, then the process exits `127` rather than `1`.
- Given the failure message, then it names the flag, environment variable, and config key that would fix it.
- Given error-level findings from a tool that did run, then the exit code stays `1`.
- Given an unsupported platform, then the exit code stays `126`.
- Given `fab-test --help`, then the epilog documents `127` alongside the existing codes.

**Files**: `fab_test_registry.py` (`preflight_error`), `fab_test.py` (epilog)
**Tests**: `pytest -m fab_test tests/test_fab_test.py -k exit_code`

---

## 7. Add a Readiness Probe ✅

Extract a check that answers "could this analyzer run?" without downloading anything or touching artifacts — the engine behind `doctor`.

**Requirements**:
- Given an analyzer name, then the probe returns ready state, the resolved path or credential source, a reason, and a remediation hint.
- Given a tool that would need downloading, then the probe reports what *would* be downloaded without downloading it.
- Given the probe runs, then no artifact is read and no subprocess is spawned.

**Files**: `fab_test_registry.py`, `_analyzer_tool_bootstrap.py`
**Tests**: `pytest -m fab_test tests/test_readiness.py`

---

## 8. Add `fab-test doctor` ✅

Surface the probe as the command a human or agent runs first.

**Requirements**:
- Given `fab-test doctor`, then every analyzer is listed with ready state, resolved source, and a one-line remediation when not ready.
- Given `--format json`, then one JSON document is emitted with stable keys (`analyzer`, `ready`, `reason`, `resolved_path`, `remediation`).
- Given `--analyzer bpa`, then only that analyzer is checked.
- Given at least one analyzer is ready, then the exit code is `0`; given none are, then it is non-zero.
- Given the JSON keys, then a test asserts them against a fixture so renames fail the build.

**Files**: `fab_test.py`, `fab_test_summary.py`
**Tests**: `pytest -m fab_test tests/test_doctor.py`

---

## 9. Add `fab-test list` ✅

Let a caller discover capability from the tool instead of the documentation.

**Requirements**:
- Given `fab-test list`, then every subcommand prints with its artifact glob, matched artifact count, and required external tool.
- Given `--format json`, then the same data is emitted as a single JSON document.
- Given a repository with no artifacts, then counts are `0` and the command still exits `0`.

**Files**: `fab_test.py`, `fab_test_registry.py`
**Tests**: `pytest -m fab_test tests/test_list_explain.py -k list`

---

## 10. Add `fab-test explain` ✅

Show the resolved command without running it, so a failing run can be diagnosed without a second execution.

**Requirements**:
- Given `fab-test explain bpa`, then the resolved subprocess command, tool path, rules path, and output path are printed without executing anything.
- Given `--format json`, then the same data is emitted as a single JSON document.
- Given an unknown analyzer name, then the CLI exits `2` and lists valid names.

**Files**: `fab_test.py`, `fab_test_registry.py`
**Tests**: `pytest -m fab_test tests/test_list_explain.py -k explain`

---

## 11. Write the Run Manifest

Emit one file per invocation so callers read a single path instead of globbing result directories.

**Requirements**:
- Given any analyzer run completes, then `analyzer-results/run.json` records `schema_version`, `fab_test_version`, the invoked command, per-artifact status, envelope paths, totals, and the final exit code.
- Given `--output-dir DIR`, then the manifest is written under `DIR`.
- Given the manifest is written, then no credential value appears anywhere in it.

**Files**: new `_run_manifest.py`, `fab_test.py`
**Tests**: `pytest -m fab_test tests/test_run_manifest.py`

---

## 12. Cover `all` and Abort Paths in the Manifest

A manifest that only appears on the happy path is a manifest an agent cannot rely on.

**Requirements**:
- Given `fab-test all`, then the manifest covers every analyzer in the run, not just the last.
- Given a run aborts on a preflight failure, then the manifest is still written with the failure reason and the `127` exit code.
- Given a subprocess timeout, then the manifest records the timeout status for that artifact.

**Files**: `fab_test.py` (`main`, `_run_analyzer`), `_run_manifest.py`
**Tests**: `pytest -m fab_test tests/test_run_manifest.py -k abort`

---

## 13. Canonicalize Subcommand Names

Remove the underscore/hyphen coin flip (`pql_test`, `pql_lint` vs `playwright-impact`).

**Requirements**:
- Given `fab-test --help`, then every subcommand displays in hyphenated form.
- Given an underscore form, then it still works and is accepted silently as an alias.
- Given `fab-test list --format json`, then each entry reports the canonical name and its aliases.
- Given result directories under `analyzer-results/`, then existing names are unchanged so historical results stay readable.

**Files**: `fab_test.py` (`_SUBCOMMAND_ALIASES`, parser), `fab_test_registry.py`
**Tests**: `pytest -m fab_test tests/test_fab_test.py -k alias`

---

## 14. Document for All Three Callers

Publish the contract for the agent, the human, and the pipeline together, per the documentation constraint in [vision.md](../vision.md).

**Requirements**:
- Given `.github/skills/fab-test/SKILL.md`, then it contains an "Agent contract" section listing exit codes, the JSON stdout guarantee, and the run manifest schema.
- Given the README, then the machine-readable workflow (`doctor` → `list` → run with `--format json` → read `run.json`) appears as a four-command example.
- Given a pipeline author, then a copy-pasteable workflow snippet shows `doctor` as a gate step and `run.json` as the artifact to upload.
- Given the docs are updated, then the `document` skill is used so README, QUICK-VALIDATION, SKILL.md, and the snippet stay in sync.

**Files**: `.github/skills/fab-test/SKILL.md`, `README.md`, `docs/QUICK-VALIDATION.md`
**Tests**: `pytest -m fab_test` (full epic sweep before commit)
