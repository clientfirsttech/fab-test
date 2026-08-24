# Playwright Embed Token Type Epic

**Status**: ✅ COMPLETED -- verified through `fab-test playwright --env DEV`
**Goal**: `fab-test playwright` renders a real report instead of timing out behind a 403,
and the test suite can no longer stay green while the embed config is wrong.

## Overview

Every `fab-test playwright` run against a real workspace fails with
`Report did not render within 60000ms`, and the captured `console.json` shows two 403s
against `api.powerbi.com/powerbi/globalservice/v201606/clusterdetails` and
`api.powerbi.com/metadata/cluster/clienttelemetryrouting`. The embed token was always
valid -- we were labelling it as the wrong *kind* of token, sending the Power BI embed
host down an authentication path an embed token cannot satisfy. Until this is fixed the
`playwright` analyzer cannot validate anything, which makes the whole subcommand
decorative: it reports failures that say nothing about the report under test.

---

## Root Cause

`src/fabric_ci_cd_dataops/scripts/playwright_validation/embed_config.py:29`:

```python
_TOKEN_TYPE_EMBED = 0  # models.TokenType.Embed
```

The comment says `Embed`; the value is `Aad`. Extracted from the shipped bundle
(`powerbi-client@2.23.1`, the same CDN build `tests/test_playwright_visual.py` injects):

```
TokenType[TokenType["Aad"]   = 0
TokenType[TokenType["Embed"] = 1
```

`Permissions.Read = 0` and `ViewMode.View = 0` are both correct. `tokenType` is the only
wrong constant in the block.

**Causal chain.** `generate_embed_token` mints a genuine embed token (it raises
`PowerBiApiError` on any non-200, and did not raise). We then pass that token to
`app.powerbi.com/reportEmbed` alongside `tokenType: 0`, which declares "this is an AAD
user token". The embed host therefore takes the AAD path and tries to resolve the
caller's home cluster via `globalservice/v201606/clusterdetails` and
`metadata/cluster/clienttelemetryrouting`. An embed token is not a valid bearer token
for those endpoints, so both return 403, the iframe falls back to its generic
"Something went wrong" page, and no typed `error` event ever reaches
`report.on('error', ...)` -- so the render/error race in `test_report_visual_renders`
simply runs out the clock.

Corroborating evidence that the 403s originate in the embed host rather than the client
library: neither endpoint appears anywhere in the client bundle (`grep -c` returns 0).
They are emitted by the iframe reacting to the token type we declared.

## Second Root Cause (found by running Task 3)

Fixing `tokenType` made the report render -- the 403s vanished and the screenshot showed
every visual drawn -- but the run still timed out. Two defects were stacked, and only
running the real entry point could have separated them.

`tests/test_playwright_visual.py` called `page.set_content(...)` to install the report
container. `set_content` performs `document.open()`/`write()`, which removes **every**
window event listener -- including the `WindowPostMessageProxy` listener the Power BI
service installs to receive events from the embed iframe. The iframe renders regardless
(it is self-contained), but no `rendered` or `error` ever reaches a handler, so the race
waits out the full budget on a report that is visibly fine.

Measured A/B against the real workspace, same report, same run:

| Variant | postMessages reaching the window | SDK events delivered |
|---------|----------------------------------|----------------------|
| With `set_content` (as shipped) | 6 | **0** -- race times out |
| Without `set_content` | 6 | **4** -- `loaded` @8.7s, `rendered` @12.5s |

Three conclusions, each of which replaced a guess:
- `report.on(...)` is fine. The reference repo's `document.body.addEventListener` style
  works too, but switching was unnecessary -- both fire once the listener survives.
- A real render takes ~12.5s, so the 60s budget was never implicated.
- The A/B ran without `--disable-web-security`, so that flag is not required either.

## Why the suite stayed green

Two independent gaps, both worth closing:

1. **The unit test mirrors the bug instead of guarding it.**
   `tests/test_playwright_embed_config.py:21` asserts `tokenType=0` -- it checks a
   hand-written constant against itself, with nothing tying either to the real library.
   It would have passed for any value we chose, including this wrong one.
2. **No verification through the real entry point.** The previous fix attempt shipped on
   a green unit suite alone. Unit tests here mock the browser and cannot exercise an
   embed, so they are structurally incapable of catching this class of defect. See
   principle 8 in `.github/agents/aidd.agent.md` and Blast Radius in `vision.md`.

Two earlier changes were also made on an unverified CORS hypothesis and did not fix
anything; both are re-decided on evidence in Task 4 rather than left in place.

---

## Task 1 -- Correct the token type constant

Set `_TOKEN_TYPE_EMBED = 1` and cite the enum inline so the next reader can check it
without downloading a bundle. Single caller (`invoke_playwright.py:505`), so the blast
radius is one code path.

**Requirements**:
- Given a built embed configuration, should set `tokenType` to `1` (`models.TokenType.Embed`)
- Given the constant block, should carry a comment naming the library and version the
  values were read from, so a future reader can re-verify

## Task 2 -- Make the embed-config test a guard, not a mirror

Two layers, because the offline contract tier cannot reach the CDN but the drift is
exactly what needs catching.

