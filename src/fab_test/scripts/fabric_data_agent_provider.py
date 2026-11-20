"""promptfoo provider for Fabric Data Agents (Data Agent Testing epic).

A port of fabric-data-agent-testing-template's ``provider.ts`` to promptfoo's
Python contract, ``call_api(prompt, options, context)``. Each call creates an
assistant and a thread, posts the prompt, runs it, polls until the run ends,
reads the agent's last reply, and deletes the thread -- unless the test names
a ``conversation``, whose thread is kept for the next turn.

promptfoo loads this file by path (``spec_from_file_location``), not as part
of the package, so imports are absolute and the wrapper points
``PROMPTFOO_PYTHON`` at fab-test's own interpreter.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fab_test.scripts._credentials import (
    IncompleteServicePrincipalError,
    ServicePrincipal,
    redact_secrets,
    resolve_service_principal,
)

DATA_AGENT_API_VERSION = "2024-05-01-preview"
_DEFAULT_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_POLL_SECONDS = 2
_TOKEN_REFRESH_MARGIN_SECONDS = 300
_TERMINAL = frozenset({"completed", "failed", "cancelled", "expired"})
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_THREAD_CACHE: dict[str, str] = {}
_SECRETS: set[str] = set()
_TOKEN_LOCK = threading.Lock()
_THREAD_LOCK = threading.Lock()


class _Final(RuntimeError):
    """A failure no retry can fix (credentials, a rejected token, missing access): report it at once."""


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


def _monotonic() -> float:
    return time.monotonic()


def _scope() -> str:
    return os.environ.get("FABRIC_SCOPE") or _DEFAULT_SCOPE


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


def _http_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise _Final(f"Data Agent URLs must use https: {parsed.geturl()}")
    data = kwargs.get("json")
    body = json.dumps(data).encode("utf-8") if data is not None else kwargs.get("data")
    headers = kwargs.get("headers") or {"Content-Type": "application/json"}
    if kwargs.get("token"):
        headers = {**headers, "Authorization": "Bearer " + kwargs["token"]}
    request = urllib.request.Request(parsed.geturl(), data=body, headers=headers, method=method)  # noqa: S310
    with urllib.request.urlopen(request, timeout=kwargs.get("timeout", 30)) as response:  # noqa: S310
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload else {}


def _token_url(principal: ServicePrincipal) -> str:
    return f"https://login.microsoftonline.com/{principal.tenant_id}/oauth2/v2.0/token"


def _token_cache_key(scope: str, principal: ServicePrincipal | None = None) -> str:
    principal = principal or _principal()
    return f"{principal.tenant_id}:{principal.client_id}:{scope}"


def _get_token(*, force_refresh: bool = False) -> str:
    principal = _principal()
    scope = _scope()
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
    data = _http_json(
        "POST", _token_url(principal), timeout=30,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
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
        )
    if exc.code == 403:
        return _Final(
            "the service principal may not use this Data Agent (HTTP 403); it needs a role in the agent's "
            "workspace and read access to the agent's data sources. Run `fab-test auth status`"
        )
    return None


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
            raise _rejected(exc) or exc from None
    raise AssertionError("unreachable")


def _validated_base_url(raw_url: str) -> str:
    base_url = raw_url.rstrip("/")
    if urllib.parse.urlsplit(base_url).scheme != "https":
        raise _Final(f"Data Agent base_url must use https: {base_url}")
    return base_url


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
    return "no thread found" in str(exc).lower()


def _post_message(base_url: str, vars_: dict[str, Any], thread_id: str, prompt: str, timeout: int) -> str:
    """Post ``prompt``; a conversation whose thread the agent has dropped gets a new one. Returns the thread."""
    url = f"{base_url}/threads/{{}}/messages?api-version={DATA_AGENT_API_VERSION}"
    message = {"role": "user", "content": prompt}
    try:
        _authed_json("POST", url.format(thread_id), timeout=timeout, json=message)
    except Exception as exc:
        if not _is_missing_thread(exc):
            raise
    else:
        return thread_id
    with _THREAD_LOCK:
        _THREAD_CACHE.pop(_conversation_key(base_url, vars_), None)
    thread_id = _thread_id(base_url, vars_, timeout)
    _authed_json("POST", url.format(thread_id), timeout=timeout, json=message)
    return thread_id


def _await_run(base_url: str, thread_id: str, run: dict[str, Any], timeout: int) -> None:
    status, started = str(run.get("status", "")), _monotonic()
    while status not in _TERMINAL:
        if _monotonic() - started > timeout:
            raise RuntimeError(f"Timed out waiting for Data Agent run after {timeout}s")
        _sleep(_POLL_SECONDS)
        url = f"{base_url}/threads/{thread_id}/runs/{run['id']}?api-version={DATA_AGENT_API_VERSION}"
        status = str(_authed_json("GET", url, timeout=timeout).get("status", ""))
    if status != "completed":
        raise RuntimeError(f"Data Agent run ended with status '{status}'")


def _last_assistant_text(messages: dict[str, Any]) -> str:
    for item in reversed(messages.get("data", [])):
        if item.get("role") != "assistant":
            continue
        for content in item.get("content", []):
            if content.get("type") == "text":
                return str((content.get("text") or {}).get("value", ""))
    return ""


def _run_once(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    timeout = int(options.get("config", {}).get("timeout", 60))
    base_url = _base_url(options, context)
    vars_ = context.get("vars", {})
    own_thread = not _conversation_key(base_url, vars_)
    thread_id = ""
    try:
        assistant_id = _authed_json("POST", f"{base_url}/assistants?api-version={DATA_AGENT_API_VERSION}",
                                    timeout=timeout, json={})["id"]
        thread_id = _post_message(base_url, vars_, _thread_id(base_url, vars_, timeout), prompt, timeout)
        run = _authed_json("POST", f"{base_url}/threads/{thread_id}/runs?api-version={DATA_AGENT_API_VERSION}",
                           timeout=timeout, json={"assistant_id": assistant_id})
        _await_run(base_url, thread_id, run, timeout)
        messages = _authed_json(
            "GET", f"{base_url}/threads/{thread_id}/messages?order=asc&api-version={DATA_AGENT_API_VERSION}",
            timeout=timeout,
        )
        return {"output": _last_assistant_text(messages)}
    finally:
        if own_thread and thread_id:
            with contextlib.suppress(Exception):
                _authed_json("DELETE", f"{base_url}/threads/{thread_id}?api-version={DATA_AGENT_API_VERSION}",
                             timeout=timeout)


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    """promptfoo's provider contract: ``{"output": text}``, or ``{"error": message}`` with no credential in it."""
    config = options.get("config", {})
    retries = int(config.get("max_retries", 3))
    retry_delay = float(config.get("retry_delay", 2))
    for attempt in range(retries + 1):
        try:
            return _run_once(prompt, options, context)
        except _Final as exc:
            return {"error": _redact(str(exc))}
        except Exception as exc:  # noqa: BLE001 - promptfoo needs every failure as an error response
            if attempt >= retries:
                return {"error": _error_text(exc)}
            _sleep(retry_delay)
    raise AssertionError("unreachable")
