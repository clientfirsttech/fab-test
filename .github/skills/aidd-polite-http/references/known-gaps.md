# Polite HTTP known gaps

HTTP call sites that don't yet meet this skill, so a review can tell a gap a
diff extends from one it inherited. A diff that fixes a gap removes its entry.
Numbers are rows in `checklist.md`. Audited 2026-11-22 (Polite HTTP epic).

Shared pieces: classification, `Retry-After` parsing, backoff and the caller's
sentence live in `src/fab_test/scripts/_http_policy.py` (decision 7); the sites
below adopt it rather than writing their own.

## Fixed

`fabric_data_agent_provider.py` and `invoke_data_agent.py` (Data Agent) meet every row as of 2026-11-22, on `_http_policy.py`; they are the model for the sites below.

## `playwright_validation/service_client.py` and `fabric_service_client.py` (Playwright, service targeting)

`ServiceClient._request` and `FabricServiceClient._rest_request` share one shape.

- One request, no retry: a single 429 or 503 fails the run, `Retry-After` unread (4, 10). The long-running-operation poll in `service_client.py` does honor `Retry-After` on 429, and is the model.
- `requests` connection errors and timeouts are not caught here and reach the caller as the library's own exception (9, 10).
- The message is `Fabric REST API error (HTTP N): URL`; the service's `errorCode` and message are kept on `.body` but not shown, and there is no remedy (13).

## `playwright_validation/power_bi_api.py` (embed URL, embed token)

- One request, no retry on 429 or 5xx (4, 10). Generating an embed token is safe to retry (3).
- A 200 that isn't JSON raises an uncaught `ValueError` from `response.json()` (11).
- The embed-token failure message appends the raw response text (13).

## `playwright_validation/xmla_roles.py` (ADOMD.NET download)

- `urllib.request.urlretrieve` has no timeout, so a stalled nuget.org download hangs the run (2).
- A DNS, TLS or HTTP failure is `Could not download ADOMD.NET: <urlopen error …>`, with no host or remedy (9, 13).

## `_analyzer_tool_bootstrap.py` (analyzer downloads)

- `_download` makes one attempt: a reset or 5xx from GitHub's release CDN fails the install (10).
- `URLError` is not caught, so a DNS or proxy-certificate failure is a traceback (9, 13); plan.md's standalone task "A failed tool download is a traceback".

## `_analyzer_annotations.py` (PR comments)

- Polite by design in what matters: best-effort, one POST, never retried (3), and never fails the run.
- The warning is `Could not post PR review comment: HTTP Error 403: Forbidden`, without the fix (the token needs `pull-requests: write`) (13). A nit.
