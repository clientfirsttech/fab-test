---
name: aidd-polite-http
description: How fab-test code treats the services it calls over HTTP - Retry-After, one retry layer, failure classes, and what its caller is told. Use when planning, adding, reviewing, or changing code that makes an HTTP request or wraps a tool that does.
---

# Polite HTTP

`aidd-polite-review` judges how fab-test talks to its callers. This skill judges
how fab-test talks to the services it calls, and what it tells its callers when
a service says no. A polite client waits as long as the server asks, retries in
one place, stops when retrying can't help, and hands its caller the cause and
the time to come back. Neither skill restates the other.

import references/checklist.md
import references/known-gaps.md

## Failure classes

Every failure a call can meet has exactly one class. The first match wins.

FailureClass = final | refresh | wait | retryable

classify(failure) {
  (a redirect while carrying a token) => final; never follow it
  (401, the first time this call sees one) => refresh: a new token, once
  (the body says "isRetriable": false) => final, whatever the status
  (429 RequestBlocked) => wait, Retry-After or Fabric's 60 s window
  (408 | 429 | 5xx, or the body says "isRetriable": true) and (Retry-After or retry-after-ms) => wait
  (408 | 429 | 5xx, or the body says "isRetriable": true) => retryable; CapacityLimitExceeded is one: the capacity is overloaded, not the caller
  (any other 3xx or 4xx: 400, 401 again, 403, 404, 405, 409, 410, 413, 422) => final, even with a Retry-After
  (DNS failure | TLS certificate verification failure) => final: retrying can't fix a name or a certificate
  (connection refused | reset | cut mid-read | socket timeout | a TLS error that isn't verification) => retryable
  (a 2xx whose body isn't what the call expects) => final, with what came back
  (a long-running operation or agent run ends failed | cancelled | expired) => final, with its status
}

## Constraints

Constraints {
  // Pace
  Retry-After (seconds or an HTTP date) and retry-after-ms are a floor: no request goes to that endpoint before it passes, whatever the backoff says
  Retry-After is the least the server wants, not a promise: (still blocked after waiting it) => stop that endpoint for the rest of the run
  (the wait would outlast the run's remaining time) => fail now, naming when to come back; never spend the budget waiting
  A block (429 RequestBlocked, a paused capacity) stops the run's calls to that endpoint, not just the one call
  Fabric's two 429s need different remedies: RequestBlocked is the caller identity's quota (a 60 s window shared by every Fabric API and every process using that identity), CapacityLimitExceeded is the capacity's compute (the Capacity Metrics app)
  Backoff is exponential, jittered and capped, with a bounded attempt count, all inside the caller's time budget

  // One layer
  Exactly one layer retries. (fab-test drives a tool that retries, e.g. promptfoo) => the layer that sees the response headers retries; the other is told not to (promptfoo: the provider reports handlesOwnRetries, or maxRetries: 0)
  A wrapping tool reads words in an error ("429", "timeout", "503", "network") as a request to retry; word a final failure so it isn't one, or turn that tool's retries off
  Never retry a request that may already have taken effect (a posted turn, a created or deleted item) unless the service makes it idempotent

  // Tell the caller
  A final failure is one sentence: the host, what failed, the service's errorCode and message, the block's end time when there is one, and what to do. Never raw JSON, a Python repr, a traceback, or a subprocess command line
  The same final cause on every item of a run is said once, at run level
  The pipeline gets that sentence in the envelope message, with the exit code unchanged; the agent also gets retry_after (UTC, ISO 8601) in the envelope when the cause was a wait
  Progress counts work, not attempts: a retried call is one item, with the reason it failed
  Tokens, secrets and Authorization headers never reach a message, a log, or a dump of response headers

  // Scope
  A finding is about what the service sees (requests, their pacing, their count) or what the caller is told about a service's answer; input validation, general correctness and style are aidd-review's
  (the code meets every constraint) => say so and report no findings; never pad with nits

  // Evidence
  (the claim is about a live service) => reproduce it with a stubbed transport first; a live probe counts against the same throttle, so send one, then wait
}

## Process

planHttpCall(call) {
  1. Read references/known-gaps.md; never copy a listed gap
  2. Walk references/checklist.md for the call; write one Given/should line per row that applies into the epic
  3. Name the retry owner, the time budget, and whether the request is idempotent
  4. (the failure text reaches a person) => also load aidd-polite-review; (the call is a new analyzer's) => aidd-analyzer-contract
  5. TDD it (aidd-tdd) with a stubbed transport: one test per FailureClass the call can meet, asserting the request count and the message
}

reviewHttpCall(diff) {
  For each request the diff adds or changes, and each retry loop or error message around one:
    classify every failure it can meet |> check every Constraint |> report each unmet one as a Finding
  (the gap is already in known-gaps.md) => note it; a finding only if the diff extends it or copies it to a new call
  (the diff fixes a known gap) => require its entry removed from known-gaps.md
  (no request in the diff is unpolite) => report no findings rather than invent some
}

Finding {
  title
  severity: blocking | should-fix | nit    // aidd-review's levels
  constraint      // the rule above it breaks
  evidence: ran | read
  whatHappens     // request count, timing, or the exact message
  fix             // concrete: the class, the header honored, the sentence the caller should get
}

severity(finding) {
  (retries multiply across layers, ignore Retry-After, or repeat a request that may have taken effect) => blocking
  (a final failure is retried, or the caller gets no cause or no remedy) => should-fix
  (wording, or a rare path that is otherwise right) => nit
}

Commands {
  /polite-http plan [call] - the checklist rows and Given/should lines for a new or changed HTTP call
  /polite-http review [diff | file] - check HTTP calls against this skill; review-only
}
