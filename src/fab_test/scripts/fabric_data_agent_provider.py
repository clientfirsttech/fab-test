"""Promptfoo provider for Fabric Data Agent evaluations."""

from __future__ import annotations

import contextlib
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from ._credentials import redact_secrets
from ._data_agent_resolution import DATA_AGENT_API_VERSION

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_THREAD_CACHE: dict[str, str] = {}
_POLL_SECONDS = 2


def _sleep(seconds: int | float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


def _json_headers(token: str = "") -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _http_json(method: str, url: str, **kwargs) -> dict[str, Any]:
    import json

    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"https", "http"}:
        raise RuntimeError(f"Unsupported URL scheme for Data Agent call: {parsed.scheme}")
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


def _get_token() -> str:
    scope = os.environ.get("FABRIC_SCOPE", "https://analysis.windows.net/powerbi/api/.default")
    cache_key = f"{os.environ.get('FABRIC_TENANT_ID', '')}:{os.environ.get('FABRIC_CLIENT_ID', '')}:{scope}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached[1] - _now() > 300:
        return cached[0]
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
    _TOKEN_CACHE[cache_key] = (token, _now() + int(data.get("expires_in", 3600)))
    return token


def _base_url(options: dict[str, Any], context: dict[str, Any]) -> str:
    config = options.get("config", {})
    vars_ = context.get("vars", {})
    fabric_urls = config.get("fabric_urls", {}) or {}
    agent_key = vars_.get("agent") or vars_.get("agent_key") or vars_.get("fabric_url_key")
    if agent_key and agent_key in fabric_urls:
        return str(fabric_urls[agent_key]).rstrip("/")
    base_url = config.get("base_url")
    if base_url:
        return str(base_url).rstrip("/")
    prompt = vars_.get("query") or ""
    if isinstance(prompt, str) and "|||" in prompt:
        key, _question = prompt.split("|||", 1)
        if key in fabric_urls:
            return str(fabric_urls[key]).rstrip("/")
    raise RuntimeError("No Data Agent URL configured. Set providers[].config.base_url or fabric_urls.")


def _conversation_key(base_url: str, conversation_id: str) -> str:
    return f"{base_url}::{conversation_id}"


def _thread_id(base_url: str, vars_: dict[str, Any], token: str, timeout: int) -> str:
    conversation = str(vars_.get("conversation") or vars_.get("conversation_id") or "").strip()
    reset = bool(vars_.get("reset") or vars_.get("reset_conversation"))
    if conversation:
        key = _conversation_key(base_url, conversation)
        if reset:
            _THREAD_CACHE.pop(key, None)
        cached = _THREAD_CACHE.get(key)
        if cached:
            return cached
    thread = _http_json(
        "POST",
        f"{base_url}/threads?api-version={DATA_AGENT_API_VERSION}",
        token=token,
        timeout=timeout,
        json={},
    )
    thread_id = thread["id"]
    if conversation:
        _THREAD_CACHE[_conversation_key(base_url, conversation)] = thread_id
    return thread_id


def _delete_thread(base_url: str, thread_id: str, token: str, timeout: int) -> None:
    _http_json(
        "DELETE",
        f"{base_url}/threads/{thread_id}?api-version={DATA_AGENT_API_VERSION}",
        token=token,
        timeout=timeout,
    )


def _assistant_id(base_url: str, token: str, timeout: int) -> str:
    assistant = _http_json(
        "POST",
        f"{base_url}/assistants?api-version={DATA_AGENT_API_VERSION}",
        token=token,
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


def _run_once(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    config = options.get("config", {})
    timeout = int(config.get("timeout", 60))
    base_url = _base_url(options, context)
    vars_ = context.get("vars", {})
    token = _get_token()
    assistant_id = _assistant_id(base_url, token, timeout)
    thread_id = _thread_id(base_url, vars_, token, timeout)
    own_thread = not bool(vars_.get("conversation") or vars_.get("conversation_id"))
    try:
        _http_json(
            "POST",
            f"{base_url}/threads/{thread_id}/messages?api-version={DATA_AGENT_API_VERSION}",
            token=token,
            timeout=timeout,
            json={"role": "user", "content": prompt},
        )
    except RuntimeError as exc:
        if "no thread found" in str(exc).lower():
            with contextlib.suppress(Exception):
                _delete_thread(base_url, thread_id, token, timeout)
            for key, value in list(_THREAD_CACHE.items()):
                if value == thread_id:
                    _THREAD_CACHE.pop(key, None)
            thread_id = _thread_id(base_url, vars_, token, timeout)
            _http_json(
                "POST",
                f"{base_url}/threads/{thread_id}/messages?api-version={DATA_AGENT_API_VERSION}",
                token=token,
                timeout=timeout,
                json={"role": "user", "content": prompt},
            )
        else:
            raise
    run = _http_json(
        "POST",
        f"{base_url}/threads/{thread_id}/runs?api-version={DATA_AGENT_API_VERSION}",
        token=token,
        timeout=timeout,
        json={"assistant_id": assistant_id},
    )
    run_id = run["id"]
    status = str(run.get("status", ""))
    started = _now()
    while status not in {"completed", "failed", "cancelled", "expired"}:
        if _now() - started > timeout:
            raise RuntimeError(f"Timed out waiting for Data Agent run after {timeout}s")
        _sleep(_POLL_SECONDS)
        polled = _http_json(
            "GET",
            f"{base_url}/threads/{thread_id}/runs/{run_id}?api-version={DATA_AGENT_API_VERSION}",
            token=token,
            timeout=timeout,
        )
        status = str(polled.get("status", ""))
    if status != "completed":
        raise RuntimeError(f"Data Agent run ended with status '{status}'")
    messages = _http_json(
        "GET",
        f"{base_url}/threads/{thread_id}/messages?order=asc&api-version={DATA_AGENT_API_VERSION}",
        token=token,
        timeout=timeout,
    )
    result = {"output": _last_assistant_text(messages)}
    if own_thread:
        _delete_thread(base_url, thread_id, token, timeout)
    return result

def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    """Promptfoo provider contract."""
    config = options.get("config", {})
    retries = int(config.get("max_retries", 0))
    retry_delay = int(config.get("retry_delay", 2))
    last_error = ""
    for attempt in range(retries + 1):
        try:
            return _run_once(prompt, options, context)
        except Exception as exc:  # noqa: BLE001 - provider must turn failures into promptfoo-shaped output
            last_error = redact_secrets(str(exc))
            if attempt >= retries:
                return {"output": "", "error": last_error}
            _sleep(retry_delay)
    return {"output": "", "error": last_error}
