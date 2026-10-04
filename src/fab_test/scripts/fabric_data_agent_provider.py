"""Promptfoo provider for Fabric Data Agent evaluations."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ._credentials import redact_secrets
from ._data_agent_resolution import DATA_AGENT_API_VERSION

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_THREAD_CACHE: dict[str, str] = {}
_TOKEN_LOCK = threading.Lock()
_THREAD_LOCK = threading.Lock()
_POLL_SECONDS = 2
_TOKEN_REFRESH_MARGIN_SECONDS = 300


def _sleep(seconds: int | float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


def _monotonic() -> float:
    return time.monotonic()


def _json_headers(token: str = "") -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _http_error_body(exc: urllib.error.HTTPError) -> str:
    cached = getattr(exc, "_fab_test_body", None)
    if cached is not None:
        return cached
    body = ""
    with contextlib.suppress(Exception):
        payload = exc.read()
        body = payload.decode("utf-8", errors="replace") if payload else ""
    setattr(exc, "_fab_test_body", body)
    return body


def _http_error_text(exc: urllib.error.HTTPError) -> str:
    body = _http_error_body(exc).strip()
    detail = body or str(exc.reason or exc)
    return f"HTTP {exc.code}: {detail}"


def _error_text(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return redact_secrets(_http_error_text(exc))
    return redact_secrets(str(exc))


def _http_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise RuntimeError(f"Data Agent URLs must use https: {parsed.geturl()}")
    data = kwargs.get("json")
    body = json.dumps(data).encode("utf-8") if data is not None else kwargs.get("data")
    headers = kwargs.get("headers") or _json_headers(kwargs.get("token", ""))
    request = urllib.request.Request(parsed.geturl(), data=body, headers=headers, method=method)  # noqa: S310
    with urllib.request.urlopen(request, timeout=kwargs.get("timeout", 30)) as response:  # noqa: S310
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload else {}


def _token_url() -> str:
    tenant = os.environ["FABRIC_TENANT_ID"]
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


def _token_cache_key(scope: str) -> str:
    return f"{os.environ.get('FABRIC_TENANT_ID', '')}:{os.environ.get('FABRIC_CLIENT_ID', '')}:{scope}"


def _invalidate_token(scope: str) -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE.pop(_token_cache_key(scope), None)


def _get_token(*, force_refresh: bool = False) -> str:
    scope = os.environ.get("FABRIC_SCOPE", "https://analysis.windows.net/powerbi/api/.default")
    cache_key = _token_cache_key(scope)
    if not force_refresh:
        with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] - _now() > _TOKEN_REFRESH_MARGIN_SECONDS:
            return cached[0]
    else:
        _invalidate_token(scope)
    data = _http_json(
        "POST",
        _token_url(),
        timeout=30,
        data=urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": os.environ["FABRIC_CLIENT_ID"],
                "client_secret": os.environ["FABRIC_CLIENT_SECRET"],
                "scope": scope,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = data["access_token"]
    with _TOKEN_LOCK:
        _TOKEN_CACHE[cache_key] = (token, _now() + int(data.get("expires_in", 3600)))
    return token


def _authed_json(method: str, url: str, *, timeout: int, **kwargs) -> dict[str, Any]:
    scope = os.environ.get("FABRIC_SCOPE", "https://analysis.windows.net/powerbi/api/.default")
    token = _get_token()
    for attempt in range(2):
        try:
            return _http_json(method, url, token=token, timeout=timeout, **kwargs)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and attempt == 0:
                _invalidate_token(scope)
                token = _get_token(force_refresh=True)
                continue
            raise
    raise RuntimeError("unreachable")


def _validated_base_url(raw_url: str) -> str:
    base_url = raw_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https":
        raise RuntimeError(f"Data Agent base_url must use https: {base_url}")
    return base_url


def _base_url(options: dict[str, Any], context: dict[str, Any]) -> str:
    config = options.get("config", {})
    vars_ = context.get("vars", {})
    fabric_urls = config.get("fabric_urls", {}) or {}
    agent_key = vars_.get("agent") or vars_.get("agent_key") or vars_.get("fabric_url_key")
    if agent_key and agent_key in fabric_urls:
        return _validated_base_url(str(fabric_urls[agent_key]))
    base_url = config.get("base_url")
    if base_url:
        return _validated_base_url(str(base_url))
    prompt = vars_.get("query") or ""
    if isinstance(prompt, str) and "|||" in prompt:
        key, _question = prompt.split("|||", 1)
        if key in fabric_urls:
            return _validated_base_url(str(fabric_urls[key]))
    raise RuntimeError("No Data Agent URL configured. Set providers[].config.base_url or fabric_urls.")


def _conversation_id(vars_: dict[str, Any]) -> str:
    return str(vars_.get("conversation") or vars_.get("conversation_id") or "").strip()


def _conversation_key(base_url: str, conversation_id: str) -> str:
    return f"{base_url}::{conversation_id}"


def _evict_thread(base_url: str, vars_: dict[str, Any]) -> None:
    conversation = _conversation_id(vars_)
    if not conversation:
        return
    with _THREAD_LOCK:
        _THREAD_CACHE.pop(_conversation_key(base_url, conversation), None)


def _thread_id(base_url: str, vars_: dict[str, Any], timeout: int) -> str:
    conversation = _conversation_id(vars_)
    reset = bool(vars_.get("reset") or vars_.get("reset_conversation"))
    if conversation:
        key = _conversation_key(base_url, conversation)
        with _THREAD_LOCK:
            if reset:
                _THREAD_CACHE.pop(key, None)
            cached = _THREAD_CACHE.get(key)
        if cached:
            return cached
    thread = _authed_json(
        "POST",
        f"{base_url}/threads?api-version={DATA_AGENT_API_VERSION}",
        timeout=timeout,
        json={},
    )
    thread_id = thread["id"]
    if conversation:
        with _THREAD_LOCK:
            _THREAD_CACHE[_conversation_key(base_url, conversation)] = thread_id
    return thread_id


def _delete_thread(base_url: str, thread_id: str, timeout: int) -> None:
    _authed_json(
        "DELETE",
        f"{base_url}/threads/{thread_id}?api-version={DATA_AGENT_API_VERSION}",
        timeout=timeout,
    )


def _assistant_id(base_url: str, timeout: int) -> str:
    assistant = _authed_json(
        "POST",
        f"{base_url}/assistants?api-version={DATA_AGENT_API_VERSION}",
        timeout=timeout,
        json={},
    )
    return assistant["id"]


def _last_assistant_text(messages: dict[str, Any]) -> str:
    for item in reversed(messages.get("data", [])):
        if item.get("role") != "assistant":
            continue
        for content in item.get("content", []):
            if content.get("type") == "text":
                return str((content.get("text") or {}).get("value", ""))
    return ""


def _is_missing_thread_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        body = _http_error_body(exc).lower()
        return exc.code == 404 or "no thread found" in body
    return "no thread found" in str(exc).lower()


def _run_once(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    config = options.get("config", {})
    timeout = int(config.get("timeout", 60))
    base_url = _base_url(options, context)
    vars_ = context.get("vars", {})
    own_thread = not bool(_conversation_id(vars_))
    thread_id = ""
    try:
        assistant_id = _assistant_id(base_url, timeout)
        thread_id = _thread_id(base_url, vars_, timeout)
        try:
            _authed_json(
                "POST",
                f"{base_url}/threads/{thread_id}/messages?api-version={DATA_AGENT_API_VERSION}",
                timeout=timeout,
                json={"role": "user", "content": prompt},
            )
        except Exception as exc:
            if not _is_missing_thread_error(exc):
                raise
            _evict_thread(base_url, vars_)
            thread_id = _thread_id(base_url, vars_, timeout)
            _authed_json(
                "POST",
                f"{base_url}/threads/{thread_id}/messages?api-version={DATA_AGENT_API_VERSION}",
                timeout=timeout,
                json={"role": "user", "content": prompt},
            )
        run = _authed_json(
            "POST",
            f"{base_url}/threads/{thread_id}/runs?api-version={DATA_AGENT_API_VERSION}",
            timeout=timeout,
            json={"assistant_id": assistant_id},
        )
        run_id = run["id"]
        status = str(run.get("status", ""))
        started = _monotonic()
        while status not in {"completed", "failed", "cancelled", "expired"}:
            if _monotonic() - started > timeout:
                raise RuntimeError(f"Timed out waiting for Data Agent run after {timeout}s")
            _sleep(_POLL_SECONDS)
            polled = _authed_json(
                "GET",
                f"{base_url}/threads/{thread_id}/runs/{run_id}?api-version={DATA_AGENT_API_VERSION}",
                timeout=timeout,
            )
            status = str(polled.get("status", ""))
        if status != "completed":
            raise RuntimeError(f"Data Agent run ended with status '{status}'")
        messages = _authed_json(
            "GET",
            f"{base_url}/threads/{thread_id}/messages?order=asc&api-version={DATA_AGENT_API_VERSION}",
            timeout=timeout,
        )
        return {"output": _last_assistant_text(messages)}
    finally:
        if own_thread and thread_id:
            with contextlib.suppress(Exception):
                _delete_thread(base_url, thread_id, timeout)


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    """Promptfoo provider contract."""
    config = options.get("config", {})
    retries = int(config.get("max_retries", 3))
    retry_delay = int(config.get("retry_delay", 2))
    last_error = ""
    for attempt in range(retries + 1):
        try:
            return _run_once(prompt, options, context)
        except Exception as exc:  # noqa: BLE001 - provider must turn failures into promptfoo-shaped output
            last_error = _error_text(exc)
            if attempt >= retries:
                return {"error": last_error}
            _sleep(retry_delay)
    return {"error": last_error}
