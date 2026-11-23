"""promptfoo provider for Fabric Data Agents (Data Agent Testing epic).

A port of fabric-data-agent-testing-template's ``provider.ts`` to promptfoo's
Python contract, ``call_api(prompt, options, context)``. Each call creates an
assistant and a thread, posts the prompt, runs it, polls until the run ends,
reads the agent's last reply, and deletes the thread -- unless the test names
a ``conversation``, whose thread is kept for the next turn.

promptfoo loads the package-level entry point by path; that entry point imports
this module using the interpreter selected by ``PROMPTFOO_PYTHON``.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fab_test.scripts import _http_policy as policy
from fab_test.scripts._credentials import (
    AUTH_CHOICES,
    DATA_AGENT_AUTH_VAR,
    AzureCliSignInError,
    IncompleteServicePrincipalError,
    ServicePrincipal,
    azure_cli_token,
    data_agent_auth,
    redact_secrets,
    resolve_service_principal,
)

DATA_AGENT_API_VERSION = "2024-05-01-preview"
_DEFAULT_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_POLL_SECONDS = 2
_TOKEN_REFRESH_MARGIN_SECONDS = 300
_TERMINAL = frozenset({"completed", "failed", "cancelled", "expired"})
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
ALLOWED_HOSTS_VAR = "FAB_TEST_DATA_AGENT_ALLOWED_HOSTS"
_TOKEN_HOST_SUFFIXES = (".fabric.microsoft.com", ".powerbi.com")
PROGRESS_VAR = "FAB_TEST_DATA_AGENT_PROGRESS"
_PROGRESS_LOCK = threading.Lock()

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_THREAD_CACHE: dict[str, str] = {}
_BLOCKED: dict[str, tuple[float, str]] = {}  # agent URL -> (blocked until, why): asked no more this run
_SECRETS: set[str] = set()
_TOKEN_LOCK = threading.Lock()
_THREAD_LOCK = threading.Lock()
_BLOCK_SECONDS_WITHOUT_HEADER = 60.0  # Fabric's request quota is counted in 60 s windows


class _Final(RuntimeError):
    """A failure no retry can fix (credentials, a rejected token, missing access): report it at once."""

    status: int | None = None  # the HTTP status behind it, when there was one


class _Retry(RuntimeError):
    """A failure asking again may fix. ``delay`` is the server's wait (a floor), None for plain backoff."""

    def __init__(self, message: str, delay: float | None = None) -> None:
        super().__init__(message)
        self.delay = delay
        self.status: int | None = None


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


def _monotonic() -> float:
    return time.monotonic()


def _scope() -> str:
    return os.environ.get("FABRIC_SCOPE") or _DEFAULT_SCOPE


def _auth_mode() -> str:
    """"az" or "service-principal": the wrapper's choice, else the chain (Data Agent az login epic)."""
    requested = os.environ.get(DATA_AGENT_AUTH_VAR, "")
    if requested in AUTH_CHOICES:
        return requested
    try:
        return data_agent_auth()
    except IncompleteServicePrincipalError as exc:
        raise _Final(f"{exc}; `fab-test auth status` shows what is set") from None


def _identity() -> str:
    return "your az login identity" if os.environ.get(DATA_AGENT_AUTH_VAR) == "az" else "the service principal"


def _principal() -> ServicePrincipal:
    """The service principal fab-test resolves everywhere (env, then .fab-test/.env or .env); nothing else."""
    try:
        principal = resolve_service_principal()
    except IncompleteServicePrincipalError as exc:
        raise _Final(f"{exc}; `fab-test auth status` shows what is set") from None
    if principal is None:
        raise _Final(
            "Data Agent tests need a service principal: set FABRIC_TENANT_ID, FABRIC_CLIENT_ID and "
            "FABRIC_CLIENT_SECRET, in the environment or .fab-test/.env; `fab-test auth status` shows what is set"
        )
    _SECRETS.add(principal.client_secret)
    return principal


