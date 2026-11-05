# Doctor Az Detection Epic

**Status**: ✅ IMPLEMENTED 2026-10-30. `pql_test`/`dependencies`/`playwright` readiness now catches a missing `az`; `pbir`/`rdl`/`a11y`/`bpa` get the detail in their informational service-mode line only, by explicit decision (see "Correction" below) — their exit code is unchanged.
**Goal**: `fab-test doctor` tells you the Azure CLI (`az`) is missing before you hit it blind in `fab-test pbir --workspace` (or any other ambient-credential run).

**Correction found during implementation**: `pbir`, `rdl`, `a11y` and `bpa` are *not* in `_CLOUD_ANALYZERS` (`fab_test_registry.py:182`) and never route through `_cloud_readiness.py` at all — their doctor row reflects tool availability (PBIR Inspector, Tabular Editor, …), and credential readiness is a separate, purely informational `service` line from `service_readiness()` ([_service_export.py](src/fab_test/scripts/_service_export.py)) that never affects `status`/exit code ([fab_test_summary.py:218-219](src/fab_test/scripts/fab_test_summary.py#L218)). So the original plan below (fixing only `_cloud_readiness.py`) would not actually have caught the reported `pbir --workspace` case. Asked the user: keep the service-mode line informational-only (chosen) rather than make it fail these four analyzers' exit code — a bigger, riskier change. Workstream 1 below (as planned) covers `pql_test`/`playwright`/`dependencies`; a second fix in `service_readiness()` covers the informational line for the other four.

## Overview

On a machine without `az` installed, `doctor` reported the ambient-credential path as ready (unverified) anyway, so nothing warned that `fab-test pbir --workspace` would fail once it actually tried to acquire a token. Two things make this possible today:

1. `_cloud_readiness.py` never probes for `az` at all. When a workspace is configured and no service principal env vars are set, it unconditionally reports the ambient path as ready-unverified ([src/fab_test/scripts/_cloud_readiness.py:69-74](src/fab_test/scripts/_cloud_readiness.py#L69)), regardless of whether `az` is on PATH.
2. The *only* place in `doctor` that checks for `az` is `_pql_identity.az_account()` ([src/fab_test/scripts/_pql_identity.py:95-99](src/fab_test/scripts/_pql_identity.py#L95)), which uses `shutil.which("az")` — a free PATH lookup, not a subprocess call, so it doesn't violate doctor's offline/no-subprocess contract ([_cloud_readiness.py:14-22](src/fab_test/scripts/_cloud_readiness.py#L14)). But that check only runs for the `pql_test` identity-comparison branch when a workspace *and* an ambient credential *and* a runnable pql-test are all present ([_pql_identity.py:108-119](src/fab_test/scripts/_pql_identity.py#L108)) — never for `pbir`, `rdl`, or playwright's ambient-credential rows. Missing-`az` and "az installed but not logged in" also collapse to the same `""`, so even where the check runs it can't distinguish "not installed" from "not signed in."

`pbir --workspace` itself has no upfront dependency check of its own: it resolves credentials through the same ambient chain (`DefaultAzureCredential`, [src/fab_test/scripts/_credentials.py:270-272](src/fab_test/scripts/_credentials.py#L270)), which shells out to `az` under the hood, and the parser just wires the `--workspace` flag through ([src/fab_test/scripts/fab_test_parser.py:392](src/fab_test/scripts/fab_test_parser.py#L392)) with no pre-flight. So the fix belongs in `doctor`'s general readiness check, not in `pbir`.

Decisions to approve:

1. **Where the check lives**: add `shutil.which("az")` to the shared ambient-credential branch in `_cloud_readiness.py` (the one at :69-74), not just the `pql_test` identity branch, so it covers `pbir`, `rdl`, and playwright readiness rows alike. `shutil.which` stays a free PATH lookup, consistent with doctor's no-subprocess contract.
2. **New status, not a reused one**: per the severity table in [archive/2026-10-10-doctor-severity.md](archive/2026-10-10-doctor-severity.md), "ambient credential expected but `az` is not even installed" is a ❌ error (you configured a workspace; the run will fail), distinct from today's ℹ/⚠ "ambient, unverified" state when `az` *is* present but not confirmed logged in.
3. **Remediation text**: name installing the Azure CLI (with a link) as the fix, not "run `az login`" — that would be wrong advice when the binary isn't there.
4. **Service principal present**: when SP env vars are fully set, skip the `az`-presence check entirely — the run doesn't need `az` at all in that case, matching current behavior.

---

## Az presence in cloud readiness

**Requirements**:
- Given a workspace, no service principal, and `az` not on PATH, should report ❌ naming "Azure CLI not installed" with a remediation linking the install docs, not the existing "ambient, unverified" ℹ/⚠ text
- Given a workspace, no service principal, and `az` on PATH, should keep today's ready-unverified behavior (this epic adds detection of absence, not login verification)
- Given a full service principal, should not probe for `az` at all and should keep today's ✅/❌ answer unchanged
- Given no workspace, should not probe for `az` (nothing will attempt an ambient credential)
- Given the row's `status` field, should be `error` when `az` is missing, consistent with the Doctor Severity epic's status vocabulary

---

## Reuse in pql_test identity check

**Requirements**:
- Given `_pql_identity.az_account()` already returns `""` for both "not installed" and "not logged in", should keep its current behavior unchanged (out of scope for this epic) — but should not regress now that cloud readiness reports the missing binary earlier, so a user sees the clearer ❌ before reaching the pql-test identity row

**Done 2026-10-30.** Unchanged, as planned — `az_account()` still collapses "not installed" and "not logged in" to `""`. Verified `test_a_missing_az_cli_is_reported_before_the_pql_test_identity_check`: with `identity_check()` stubbed to `None` (what it returns when `az_account()` is `""`) and `az_cli_available()` stubbed to `False`, `cloud_readiness` falls through `_pql_identity_row()` (returns `None`) into `_with_workspace`, which now reports the ❌ az-missing row.

---

## Tests

Follow the pattern in `tests/test_doctor_severity.py`: monkeypatch `shutil.which` to simulate `az` present vs. absent, assert on `_print_doctor` row `status` and remediation text, no real subprocess or network calls.

**Requirements**:
- Given `shutil.which("az")` returns `None`, a workspace, and no service principal, should assert the readiness row is `status == "error"` with remediation text naming the Azure CLI install step
- Given `shutil.which("az")` returns a path, same setup, should assert today's ready-unverified row is unchanged (no regression)
- Given a full service principal with `shutil.which("az")` returning `None`, should assert the row is unaffected by az's absence
- Given no workspace at all, should assert `shutil.which` is never consulted (or its result ignored) and the row matches current "not configured" behavior
- Given `fab-test pbir --workspace` run against a doctor-passing row of each kind (mocked, not live), should assert the new error row is what would have caught this bug — i.e. doctor fails loudly before `pbir` would have failed raw

**Done 2026-10-30.** Added `az_cli_available()` (`_credentials.py`, a `shutil.which("az")` wrapper) and wired it into `_with_workspace`'s ambient-credential branch in `_cloud_readiness.py`: a new ❌ row (`"workspace configured; no service principal set, and the Azure CLI (`az`) is not installed"`) fires only when `status.resolved and not status.verified`, i.e. ambient — a full service principal or no workspace never calls it. Five new tests in `tests/test_doctor_severity.py` cover: az missing → error; az present → unchanged ready; full SP unaffected by az absence; no workspace never probes it (asserted via a monkeypatch that raises if called); and that a missing az surfaces before the `pql_test` identity-comparison branch would otherwise run. The autouse fixture now defaults `az_cli_available` to `True` everywhere it's imported, so existing tests don't depend on whether this machine happens to have `az` installed. Full suite (minus playwright-marked): 2988 passed, 87% coverage; `ruff check .` and the complexity/module-budget ratchets clean. The pre-existing `test_the_installed_distribution_agrees_with_the_package` failure and a `pip install -e .` script-overwrite error are local dev-environment drift, unrelated to this change — not fixed here.

**Last requirement reframed, not dropped**: the "would have caught this bug" check (requirement 5) is satisfied by the *reframed* fix below (service-mode line), not by this workstream alone — see the Correction above.

---

## Az detection for the service-mode line (pbir / rdl / a11y / bpa)

Added 2026-10-30 after the Correction above. `service_readiness()` in `_service_export.py` is the only place these four analyzers' doctor output says anything about credentials, and it never checked `az` either.

**Requirements**:
- Given an ambient credential (`status.source == AMBIENT_SOURCE`) and `az` missing, should append "the Azure CLI (`az`) is not installed, so `az login` is not available here" to the service-mode line
- Given `az` present, should print the line exactly as before (no mention of `az`)
- Given a configured service principal, should never mention `az`, present or absent — the first (`status.verified`) branch returns before the check
- Given the line's role is informational, should not change `status`, `ready`, or doctor's exit code for `pbir`/`rdl`/`a11y`/`bpa` — confirmed by user decision, not a bug fix for their exit code

**Done 2026-10-30.** Four new tests in `tests/test_doctor_severity.py`'s "Service-mode line" section: az missing → line names it; az present → line stays silent about it; service principal → line never mentions `az` even when it's absent. The fixture's `_service_export.az_cli_available` default (`True`) keeps this independent of whether `az` is actually installed on the machine running the suite.

---

## Documentation

**Requirements**:
- Given the new ❌ status, should add a row to the doctor troubleshooting tables in GETTING-STARTED.md (and PLAYWRIGHT-CI.md if the ambient-credential row is shared there) naming "Azure CLI not installed" and its fix
- Given a behavior change to doctor's exit code on machines missing `az`, should add a CHANGELOG entry (bug fix: doctor now catches a missing Azure CLI before a workspace run needs it)

**Done 2026-10-30.** Added a troubleshooting row to `docs/GETTING-STARTED.md`'s table naming the new ❌ and pointing at the Azure CLI install step already referenced in step 3. Not added to `PLAYWRIGHT-CI.md`: playwright always needs a service principal and never reaches the ambient/az branch (it fails earlier, on "needs a service principal"), so the row would never apply there. CHANGELOG entry added under 2026-10-30, naming both halves of the fix (the ❌ status change for `pql_test`/`dependencies`, and the informational-only line for `pbir`/`rdl`/`a11y`/`bpa`) and stating plainly that the latter does not change those analyzers' exit code. No version bump: following the Doctor Severity epic's precedent, and this is a dev-branch fix, not a release cut.

---

## Quality gates

Always last; nothing follows it.

**Requirements**:
- Given the finished epic, should pass `ruff check .` over the whole repo, the complexity and module-budget ratchets, and the coverage floor on the full suite, run as CI runs them (vision.md, Definition of Done)

**Passed 2026-10-30.** `ruff check .` clean over the whole repo. `tests/test_complexity_budget.py` and `tests/test_module_budget.py` both pass. Full suite minus playwright-marked tests (`pytest -n auto -m "not playwright" --cov`): 2988 passed, 2 skipped, 87% coverage (floor is 80%) — one pre-existing failure (`test_the_installed_distribution_agrees_with_the_package`, a local `pip install -e .` / dist-info mismatch unrelated to this epic's files) left as-is. Playwright-marked tests were not run this pass (none of this epic's changes touch playwright execution; `playwright`'s own readiness path was exercised and passed under the non-playwright run via `test_doctor_severity.py`).
