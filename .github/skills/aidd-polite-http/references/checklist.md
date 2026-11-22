# Polite HTTP checklist

One row per question to answer for each HTTP call. `/polite-http plan` turns
each row that applies into a Given/should line in the epic;
`/polite-http review` checks each one against the diff.

| # | Ask | Polite answer |
|---|-----|---------------|
| 1 | Which layer retries? | Exactly one. If fab-test drives a tool that retries (promptfoo, a SDK with its own policy), one of the two is switched off, and the choice is written beside the code. |
| 2 | What is the time budget? | Retries and waits fit inside the run's `--timeout`. A wait that won't fit fails at once, naming when to come back. |
| 3 | Is the request idempotent? | GET, PUT and DELETE are. A POST that creates, posts or sends is not: after a timeout or 5xx it may have taken effect, so it is retried only if the service dedupes it. |
| 4 | Is `Retry-After` honored? | Parsed as seconds or an HTTP date (and `retry-after-ms`), used as a floor over the backoff, and the endpoint gets no request before it passes. |
| 5 | What does a block do to the rest of the run? | A 429 `RequestBlocked` or a paused capacity stops calls to that endpoint for the run; the remaining items are reported as not asked, with the cause once. |
| 6 | Is every final 4xx final? | 400, 403, 404, 405, 409, 410, 413, 422 and a second 401 are reported after one request, with the service's message. |
| 7 | Is a body's `isRetriable` read? | Yes, and it overrides the status either way. |
| 8 | Is the 401 path a single refresh? | One new token, one retry, then final with what to check. |
| 9 | What do DNS and TLS failures say? | Final after one request; the message names the host, and for a certificate failure the proxy or `SSL_CERT_FILE` fix. |
| 10 | Are refused, reset and timed-out connections retried? | Yes, with capped, jittered backoff inside the budget, and the last cause reported. |
| 11 | What if a 2xx body is wrong? | Unparseable or missing fields are final, reported with what came back, never a `KeyError` or an empty answer. |
| 12 | What if a long-running operation or run fails? | `failed`, `cancelled` or `expired` is final, reported with its status and the service's error. |
| 13 | What does the caller see? | One sentence: host, what failed, `errorCode` and message, block end time, what to do. The envelope carries it, plus `retry_after` for a wait. No JSON body, repr, traceback or command line. |
| 14 | Is progress honest? | One line per item, not per attempt, with why it failed. |
| 15 | Is anything secret printed? | No token, secret or `Authorization` header in any message, log or header dump. |
| 16 | How is it tested? | A stubbed transport, one test per failure class the call can meet, asserting the number of requests and the message. Live runs only confirm. |

## Worked example: a throttled Data Agent (2026-11-22)

`fab-test data-agent --workspace fab-test-working-area` asked seven questions
of a Fabric Data Agent while Fabric was blocking its API.

- Fabric answered `429`, `errorCode: RequestBlocked`, `Retry-After: 16`,
  `isRetriable: true`, "blocked by the upstream service until 16:23:38 UTC".
  The workspace API answered normally: only the agent endpoint was blocked.
- Every later request drew a new block ending 120 s after it. A silent wait of
  202 s, past the stated end, still drew a new one. `Retry-After` was the least
  Fabric wanted, not a promise (row 4, row 5).
- The provider made 4 attempts 2 s apart and ignored `Retry-After` (row 4).
  promptfoo saw "429" in the provider's error and called it again, up to 3
  more times (row 1): up to 16 requests per question while blocked.
- Progress showed the first question three times, as `1/7`, `2/7` and `3/7`
  (row 14).
- The run hit its 198 s timeout and printed the Node command line instead of
  the cause (row 13).
- With a stubbed transport, the same provider retried 400 and 404 four times
  (row 6) and reported a DNS failure as `<urlopen error getaddrinfo failed>`
  (row 9).

Microsoft documents `RequestBlocked` as the caller identity's request quota
(a fixed 60 s window, shared by every Fabric API and every process using that
service principal), and `CapacityLimitExceeded` as the separate capacity case.
A block that outlives a silent wait points at something else spending the same
identity's quota.

A polite version sends one request, sees the block, waits at least its
`Retry-After` once, stops the agent for the run if it is still blocked, and
reports once: "Fabric is rate-limiting this service principal (RequestBlocked)
until 16:38 UTC; 7 questions were not asked. Another run or tool using the same
service principal shares its quota. Wait and rerun."