def _redact(text: str) -> str:
    """Remove the client secret (from the environment or a .env file) and every token this process holds."""
    text = redact_secrets(text)
    tokens = {token for token, _expiry in _TOKEN_CACHE.values()}
    for value in _SECRETS | tokens:
        if len(value) >= 8:
            text = text.replace(value, "<redacted>")
    return _BEARER.sub("Bearer <redacted>", text)


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    cached = getattr(exc, "_fab_test_body", None)
    if cached is not None:
        return cached
    body = ""
    with contextlib.suppress(Exception):
        payload = exc.read()
        body = payload.decode("utf-8", errors="replace") if payload else ""
    exc._fab_test_body = body  # read once: the stream can't be read twice
    return body


def _error_text(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        detail = _http_error_body(exc).strip() or str(exc.reason or exc)
        return _redact(f"HTTP {exc.code}: {detail}")
    return _redact(str(exc))


def _allowed_host(host: str) -> bool:
    """Fabric and Power BI hosts, plus exact hosts the caller's environment names (decision 17).

    Read from the environment, never the suite: whoever writes a suite controls its URL,
    so a suite must not be able to widen where the token goes.
    """
    host = host.lower().rstrip(".")
    if host.endswith(_TOKEN_HOST_SUFFIXES):
        return True
    extra = os.environ.get(ALLOWED_HOSTS_VAR, "")
    return host in {item.strip().lower() for item in extra.split(",") if item.strip()}


def _check_destination(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise _Final(f"Data Agent URLs must use https: {parsed.scheme}://{parsed.hostname or ''}")
    if not _allowed_host(parsed.hostname or ""):
        raise _Final(
            f"fab-test sends the Fabric token only to Fabric or Power BI hosts, not {parsed.hostname!r}. "
            f"Remove the suite's base_url/fabric_urls, or allow the exact host in the caller's "
            f"{ALLOWED_HOSTS_VAR} (comma-separated)"
        )
    if parsed.username or parsed.password:
        raise _Final(f"Data Agent URLs must not carry user info ({parsed.hostname!r}); "
                     "the token is the only credential")
    return parsed


def destination_problem(url: Any) -> str | None:
    """The run's refusal for a URL the token must not go to, or None. Lint shares it (decision 18)."""
    try:
        _check_destination(str(url).rstrip("/"))
    except _Final as exc:
        return str(exc)
    return None


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib keeps the Authorization header across a redirect, so fab-test follows none."""

    def redirect_request(self, _req, _fp, code, _msg, _headers, newurl):  # urllib calls it positionally
        host = urllib.parse.urlsplit(newurl).hostname
        raise _Final(f"the Data Agent API answered HTTP {code}, a redirect to {host!r}; fab-test does not follow "
                     "redirects with a token. Check the agent URL")


_OPENER = urllib.request.build_opener(_RefuseRedirects())


def _urlopen(request: urllib.request.Request, timeout: float):
    return _OPENER.open(request, timeout=timeout)


def _http_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    token = kwargs.get("token")
    parsed = _check_destination(url) if token else urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise _Final(f"Data Agent URLs must use https: {parsed.geturl()}")
    data = kwargs.get("json")
    body = json.dumps(data).encode("utf-8") if data is not None else kwargs.get("data")
    headers = kwargs.get("headers") or {"Content-Type": "application/json"}
    if token:
        headers = {**headers, "Authorization": "Bearer " + token}
    request = urllib.request.Request(parsed.geturl(), data=body, headers=headers, method=method)  # noqa: S310
    with _urlopen(request, timeout=kwargs.get("timeout", 30)) as response:
        payload = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(payload) if payload else {}
    except ValueError:
        start = " ".join(payload.split())[:120]
        raise _Final(_redact(f"{parsed.hostname} answered with a body that is not JSON, starting: {start}")) from None


def _token_url(principal: ServicePrincipal) -> str:
    return f"https://login.microsoftonline.com/{principal.tenant_id}/oauth2/v2.0/token"


def _token_cache_key(scope: str, principal: ServicePrincipal | None = None) -> str:
    principal = principal or _principal()
    return f"{principal.tenant_id}:{principal.client_id}:{scope}"


def _az_token(scope: str, *, force_refresh: bool) -> str:
    key = f"az:{scope}"
    with _TOKEN_LOCK:
        cached = None if force_refresh else _TOKEN_CACHE.get(key)
    if cached and cached[1] - _now() > _TOKEN_REFRESH_MARGIN_SECONDS:
        return cached[0]
    try:
        token, expires_on = azure_cli_token(scope)
    except AzureCliSignInError as exc:
        raise _Final(str(exc)) from None  # a sign-in no retry fixes (aidd-polite-http)
    with _TOKEN_LOCK:
        _TOKEN_CACHE[key] = (token, expires_on)
    return token


def _get_token(*, force_refresh: bool = False) -> str:
    scope = _scope()
    if _auth_mode() == "az":
        return _az_token(scope, force_refresh=force_refresh)
    principal = _principal()
    key = _token_cache_key(scope, principal)
    with _TOKEN_LOCK:
        cached = None if force_refresh else _TOKEN_CACHE.get(key)
    if cached and cached[1] - _now() > _TOKEN_REFRESH_MARGIN_SECONDS:
        return cached[0]
    form = {
        "grant_type": "client_credentials",
        "client_id": principal.client_id,
        "client_secret": principal.client_secret,
        "scope": scope,
    }
    try:
        data = _http_json(
            "POST", _token_url(principal), timeout=30,
            data=urllib.parse.urlencode(form).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    except _TRANSPORT_ERRORS as exc:
        raise _classified(exc, _token_url(principal)) from None
    token = data["access_token"]
    with _TOKEN_LOCK:
        _TOKEN_CACHE[key] = (token, _now() + int(data.get("expires_in", 3600)))
    return token


def _rejected(exc: urllib.error.HTTPError) -> _Final | None:
    """The message for a status no retry fixes, in the words the service paths use (`_service_export`)."""
    if exc.code == 401:
        return _Final(
            "Fabric rejected the token (HTTP 401) -- it is for a different tenant than the workspace, expired, "
            "or the tenant does not yet let service principals use Fabric APIs. Check FABRIC_TENANT_ID and "
            "which identity `fab-test auth status` reports"
        ) if _identity() == "the service principal" else _Final(
            "Fabric rejected your az login token (HTTP 401) -- it is for a different tenant than the workspace "
            "or expired. Run `az login --tenant <the workspace's tenant>`"
        )
    if exc.code == 403:
        return _Final(
            f"{_identity()} may not use this Data Agent (HTTP 403); it needs a role in the agent's "
            "workspace and read access to the agent's data sources. Run `fab-test auth status`"
        )
    return _not_retriable(exc)


def _not_retriable(exc: urllib.error.HTTPError) -> _Final | None:
    """A paused capacity names the fix; every other status is classified by ``_classified``."""
    if _json_body(exc).get("errorCode") == "CapacityNotActive":
        return _Final(f"the agent's Fabric capacity is paused (CapacityNotActive): resume the capacity behind the "
                      f"workspace, then run again. {_error_text(exc)}")
    return None


def _json_body(exc: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        body = json.loads(_http_error_body(exc) or "{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


# OSError covers URLError (and HTTPError), timeouts, resets and TLS errors; IncompleteRead and other
# http.client errors, and a TLS error during read(), escape urllib unwrapped
_TRANSPORT_ERRORS = (OSError, http.client.HTTPException)


def _classified(exc: Exception, url: str) -> _Final | _Retry:
    """The failure as ``aidd-polite-http`` classes it, worded for the person who ran the suite."""
    host = urllib.parse.urlsplit(url).hostname or url
    if not isinstance(exc, urllib.error.HTTPError):
        text = _redact(policy.describe_network(host, exc))
        return _Final(text) if policy.network_class(exc) == policy.FINAL else _Retry(text)
    body = _json_body(exc)
    if "message" not in body and body.get("error_description"):  # the token endpoint's spelling
        body = {**body, "message": body["error_description"]}
    elif not body and (raw := _http_error_body(exc).strip()) and raw[0] not in "{[":
        body = {"message": " ".join(raw.split())[:200]}  # plain text is still the service's own words
    delay = policy.retry_after(exc.headers, _now())
    kind = policy.classify(exc.code, body, delay)
    if kind == policy.WAIT and delay is None:
        delay = _BLOCK_SECONDS_WITHOUT_HEADER
    text = _redact(policy.describe_http(host, exc.code, body, until=_now() + delay if delay is not None else None,
                                        reason=str(exc.reason or "")))
    failure = _Final(text) if kind == policy.FINAL else _Retry(text, delay if kind == policy.WAIT else None)
    failure.status = exc.code
    return failure


def _authed_json(method: str, url: str, *, timeout: int, **kwargs: Any) -> dict[str, Any]:
    """Call the agent API with a cached token; a 401 refreshes it once, then is final."""
    token = _get_token()
    for attempt in range(2):
        try:
            return _http_json(method, url, token=token, timeout=timeout, **kwargs)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and attempt == 0:
                token = _get_token(force_refresh=True)
                continue
            raise _rejected(exc) or _classified(exc, url) from None
        except _TRANSPORT_ERRORS as exc:
            raise _classified(exc, url) from None
    raise AssertionError("unreachable")


def _validated_base_url(raw_url: str) -> str:
    """Refuse an http or non-Fabric agent URL before any token is fetched."""
    base_url = raw_url.rstrip("/")
    _check_destination(base_url)
    return base_url


def _segment(value: Any) -> str:
    """A server-issued id as one path segment: ``/`` and ``?`` can't steer the request."""
    return urllib.parse.quote(str(value), safe="")


def _base_url(options: dict[str, Any], context: dict[str, Any]) -> str:
    """``config.base_url``, or the template's ``fabric_urls`` keyed by ``vars.agent`` or a ``key|||question`` prompt."""
    config = options.get("config", {})
    vars_ = context.get("vars", {})
    fabric_urls = config.get("fabric_urls") or {}
    agent_key = vars_.get("agent") or vars_.get("agent_key") or vars_.get("fabric_url_key")
    if agent_key and agent_key in fabric_urls:
        return _validated_base_url(str(fabric_urls[agent_key]))
    if config.get("base_url"):
        return _validated_base_url(str(config["base_url"]))
    query = vars_.get("query") or ""
    if isinstance(query, str) and "|||" in query:
        key = query.split("|||", 1)[0]
        if key in fabric_urls:
            return _validated_base_url(str(fabric_urls[key]))
    raise _Final("No Data Agent URL configured. Set providers[].config.base_url or fabric_urls.")


def _conversation_key(base_url: str, vars_: dict[str, Any]) -> str:
    conversation = str(vars_.get("conversation") or vars_.get("conversation_id") or "").strip()
    return f"{base_url}::{conversation}" if conversation else ""


def _thread_id(base_url: str, vars_: dict[str, Any], timeout: int) -> str:
    key = _conversation_key(base_url, vars_)
    if key:
        with _THREAD_LOCK:
            if vars_.get("reset") or vars_.get("reset_conversation"):
                _THREAD_CACHE.pop(key, None)
            cached = _THREAD_CACHE.get(key)
        if cached:
            return cached
    thread_id = _authed_json("POST", f"{base_url}/threads?api-version={DATA_AGENT_API_VERSION}",
                             timeout=timeout, json={})["id"]
    if key:
        with _THREAD_LOCK:
            _THREAD_CACHE[key] = thread_id
    return thread_id


def _is_missing_thread(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 404 or "no thread found" in _http_error_body(exc).lower()
    return getattr(exc, "status", None) == 404 or "no thread found" in str(exc).lower()


def _post_message(base_url: str, vars_: dict[str, Any], thread_id: str, prompt: str, timeout: int) -> str:
    """Post ``prompt``; a conversation whose thread the agent has dropped gets a new one. Returns the thread."""
    url = f"{base_url}/threads/{{}}/messages?api-version={DATA_AGENT_API_VERSION}"
    message = {"role": "user", "content": prompt}
    try:
        _authed_json("POST", url.format(_segment(thread_id)), timeout=timeout, json=message)
    except Exception as exc:
        if not _is_missing_thread(exc):
            raise
    else:
        return thread_id
    with _THREAD_LOCK:
        _THREAD_CACHE.pop(_conversation_key(base_url, vars_), None)
    thread_id = _thread_id(base_url, vars_, timeout)
    _authed_json("POST", url.format(_segment(thread_id)), timeout=timeout, json=message)
    return thread_id


def _await_run(base_url: str, thread_id: str, run: dict[str, Any], timeout: int) -> None:
    status, started = str(run.get("status", "")), _monotonic()
    while status not in _TERMINAL:
        if _monotonic() - started > timeout:
            raise _Final(f"Timed out waiting for Data Agent run after {timeout}s; raise the suite's "
                         "providers[].config.timeout or --timeout if the agent is slow")
        _sleep(_POLL_SECONDS)
        url = (f"{base_url}/threads/{_segment(thread_id)}/runs/{_segment(run['id'])}"
               f"?api-version={DATA_AGENT_API_VERSION}")
        run = _authed_json("GET", url, timeout=timeout)
        status = str(run.get("status", ""))
    if status != "completed":  # failed, cancelled or expired: the agent's verdict, not a transient fault
        error = run.get("last_error") or {}
        detail = f": {error.get('code') or 'error'}: {error.get('message')}" if error.get("message") else ""
        raise _Final(f"Data Agent run ended with status '{status}'{detail}")


def _last_assistant_text(messages: dict[str, Any]) -> str:
    for item in reversed(messages.get("data", [])):
        if item.get("role") != "assistant":
            continue
        for content in item.get("content", []):
            if content.get("type") == "text":
                return str((content.get("text") or {}).get("value", ""))
    return ""


def _post_turn(base_url: str, vars_: dict[str, Any], thread_id: str, prompt: str, timeout: int) -> str:
    """A conversation's turn goes on a shared thread. Only a 429 proves the service refused it; after a timeout,
    a reset or a 5xx it may be there already, and posting again would put it in the conversation twice."""
    try:
        return _post_message(base_url, vars_, thread_id, prompt, timeout)
    except _Retry as exc:
        if exc.status == 429:
            raise
        raise _Final(f"{exc} (not asked again: the turn may already be in the conversation, and asking again "
                     "would post it twice)") from exc


def _answer_posted_turn(base_url: str, thread_id: str, assistant_id: str, timeout: int) -> dict[str, str]:
    """A conversation's turn is on the shared thread now: a retry would post it twice, so failures are final."""
    try:
        return _answer(base_url, thread_id, assistant_id, timeout)
    except _Final:
        raise
    except Exception as exc:
        raise _Final(f"{_error_text(exc)} (not asked again: a retry would post this turn twice in the "
                     "conversation)") from exc


def _answer(base_url: str, thread_id: str, assistant_id: str, timeout: int) -> dict[str, str]:
    """Run the assistant on the thread and read its reply."""
    thread = f"{base_url}/threads/{_segment(thread_id)}"
    run = _authed_json("POST", f"{thread}/runs?api-version={DATA_AGENT_API_VERSION}",
                       timeout=timeout, json={"assistant_id": assistant_id})
    _await_run(base_url, thread_id, run, timeout)
    messages = _authed_json("GET", f"{thread}/messages?order=asc&api-version={DATA_AGENT_API_VERSION}",
                            timeout=timeout)
    return {"output": _last_assistant_text(messages)}


def _run_once(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    timeout = int(options.get("config", {}).get("timeout", 60))
    base_url = _base_url(options, context)
    vars_ = context.get("vars", {})
    own_thread = not _conversation_key(base_url, vars_)
    thread_id = ""
    try:
        assistant_id = _authed_json("POST", f"{base_url}/assistants?api-version={DATA_AGENT_API_VERSION}",
                                    timeout=timeout, json={})["id"]
        thread_id = _thread_id(base_url, vars_, timeout)  # set first: a failed post still deletes it
        if own_thread:
            thread_id = _post_message(base_url, vars_, thread_id, prompt, timeout)
            return _answer(base_url, thread_id, assistant_id, timeout)
        thread_id = _post_turn(base_url, vars_, thread_id, prompt, timeout)
        return _answer_posted_turn(base_url, thread_id, assistant_id, timeout)
    finally:
        if own_thread and thread_id:
            with contextlib.suppress(Exception):
                _authed_json("DELETE", f"{base_url}/threads/{_segment(thread_id)}"
                             f"?api-version={DATA_AGENT_API_VERSION}", timeout=timeout)


def _report_progress(prompt: str, started: float, result: dict[str, Any]) -> None:
    """One line per answer for the wrapper to show live; a run of live calls must not look hung.

    The path comes from the wrapper's private temp dir (``FAB_TEST_*``, which a suite may not set).
    Progress is a courtesy: failing to write it never fails the test.
    """
    path = os.environ.get(PROGRESS_VAR)
    if not path:
        return
    entry = {"query": prompt, "seconds": round(time.monotonic() - started), "error": "error" in result}
    if "error" in result:  # already redacted: the same sentence promptfoo gets
        entry["message"] = result["error"]
        if retry_after := (result.get("metadata") or {}).get("retry_after"):
            entry["retry_after"] = retry_after
    line = json.dumps(entry)
    with contextlib.suppress(OSError), _PROGRESS_LOCK, open(path, "a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """promptfoo's provider contract: ``{"output": text}``, or ``{"error": message}`` with no credential in it."""
    started = time.monotonic()
    result = _call_api(prompt, options, context)
    _report_progress(prompt, started, result)
    return result


def _blocked_result(text: str, until: float) -> dict[str, Any]:
    """An error with the UTC time to come back, for the wrapper's envelope (``retry_after``)."""
    return {"error": text, "metadata": {"retry_after": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(until))}}


def _block(base_url: str, exc: _Retry) -> dict[str, Any]:
    """Stop asking this agent until the server's wait has passed; every later question says why at once."""
    until = _now() + (exc.delay or _BLOCK_SECONDS_WITHOUT_HEADER)
    with _THREAD_LOCK:
        _BLOCKED[base_url] = (until, str(exc))
    return _blocked_result(str(exc), until)


def _still_blocked(base_url: str) -> dict[str, Any] | None:
    with _THREAD_LOCK:
        until, why = _BLOCKED.get(base_url, (0.0, ""))
    return _blocked_result(f"Not asked: {why}", until) if _now() < until else None


def _call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """The one layer that retries (aidd-polite-http): promptfoo's own retries are off (``maxRetries: 0``).

    A server's wait is a floor, waited once; still blocked after it, the agent is asked no more this run.
    """
    config = options.get("config", {})
    retries = int(config.get("max_retries", 3))
    retry_delay = float(config.get("retry_delay", 2))
    budget = float(config.get("timeout", 60))
    try:
        base_url = _base_url(options, context)
    except _Final as exc:
        return {"error": _redact(str(exc))}
    if blocked := _still_blocked(base_url):
        return blocked
    waited, last = False, ""
    for attempt in range(retries + 1):
        try:
            return _run_once(prompt, options, context)
        except _Final as exc:
            return {"error": _redact(str(exc))}
        except _Retry as exc:
            if exc.delay is not None:
                if waited or exc.delay > budget or attempt >= retries:
                    return _block(base_url, exc)
                waited = True
                _sleep(exc.delay)
                continue
            last = str(exc)
        except Exception as exc:  # noqa: BLE001 - promptfoo needs every failure as an error response
            last = _error_text(exc)
        if attempt >= retries:
            return {"error": last}
        _sleep(policy.backoff(attempt, retry_delay))
    raise AssertionError("unreachable")
