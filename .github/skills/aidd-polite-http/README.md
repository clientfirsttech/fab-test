# aidd-polite-http

Plans and reviews how fab-test's code treats the services it calls over HTTP: how long it waits when a service is busy, which layer retries, which failures it gives up on at once, and what it tells the person, pipeline or agent that ran it.

## Why

On 2026-11-22 Fabric throttled a Data Agent. fab-test ignored the service's `Retry-After`, retried in two layers at once (up to 16 requests per question), and after 198 s printed a Node command line instead of "Fabric is throttling this agent until 16:38 UTC". The same code retried a 404 four times. Code review checks correctness and security, and `aidd-polite-review` checks what a caller reads, so none of this was caught before a live run. This skill writes the bar down: a class for every failure, `Retry-After` as a floor, one retry layer, and one clear sentence for the caller.

## Commands

`/polite-http plan [call]` turns the checklist into Given/should requirements for a new or changed HTTP call: who retries, the time budget, whether the request is idempotent, and what each failure class does.

```
/polite-http plan the Data Agent provider's run polling
```

`/polite-http review [diff | file]` checks each request in a diff or file against the failure classes and constraints, and reports findings at `aidd-review`'s levels (blocking, should-fix, nit). It is review-only.

```
/polite-http review src/fab_test/scripts/fabric_data_agent_provider.py
```

## When it runs

The AIDD router loads it whenever a task plans, adds, reviews or changes code that makes an HTTP request, or wraps a tool that does. `references/known-gaps.md` lists the call sites that don't meet it yet.
