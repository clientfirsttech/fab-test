# Feature Flags Epic

**Status**: ✅ IMPLEMENTED 2026-10-06 (`_feature_flags.py`, `tests/test_feature_flags.py`)
**Goal**: Unreleased analyzers (`data-agent`, `sqldb-test`) can merge to `dev` switched off, so Playwright and RDL changes ship from `dev` to `main` without exposing half-built commands.

## Overview

WHY: `dev` now carries work for two epics that are not ready to release: the [Data Agent Testing epic](data-agent-testing-epic.md) (the promptfoo tool seam is implemented: `data_agent` in `analyzers.json`, `_BOOTSTRAPPED_ANALYZERS`, and the npm bootstrap) and the [SQL Database T-TEST epic](sqldb-t-test-epic.md) (planned). The same branch carries Playwright workspace-name resolution and RDL fixture changes that should ship now. Without a switch, releasing one means releasing all, or holding work back on long-lived branches.

`HIDDEN_ANALYZERS` (`fab_test_registry.py`) is not that switch. By design it is a visibility state, not a removal: a hidden analyzer stays fully invocable, aliases included. A feature flag has the opposite contract: while it is off, the command does not exist, its tool is never resolved or installed, and no bundle runs it.

**Decisions**:

1. ✅ Flags are read from **environment variables only**: `FAB_TEST_ENABLE_<NAME>=1` (e.g. `FAB_TEST_ENABLE_DATA_AGENT`, `FAB_TEST_ENABLE_SQLDB_TEST`). Not `fab-test.yml`: the parser is built before the config file loads, and an env var is easy to set in CI and on a dev machine.
2. ✅ A disabled analyzer is registered as a **stub subcommand** that exits `2` with `<name> is not enabled in this release` plus a hint naming the env var. The stub accepts and ignores any arguments, runs nothing, resolves no tool, and is hidden from the advertised surface the way `pql_lint` is, so `--help` stays byte-identical to `main`. A clear message is better than an unknown-command error or a "did you mean" pointing at a different analyzer.
3. ✅ Flags are **default off, listed in one table**, and each is **deleted** when its feature ships. Deleting the entry is what enables it, because names without a flag are always enabled, so there is no separate "flip to `True`" step. A flag never outlives its epic, and a test fails if any default is `True`.
4. ✅ Names not in the flag table are always enabled, so every existing analyzer is unaffected.

---

## Flag Module

A single source of truth: `src/fab_test/scripts/_feature_flags.py`.

```python
# Unreleased analyzers, off by default. FAB_TEST_ENABLE_<NAME>=1 turns one on.
_FEATURES: dict[str, bool] = {"data_agent": False, "sqldb_test": False}

def is_enabled(name: str) -> bool: ...
def disabled_analyzers() -> frozenset[str]: ...
def enable_hint(name: str) -> str: ...  # "set FAB_TEST_ENABLE_DATA_AGENT=1 to enable"
```

**Requirements**:
- Given a name in `_FEATURES` and no env var, should return that name's default (`False`)
- Given `FAB_TEST_ENABLE_<NAME>` set to `1`, `true`, or `yes` (case-insensitive), should return `True`; given any other value, should return `False`
- Given a name not in `_FEATURES`, should return `True`
- Given registry keys and CLI spellings differ (`data_agent` / `data-agent`, `sqldb_test` / `sqldb-test`), should key flags by registry key and derive the env var name from it

---

## Gate The Surfaces

Every surface that enumerates analyzers filters through `disabled_analyzers()`, so no surface can drift.

| Surface | Location | Change |
|---|---|---|
| Subcommand | `fab_test_parser.py` `build_parser`, after the `_SUBPARSER_BUILDERS` loop | `add_disabled_stubs(subs)` registers each disabled feature's spellings with no `help` (hidden like pql-lint). `argparse.REMAINDER` cannot swallow option-shaped arguments, so the stub is a parser subclass whose `parse_known_args` exits `2` with the message |
| Advertised list | `fab_test_parser.py` `accepted_subcommands` / `advertised_subcommands` | Exclude stub spellings, so they never appear in `--help` or "did you mean" suggestions |
| Dispatch | none needed | The stub exits during argument parsing, before config load, target resolution, credentials, or telemetry, and that also covers `fab-test help <name>` |
| Registry | `ANALYZER_REGISTRY`, `visible_analyzers()`, `_suffix_to_analyzers()` | Exclude disabled analyzers |
| Tool bootstrap | `resolve_tool`, readiness, and the other `_BOOTSTRAPPED_ANALYZERS` checks | Treat a disabled analyzer as having no tool: promptfoo is never resolved or installed |
| Bundles | `load_fab_test_all_analyzers` (`fab_test_all` in `analyzers.json`) | Filter at load time. `_LOCAL_ANALYZERS` is a fixed tuple with no flagged names; data-agent and sqldb-test never join `local` (their epics' decision 8) |
| Admin | `doctor`, `list`, `explain` (`fab_test_admin.py`) | Inherit the filter via `visible_analyzers()`; `doctor --analyzer data_agent` exits `2` with the not-enabled message |
| Skill content | `src/fab_test/skill/` | Must not advertise a disabled command |

Out of scope: `tools/check_tool_updates.py` is dev-only and keeps tracking promptfoo's version. The promptfoo row in THIRD-PARTY.md stays, since listing a notice for a tool that is never installed does no harm.

**Requirements**:
- Given a flag is off, should exit `2` from `fab-test data-agent` / `fab-test sqldb-test` (and aliases such as `agent`) with `<name> is not enabled in this release` and the enable hint, whatever arguments follow (including `--help` and `--format json`)
- Given a flag is off and `--format json`, should still print the plain message to stderr and exit `2`, never a partial envelope
- Given a flag is off, should write no results folder, open no telemetry, and read no credentials
- Given a flag is off, should omit the analyzer from `--help`, `list`, `doctor`, `explain`, `all`, `local`, and artifact-type suggestions
- Given a flag is off, should never resolve, install, or download the analyzer's tool
- Given a flag is on, should register the real builder instead of the stub and behave exactly as if the flag module did not exist
- Given a planned epic whose real builder does not exist yet (`sqldb-test`), should register the stub only, so the name is reserved and the message is in place before any code lands
- Given the epics that add these commands, should register their builders through `is_enabled` from the start (recorded in each epic's registration section)

---

## Tests

**Requirements**:
- Given `tests/test_feature_flags.py`, should parametrize over `_FEATURES` and assert, with the default and with the env var set (`monkeypatch.setenv`), every row of the surface table above
- Given the existing tests that assume `data_agent` is bootstrapped (`test_check_tool_updates.py`, `test_pbir_a11y_tool_bootstrap.py`), should set the flag on explicitly
- Given all flags at their defaults, should produce `fab-test --help` output byte-identical to `main`, so the release diff shows only Playwright and RDL changes
- Given any flag whose default is `True`, should fail a test, since a released feature's entry is deleted instead (decision 3)

---

## Rollout

1. Land the flag module, the gating, and the tests on `dev`.
2. Commit the data-agent promptfoo seam (flag off) **separately** from the Playwright workspace-name changes (`fab_test_execution.py`, `invoke_playwright.py`, `test_target_workspace.py`), so each can be reviewed and reverted on its own.
3. Release Playwright and RDL from `dev` to `main`.
4. When an epic is ready, delete its rows from `_FEATURES` and `FEATURE_SPELLINGS` in the release commit.

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