**Requirements**:
- Given the contract-tier suite running offline, should assert `tokenType == 1` and fail
  if it is ever set back to `0`
- Given the `integration` marker and network access, should fetch the pinned
  `powerbi-client` bundle, parse `TokenType`, `Permissions`, and `ViewMode` out of it,
  and assert all three of our constants match the library
- Given no network, should skip the integration check rather than fail, per the existing
  `integration` marker convention in `pytest.ini`

## Task 3 -- Verify through the real entry point (gates every claim below)

Approved to run against the live DEV workspace using `.fab-test/.env`. This is a
read-only report render; no artifact is written to the workspace.

```bash
fab-test playwright --env DEV
```

**Requirements**:
- Given a run against the real DEV workspace, should exit `0` with
  `analyzer-results/playwright/.../envelope.json` reporting `"status": "passed"`
- Given that same run, should produce a `console.json` with no 403s against
  `clusterdetails` or `clienttelemetryrouting` (or no `console.json` at all)
- Given the run's screenshot evidence, should show rendered report content rather than
  the "Something went wrong" panel
- Given any of the above failing, should stop and re-diagnose rather than adjust
  timeouts or flags to mask it -- no change below is claimed as verified until this
  task is green

**Outcome.** Task 1 alone was not sufficient -- it fixed rendering but exposed the
second defect above. With both fixed:

```
Playwright visual validation passed: 1 cases (1 passed in 17.31s)
  ✅  SampleModel-PQLAssert  — no findings
```

`envelope.json` reports `"status": "passed"`, zero findings, and no 403 against
`clusterdetails` or `clienttelemetryrouting`. One benign 400 remains on
`conceptualschema?userPreferredLocale=` (empty locale query parameter); the report
renders and passes, so it is console noise rather than a failure, and is left alone
rather than chased.

The reference implementation's two other divergences -- constructing a fresh
`pbi.service.Service` instead of the `window.powerbi` singleton, and listening on
`document.body` instead of `report.on(...)` -- were **not** needed once the listener
survives, and so were not adopted. Both were candidate guesses; the A/B retired them.

## Task 4 -- Re-decide the two unverified changes on evidence

Both landed in `01bcb11` on the disproven CORS hypothesis. Neither is kept by default.

**Requirements**:
- Given a passing run from Task 3, should re-run with `--disable-web-security` removed;
  passing without it should revert the launch-args fixture entirely, since a
  browser-security flag must not persist on a disproven rationale
- Given removal demonstrably breaks the run, should keep the flag and record the
  observed failure in the fixture docstring as its justification
- Given a passing run, should measure actual render time and set
  `PLAYWRIGHT_TIMEOUT_SECONDS` from that measurement plus headroom, rather than from the
  earlier guess of 180s
- Given any change to the render-wait budget, should keep the outer per-artifact
  subprocess timeout (`_DEFAULT_SUBPROCESS_TIMEOUT`) above it, so the wrapper is never
  killed before its own wait elapses

**Outcome: both reverted.** The A/B ran clean without `--disable-web-security`, so the
launch-args fixture is gone -- a browser-security flag does not stay in on a disproven
rationale. Measured render is ~12.5s against a 60s budget (4.8x headroom) and a 17.3s
end-to-end run against the 120s subprocess timeout, so both timeouts return to their
original values, along with every doc, schema, and test reference that moved with them.
The net diff of this epic is therefore the two real fixes plus the guards, not the six
files the wrong diagnosis had touched.

## Task 5 -- Keep the timeout diagnostic

`_capture_embed_error_details` is kept regardless of the outcome above: it is what turns
a bare "did not render within Xms" into a message naming the real cause, and it is the
reason this class of failure should take one run to diagnose instead of three.

**Requirements**:
- Given a render timeout with Power BI's error panel present, should fold the panel text
  into the failure message and write `embed_error_details.txt` beside the screenshot
- Given a render timeout with no panel present, should fall back to the plain timeout
  message without inventing evidence

## Task 6 -- Correct the record

`01bcb11` is still local and unpushed, so this is a clean amend rather than a revert
commit on top of a wrong one.

**Requirements**:
- Given the superseded `tasks/playwright-render-diagnostics-epic.md`, should be replaced
  by this epic so the archived history does not preserve the wrong diagnosis as fact
- Given `01bcb11`'s commit message attributing the failure to Chromium's same-origin
  policy, should be amended to name the real cause
- Given the epic completes, should archive to
  `tasks/archive/2026-08-24-playwright-embed-token-type.md`

---

## Definition of Done

Per `vision.md`, all three callers documented, plus the verification this epic exists to
enforce:

| Caller | Deliverable |
|--------|-------------|
| **AI agent** | `.github/skills/fab-test/SKILL.md` reflects any changed timeout default |
| **Human** | README/docs updated if a default or flag changes |
| **Pipeline** | No YAML change expected; confirm none is needed |
| **Verification** | Task 3 green through `fab-test playwright --env DEV`, not the unit suite alone |

Full suite at the commit checkpoint, coverage at or above the 80% floor, `ruff check`
clean. The six pre-existing failures unrelated to this work (telemetry config in
`fab-test.yml`) stay out of scope and are confirmed pre-existing by stashing.
