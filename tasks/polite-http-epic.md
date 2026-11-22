# Polite HTTP Epic

**Status**: ✅ IMPLEMENTED 2026-11-22 on `feature/data-agent-testing` (the provider exists only there); all eight decisions accepted 2026-11-22. Open before archiving: the polite-client eval rerun after the skill's new Scope constraint, and the Playwright half of the gates once Fabric stops blocking the service principal.
**Goal**: every HTTP call fab-test makes treats a throttled or failing service the way a considerate client would: it waits as long as the server asks and no less, retries in one layer only, stops when retrying can't help, and tells its caller what happened and when to come back. A project skill, `aidd-polite-http`, holds that bar at planning time and in review.

**Evidence** (`fab-test data-agent --workspace fab-test-working-area`, 2026-11-22):

- Fabric answered the first agent call (`POST …/assistants`) with **429 `RequestBlocked`**, `Retry-After: 16`, `isRetriable: true`, "blocked by the upstream service until 16:23:38 UTC". The workspace API answered normally, so the block covered the agent endpoint only.
- **The block slides, and `Retry-After` understates it.** Every later request was answered with a block ending at that request's time + 120 s (`Retry-After: 120`, at 16:30:58, 16:32:00 and 16:33:03, each 60 s after the last). A wait of 202 s with no requests, past the stated end of 16:35:02, still drew a new block at 16:36:25 (until 16:38:24). So waiting exactly `Retry-After` and retrying does not clear it, and whether early retries extend it, or something upstream (capacity throttling) holds it, is not yet known.
- The provider ignores `Retry-After`. `_call_api` makes 4 attempts 2 s apart (`max_retries: 3`, `retry_delay: 2`), then returns the service's body as raw JSON (`HTTP 429: {"errorCode":"RequestBlocked",…}`), not a sentence naming the cause and when to come back.
- **Nested retries.** promptfoo 0.124's scheduler sees "429" in that error and calls the provider again (`maxRetries: 3`, 1 s / 2 s / 4 s backoff, `Retry-After` honored only from response metadata the provider doesn't send). Up to 16 requests per question while blocked; the run showed the same question three times as `1/7 failed`, `2/7 failed` and `3/7 failed`, so the progress count also miscounts retries as questions.
- The wrapper's subprocess timeout (198 s) then killed promptfoo, and the person saw the raw command line (`Command '['C:\\Program Files\\nodejs\\node.EXE', …]' timed out after 198.0 seconds`), not "Fabric is throttling this agent". The report had no per-question detail.

**Non-throttling failures** (the provider with a stubbed `_urlopen`, no network, 2026-11-22):

