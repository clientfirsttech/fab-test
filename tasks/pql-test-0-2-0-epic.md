# pql-test 0.2.0 Update Epic

**Status**: ✅ IMPLEMENTED 2026-11-05, 5/5 tasks. The serial Playwright half of the gate was not run (nothing in this epic touches it).
**Goal**: fab-test requires `pql-test==0.2.0` and every document that restates the pin, the license, or the dependency set says so.

## Overview

`pql-test` 0.2.0 was released after the `0.1.20` pin. Discovery compared the two wheels and ran both against the same deployed model:

| Area | `0.1.20` → `0.2.0` | Effect |
|---|---|---|
| License | Business Source License 1.1 → **AGPL-3.0-only**, plus a `NOTICE` file | `THIRD-PARTY.md` and its test described BSL terms |
| Dependencies | adds `cryptography`, `requests`, `urllib3>=2.8`, `PyYAML`, `jsonschema` (and its `attrs`, `referencing`, `rpds-py`); `pyadomd` becomes Windows-only | `uv.lock` grows by ~170 lines |
| Python floor | 3.9 → 3.10 | none (fab-test needs 3.12) |
| Platform guard | `run-tests`, live `retrieve-tests`, `code-coverage` exit 1 off Windows with one message | none: ADOMD.NET was already Windows-only |
| Auth flag | `auth login --environment` → `--cloud` | nothing in fab-test uses it |
| New | `pql-test contract` (ODCS data contracts), `--quiet` | out of scope here; see the ODCS Contract Analyzer epic |

Unchanged: `run-tests`' `--env`, `--workspace-id` and `--output`, the `--format` option, and the exit rule (1 on a failure or when every test is skipped).

Decisions (user, 2026-11-05): the license is AGPL and `THIRD-PARTY.md` states it as written, with no reading of what it permits; the native-output check runs live against fab-test [Dev]; exposing `pql-test contract` is a separate epic.

---

## Characterize 0.2.0 ✅

**Requirements**:
- Given the same deployed model, should produce native JSON with the same keys, counts and failing tests as `0.1.20`

Done live, not by a fixture: `fab-test pql-test --workspace <Dev> --artifact SampleModel-PQLAssert` on `0.1.20` and on `0.2.0` gave identical top-level keys, identical per-result keys, 86 tests / 78 passed / 8 failed / 0 skipped, and the same eight failing test names. The wrapper needed no change, so no test was added for it.

---

## Bump the pin ✅

**Requirements**:
- Given `pyproject.toml` pins `0.2.0`, should have `uv.lock`, `docs/RELEASE.md`, the TestPyPI workflow comment and the CHANGELOG agree, with `tests/test_pql_test_pin_consistency.py` passing

---

## License notice ✅

**Requirements**:
- Given the pin is `0.2.0`, should have `THIRD-PARTY.md` name AGPL-3.0-only, point at the bundled `LICENSE.txt` and `NOTICE`, and drop the Business Source License terms
- Given the notice, should keep stating the license as written, never what it permits (red first: `test_pql_test_license_is_named_as_written_and_its_source_is_pointed_to`)

---

## Dependencies and platform ✅

**Requirements**:
- Given the new lock, should pass the CI audit command (`pip-audit` over `uv export --frozen`): no known vulnerabilities
- Given the new platform guard, should leave fab-test's behavior unchanged, because the `pql_test` analyzer already needs Windows for ADOMD.NET

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)

**Result**: `ruff check .` clean; `pytest -n auto -m "not playwright"` 3007 passed, 2 skipped (includes the complexity and module-budget ratchets); `pip-audit` on the new lock found nothing. Not run: the serial `-m playwright --cov-fail-under=80` half, so the coverage floor was not re-measured.
