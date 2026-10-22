# Core Module Split Epic

**Status**: 🔄 IN PROGRESS (3/5 tasks)
**Goal**: `fab_test_registry.py`, `fab_test_execution.py` and `fab_test_summary.py` each fall under the 800-line hard budget, and their `test_module_budget.py` exemptions are deleted.

## Overview

Every change to discovery, commands, readiness, or summaries lands in one of three modules that are 919–1,038 lines against an 800-line hard budget, so each small fix grows a file that is already exempted, and an agent asked to change one behavior loads a thousand lines to do it. Each module has a seam the code already respects; moving along it changes no behavior. Tests monkeypatch several of these names at their current paths (`fab_test_admin._check_readiness`, `fab_test_registry.*`), so each move keeps re-exports only where a caller outside the package needs them, and updates the tests otherwise.

---

## Split command builders out of the registry ✅

`build_*_command`, the rules-path resolvers, `_COMMAND_BUILDERS` and `build_command` move to `_command_builders.py`.

**Requirements**:
- Given the move, should leave `fab_test_registry.py` holding the registry tables, scopes, and discovery only
- Given every analyzer, should build a byte-identical command before and after (`explain --format json` for each)

---

## Split readiness out of the registry ✅

`resolve_tool`, `preflight_error`, `check_readiness` and `_cloud_readiness` move to `_readiness.py`.

**Requirements**:
- Given `doctor`, `doctor --local`, `explain` and a run with a missing tool, should print the same output and exit codes as before

---

## Split target resolution out of execution ✅

Workspace and target resolution (`_manifest_target` through `_discover_for`) moves to `_run_targets.py`.

**Requirements**:
- Given a local run, `--workspace NAME --artifact X`, and a `WS.Workspace/NAME` target, should write the same `run.json` target and dry-run plan as before

---

## Split the admin printers out of the summary

`_print_list`, `_print_auth_status`, `_print_doctor`, `_print_config_show` and `_print_local_doctor` move to `_admin_output.py`.

**Requirements**:
- Given `list`, `auth status`, `doctor` and `config --show`, in text and JSON, should print the same output as before

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets with the three exemptions removed, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)