- **400 and 404 are retried 4 times** before they are reported. Neither can succeed on a retry, so a mistyped agent URL or a deleted agent costs 4 requests and ~6 s per question, then promptfoo's grading.
- **500 is retried 4 times by the provider**, and promptfoo's scheduler also retries any error whose text contains `502`, `503`, `504`, `timeout`, `network` or `ECONNREFUSED`. So 5xx and timeouts get nested retries too, not only 429.
- **A DNS failure is retried 4 times** and reported as `<urlopen error getaddrinfo failed>`: no host, no remedy. A TLS-inspecting proxy's certificate failure looks the same; the open standalone task "A failed tool download is a traceback" is that case in `_analyzer_tool_bootstrap.py`.
- Already polite and kept: 401 refreshes the token once, 403 and `isRetriable: false` are final at once with remediation, a redirect is refused rather than followed with a token, and a turn posted to a shared conversation is never re-asked.
- What a `RequestBlocked` block is (answered by the audit from Microsoft's [Throttling in Microsoft Fabric](https://learn.microsoft.com/rest/api/fabric/articles/throttling)): the **caller identity's** request quota, a fixed 60 s window shared by every Fabric API and every process using that service principal, plus per-API limits. Capacity overload is a different 429, `CapacityLimitExceeded`, with no `Retry-After` and a different remedy (the Capacity Metrics app). A block that outlived 202 s of silence points at something else spending the same service principal's quota; it was not the capacity.

**Decisions** (proposed and accepted 2026-11-22):

1. **A project skill, `.github/skills/aidd-polite-http/`, with `/polite-http plan` and `/polite-http review`**, shaped like `aidd-command-grammar`. Not a `references/http.md` inside `aidd-polite-review`: that skill is read-only and reviews what a caller reads, while this one sets a bar for code at planning time and checks every diff that adds or changes an HTTP call. It cites `aidd-polite-review`'s principles (Quiet about its own problems, Keeps me informed, Errors are design failures) and vision.md's "Tell the caller how to fix it", rather than restating them.
2. **Wired through the router**: a Pre-Flight rule in `aidd-workflow`, mirrored in `aidd.agent.md`: (task plans, adds, reviews, or changes code that makes an HTTP request, or wraps a tool that does) => load `aidd-polite-http`. Findings join the review at `aidd-review`'s levels.
3. **One retry layer.** Where fab-test drives a tool that retries (promptfoo), the layer that sees the response headers owns retries, and the other layer is told not to retry (the provider reports `handlesOwnRetries`, or promptfoo's `maxRetries: 0`). Retries that multiply across layers are a blocking finding.
4. **`Retry-After` is a floor.** Seconds or an HTTP date are both parsed. No request goes to that endpoint before the floor passes. `Retry-After` is the least the server wants, not a promise that the next try succeeds. A `RequestBlocked` block stops the run's calls to that endpoint, not just the one call: one probe after the wait, then the rest of the run's questions are reported as not asked. When the wait would outlast the run's remaining time, fail at once and give the time to come back, rather than spending the budget waiting.
5. **Every failure has a class, not just every status.** HTTP: 400, 404, 405, 409, 410, 413 and 422 final at once, with the service's message; 401 refresh the token once, then final; 403 final, with the access to grant; 408, 429, 500, 502, 503 and 504 retryable with capped, jittered exponential backoff and a bounded attempt count; `isRetriable` in the body overrides the status either way. Below HTTP: a DNS failure and a TLS certificate failure are final (name the host, and for TLS the proxy or `SSL_CERT_FILE` fix); connection refused, connection reset and a socket timeout are retryable. Above HTTP: a 2xx whose body isn't the expected JSON, and a long-running operation or agent run that ends `failed` or `cancelled`, are final, with what came back. A non-idempotent request that may already have taken effect is never retried blind (the Data Agent conversation rule, `_answer_posted_turn`, already does this).
6. **The caller hears the cause, once, in its terms**: the human gets a sentence, not a JSON body or a Python repr: the host, the service's `errorCode` and message, the block's end time when there is one, and what to do; the pipeline gets the same text in the envelope `message` with exit code 1 unchanged; the agent gets a machine-readable `retry_after` (UTC) in the envelope beside the message. A raw subprocess command line is never the message.
7. **A shared helper only where two call sites need it.** The audit (task 4) decides. If more than one urllib client needs classification, `Retry-After` parsing and backoff, they share one small module; the `requests`-based clients adopt it through a retry adapter, not a rewrite. **Settled by the audit 2026-11-22:** three urllib sites (the provider, `_analyzer_tool_bootstrap`, `xmla_roles`) and three `requests` sites need it, so `_http_policy.py` holds the pure parts (classify, `Retry-After`, backoff, the caller's sentence); the provider adopts it here and the rest through the two standalone tasks the audit filed.
8. **Data Agent is the first adopter**, in this epic rather than the Data Agent epic, because it supplied the evidence and is still behind `FAB_TEST_ENABLE_DATA_AGENT`.

## Overview

WHY: vision.md asks fab-test to tell the caller how to fix a failure and to be a good citizen in automation, but no skill reviews how it talks to the services it calls. On 2026-11-22 a throttled Fabric Data Agent turned into a 198 s hang that ended with a Node command line. The client's own retries kept the throttle alive. `aidd-review` checks code quality and security, and `aidd-polite-review` checks caller-facing text, so retry pacing, nested retries and dropped server error bodies pass both and are found only in a live run. This epic writes that bar down as a skill, wires it into planning and review, audits fab-test's seven HTTP call sites against it, and fixes the Data Agent path first.

---

## Skill Draft

`SKILL.md`, `README.md` and `references/checklist.md` for `aidd-polite-http`, in AIDD form.

**Status**: ✅ 2026-11-22. `.github/skills/aidd-polite-http/`: `SKILL.md` (95 body lines, ~70 frontmatter tokens, checked with the Python emulation of `validate-skill`), `README.md`, `references/checklist.md` (16 rows and the worked example) and `references/known-gaps.md`. The classification puts a 401's single refresh ahead of the body's `isRetriable`, as the provider already does, and tells `RequestBlocked` (identity quota) from `CapacityLimitExceeded` (capacity).

**Requirements**:
- Given `validate-skill` (via `npx`, per the AIDD tooling note), should pass with no warnings: frontmatter under 100 tokens, body under 160 lines.
- Given `/polite-http plan`, should ask of each new HTTP call: which statuses are final, which retry, who owns retries, the time budget, whether the request is idempotent, and what each caller is told.
- Given `/polite-http review`, should check decisions 3–6 against the diff and report each finding with evidence (ran | read), severity and a concrete fix.
- Given the 2026-11-22 evidence, should carry it as the worked example of a sliding block and nested retries.

---

## Router Wiring

Load the skill from `aidd-workflow` and `aidd.agent.md`.

**Status**: ✅ 2026-11-22. A Pre-Flight rule and a Project-Specific Skills row in `aidd-workflow`; `aidd.agent.md`'s Skill Locations lists it. New guards in `tests/test_aidd_command_map.py`: the router lists the skill and loads it for HTTP work, and every project skill exists and appears in the agent's Skill Locations. That second guard caught `aidd-polite-review` missing from the agent's list since 2026-11-18; added.

**Requirements**:
- Given a task that plans or changes code making an HTTP request, should load `aidd-polite-http`; given one that doesn't, should not.
- Given the Skill Guards test, should pass with the new Pre-Flight rule mirrored in `.github/agents/aidd.agent.md`.

---

## Eval Tests

Riteway AI `.sudo` evals in `ai-evals/aidd-polite-http/`, per `aidd-upskill`.

**Status**: ⚠️ 2026-11-22, 2 of 3 passing at one run each. The rude-client eval (4/4) and the non-idempotent eval (3/3) pass. The polite-client eval failed four times. Runs 1 and 2 found real gaps: in the fixture (a retried 415, a sleep before giving up) and in the provider (a 5xx's `Retry-After` ignored, `SSLEOFError` unclassified), all fixed with tests. Runs 3 and 4 found no blocking findings and confirmed every rule, but reported out-of-scope should-fixes (input validation of the token and URL). That points at the skill, which now has a Scope constraint (findings are about what the service sees or what the caller is told; never pad). Not yet re-verified: rerun `npx -y riteway@9.3.0 ai 'ai-evals/aidd-polite-http/*.sudo' --runs 1`.

**Requirements**:
- Given the Data Agent provider as it stood on 2026-11-22, should flag the ignored `Retry-After`, the nested promptfoo retries, the retried 400/404, and the unnamed DNS failure, each with a fix.
- Given a client that retries every exception the same way, should flag the missing classification and name which failures are final.
- Given a client that honors `Retry-After`, retries in one layer and names the cause, should report no findings.
- Given a fix that retries a non-idempotent POST to recover, should flag the duplicate-effect risk rather than recommend it.

---

## HTTP Call Site Audit

Review each HTTP call site with the skill and record the gaps in `references/known-gaps.md`.

**Status**: ✅ 2026-11-22. All seven sites recorded in [known-gaps.md](../.github/skills/aidd-polite-http/references/known-gaps.md). Decision 7 settled: `_http_policy.py`. Filed: plan.md's new "Playwright REST clients: polite failures" task, and "A failed tool download is a traceback" widened to the bootstrap retry, the ADOMD.NET download's missing timeout and the PR-comment nit. `_analyzer_annotations.py` is already polite where it matters (one best-effort POST, never retried).

**Requirements**:
- Given `fabric_data_agent_provider.py`, `playwright_validation/{service_client,fabric_service_client,power_bi_api,xmla_roles}.py`, `_analyzer_annotations.py` and `_analyzer_tool_bootstrap.py`, should record per site its retry owner, `Retry-After` handling, status classes and what the caller is told.
- Given each site, should record what it does with every class in decision 5: final 4xx, 401/403, retryable 5xx, DNS and TLS failures, refused/reset/timeout, and a malformed 2xx body.
- Given the audit, should settle decision 7 (shared helper or not) and file each gap outside the Data Agent path as a plan.md standalone task; the existing "A failed tool download is a traceback" task is linked from the audit rather than duplicated.

---

## Data Agent Provider

Make the provider polite to a throttled or failing Fabric (first adopter).

**Status**: ✅ 2026-11-22. `_http_policy.py` (pure: `classify`, `retry_after`, `network_class`, `backoff`, `describe_http`, `describe_network`; 47 tests in `tests/test_http_policy.py`) and the provider on it (23 tests in `tests/test_data_agent_provider_http.py`, one per failure class, asserting request counts, sleeps and the sentence). `_data_agent_suite.py` sets `maxRetries: 0` on promptfoo's provider config, verified in promptfoo 0.124's scheduler (`getProviderMaxRetries`). A blocked agent is recorded per agent URL: one wait, then `Not asked: …` with no request until the block's end. Two tests changed on purpose: a lone question whose run fails is no longer asked again (decision 5), and a 503's message is now a sentence. The provider grew from 441 to 542 lines, over the 400-line soft budget: kept whole because the suite's seams (`_http_json`, `_urlopen`, `_sleep`, `_now`) are patched on this one module, and the growth is retry policy that belongs beside the transport. The policy-client eval found two gaps in this code too, both fixed: a 5xx carrying `Retry-After` was backed off without honoring it, and a TLS error during `read()` (`SSLEOFError`) escaped classification.

**Requirements**:
- Given a 429 with `Retry-After`, should send no request to that agent before it passes, and stop the run's calls to it when the wait outlasts the remaining time.
- Given promptfoo's own scheduler, should retry in one layer only, so a blocked question makes one request per `Retry-After` window, not up to 16, and a 5xx or timeout is not retried by both layers.
- Given a 400, 404, 409 or other final 4xx, should report it after one request, not four.
- Given a 500, 502, 503, 504, connection reset or socket timeout, should retry with capped, jittered backoff within the run's time budget, then report the last cause.
- Given a DNS or TLS failure, should report it after one request, naming the host and, for TLS, the proxy certificate fix.
- Given a 200 whose body isn't JSON, or a run that ends `failed`, `cancelled` or `expired`, should report what came back rather than a parse error or an empty answer.
- Given a final failure of any class, should return one sentence naming the cause, the service's `errorCode` and message, and what to do, never raw JSON or a Python repr.
- Given a retried question, should count it once in the live progress, with the reason it failed.

---

## Data Agent Wrapper Timeout

Report the run's outer timeout in the caller's terms.

**Status**: ✅ 2026-11-22 (5 tests in `tests/test_data_agent_wrapper_http.py`). A timeout now reads `promptfoo did not finish within 198 s: 3 of 7 questions came back (1 answered, 2 failed). Last failure: …`, from the provider's progress lines, which now carry each failure's sentence and `retry_after`. Provider errors are summarised once (`3 of 3 questions could not be asked: …`, with how many failed another way), and the envelope carries `retry_after`. Partly met: the report doesn't list which questions answered before a timeout (promptfoo writes no results when killed); live progress showed each one, and the message gives the count.

**Requirements**:
- Given promptfoo killed at the wrapper's timeout, should name the last cause the provider reported (throttled until HH:MM UTC, an unreachable host, a failing service, or a slow agent) and the flag that raises the budget, never the subprocess command line.
- Given every question failing with the same final cause (agent not found, access denied, host unreachable), should say so once at run level, not once per question.
- Given the envelope, should carry `retry_after` when the cause was throttling (decision 6), and the report should list the questions that did answer.

---

## Documentation

Human and agent callers, per the Definition of Done.

**Status**: ✅ 2026-11-22. The skill's README; `docs/DATA-AGENT-TESTS-WALKTHROUGH.md`'s troubleshooting table gains RequestBlocked, CapacityLimitExceeded, the run timeout, the run-level summary, and DNS/TLS rows; the fab-test skill's `credentials.md` and `flags.md` (both copies, synced) say what is final, what is retried, and what `retry_after` means; CHANGELOG 2026-11-22. The pipeline needs no new snippet: exit codes are unchanged and `retry_after` is an additive envelope field.

**Requirements**:
- Given the skill README, should say what the skill checks, why, and both commands with an example.
- Given `DATA-AGENT-TESTS-WALKTHROUGH.md` and the packaged `fab-test` skill, should say what a throttled run looks like and when to rerun.

---

## Quality gates

Run as CI runs them, over the whole repo (vision.md, Definition of Done).

**Status**: ✅ 2026-11-22, Playwright half deferred. `ruff check .` clean; complexity and module-budget ratchets pass; non-playwright half 3792 passed + 2 skipped, coverage 88% (floor 80%); the `GITHUB_ACTIONS=true CI=true` pass 3792 passed + 2 skipped. Blast radius: nothing outside the Data Agent path imports a changed module; `tests lint` (which runs `promptfoo validate` on the config now carrying `maxRetries: 0`) and `tests init --questions` pass through the CLI, and a live run printed `7 of 7 questions could not be asked: Fabric is rate-limiting this identity (RequestBlocked) until 19:43:58 UTC…` with `retry_after` in the envelope. **Not run:** the serial Playwright half (live renders with the same service principal, which Fabric has blocked since 16:19 UTC); no Playwright code changed. Run it once the block clears.

**Requirements**:
- Given `ruff check .`, the complexity and module-budget ratchets, the full suite with `--cov-fail-under=80`, and the CI-env run, should all pass.
