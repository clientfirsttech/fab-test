"""Data Agent request lifecycle and retry coordination for the promptfoo provider."""

from __future__ import annotations

import contextlib
import json
import os
import time
import urllib.error
import urllib.parse
from typing import Any, Protocol

from fab_test.scripts import _http_policy as policy


class Runtime(Protocol):
    """Provider state and test seams resolved at call time."""

    def __getattr__(self, name: str) -> Any: ...


def validated_base_url(runtime: Runtime, raw_url: str) -> str:
    """Refuse an http or non-Fabric agent URL before any token is fetched."""
    base_url = raw_url.rstrip("/")
    runtime._check_destination(base_url)
    return base_url


def _segment(value: Any) -> str:
    """A server-issued id as one path segment: ``/`` and ``?`` can't steer the request."""
    return urllib.parse.quote(str(value), safe="")


def _base_url(runtime: Runtime, options: dict[str, Any], context: dict[str, Any]) -> str:
    """Read the explicit base URL or template URL mapped by the test's agent variable."""
    config = options.get("config", {})
    vars_ = context.get("vars", {})
    fabric_urls = config.get("fabric_urls") or {}
    agent_key = vars_.get("agent") or vars_.get("agent_key") or vars_.get("fabric_url_key")
    if agent_key and agent_key in fabric_urls:
        return validated_base_url(runtime, str(fabric_urls[agent_key]))
    if config.get("base_url"):
        return validated_base_url(runtime, str(config["base_url"]))
    query = vars_.get("query") or ""
    if isinstance(query, str) and "|||" in query:
        key = query.split("|||", 1)[0]
        if key in fabric_urls:
            return validated_base_url(runtime, str(fabric_urls[key]))
    raise runtime._Final("No Data Agent URL configured. Set providers[].config.base_url or fabric_urls.")


def _conversation_key(base_url: str, vars_: dict[str, Any]) -> str:
    conversation = str(vars_.get("conversation") or vars_.get("conversation_id") or "").strip()
    return f"{base_url}::{conversation}" if conversation else ""


def _thread_id(runtime: Runtime, base_url: str, vars_: dict[str, Any], timeout: int) -> str:
    key = _conversation_key(base_url, vars_)
    if key:
        with runtime._THREAD_LOCK:
            if vars_.get("reset") or vars_.get("reset_conversation"):
                runtime._THREAD_CACHE.pop(key, None)
            cached = runtime._THREAD_CACHE.get(key)
        if cached:
            return cached
    url = f"{base_url}/threads?api-version={runtime.DATA_AGENT_API_VERSION}"
    thread_id = runtime._field(runtime._authed_json("POST", url, timeout=timeout, json={}), "id", url)
    if key:
        with runtime._THREAD_LOCK:
            runtime._THREAD_CACHE[key] = thread_id
    return thread_id


def _is_missing_thread(runtime: Runtime, exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 404 or "no thread found" in runtime._http_error_body(exc).lower()
    return getattr(exc, "status", None) == 404 or "no thread found" in str(exc).lower()


def _post_message(
    runtime: Runtime, base_url: str, vars_: dict[str, Any], thread_id: str, prompt: str, timeout: int,
) -> str:
    """Post a prompt, recreating a conversation thread the service has dropped."""
    url = f"{base_url}/threads/{{}}/messages?api-version={runtime.DATA_AGENT_API_VERSION}"
    message = {"role": "user", "content": prompt}
    try:
        runtime._authed_json("POST", url.format(_segment(thread_id)), timeout=timeout, json=message)
    except Exception as exc:
        if not _is_missing_thread(runtime, exc):
            raise
    else:
        return thread_id
    with runtime._THREAD_LOCK:
        runtime._THREAD_CACHE.pop(_conversation_key(base_url, vars_), None)
    thread_id = _thread_id(runtime, base_url, vars_, timeout)
    runtime._authed_json("POST", url.format(_segment(thread_id)), timeout=timeout, json=message)
    return thread_id


def _await_run(runtime: Runtime, base_url: str, thread_id: str, run: dict[str, Any], timeout: int) -> None:
    status, started = str(run.get("status", "")), runtime._monotonic()
    while status not in runtime._TERMINAL:
        if runtime._monotonic() - started > timeout:
            raise runtime._Final(
                f"Timed out waiting for Data Agent run after {timeout}s; raise the suite's "
                "providers[].config.timeout or --timeout if the agent is slow"
            )
        runtime._sleep(runtime._POLL_SECONDS)
        url = (
            f"{base_url}/threads/{_segment(thread_id)}/runs/{_segment(run['id'])}"
            f"?api-version={runtime.DATA_AGENT_API_VERSION}"
        )
        run = runtime._authed_json("GET", url, timeout=timeout)
        status = str(run.get("status", ""))
    if status != "completed":
        error = run.get("last_error") or {}
        detail = f": {error.get('code') or 'error'}: {error.get('message')}" if error.get("message") else ""
        raise runtime._Final(f"Data Agent run ended with status '{status}'{detail}")


def _last_assistant_text(messages: dict[str, Any]) -> str:
    for item in reversed(messages.get("data", [])):
        if item.get("role") != "assistant":
            continue
        for content in item.get("content", []):
            if content.get("type") == "text":
                return str((content.get("text") or {}).get("value", ""))
    return ""


def _post_turn(
    runtime: Runtime, base_url: str, vars_: dict[str, Any], thread_id: str, prompt: str, timeout: int,
) -> str:
    """Post a conversation turn without repeating one that may already exist."""
    try:
        return _post_message(runtime, base_url, vars_, thread_id, prompt, timeout)
    except runtime._Retry as exc:
        if exc.status == 429:
            raise
        raise runtime._Final(
            f"{exc} (not asked again: the turn may already be in the conversation, and asking again "
            "would post it twice)"
        ) from exc


def _answer_posted_turn(
    runtime: Runtime, base_url: str, thread_id: str, assistant_id: str, timeout: int,
) -> dict[str, str]:
    """Answer a posted conversation turn without retrying a possible duplicate."""
    try:
        return _answer(runtime, base_url, thread_id, assistant_id, timeout)
    except runtime._Final:
        raise
    except Exception as exc:
        final = runtime._Final(
            f"{runtime._error_text(exc)} (not asked again: a retry would post this turn twice in the conversation)"
        )
        if isinstance(exc, runtime._Retry) and exc.delay is not None:
            final.wait = exc.delay
        raise final from exc


def _answer(
    runtime: Runtime, base_url: str, thread_id: str, assistant_id: str, timeout: int,
) -> dict[str, str]:
    thread = f"{base_url}/threads/{_segment(thread_id)}"
    run = runtime._authed_json(
        "POST",
        f"{thread}/runs?api-version={runtime.DATA_AGENT_API_VERSION}",
        timeout=timeout,
        json={"assistant_id": assistant_id},
    )
    _await_run(runtime, base_url, thread_id, run, timeout)
    messages = runtime._authed_json(
        "GET",
        f"{thread}/messages?order=asc&api-version={runtime.DATA_AGENT_API_VERSION}",
        timeout=timeout,
    )
    return {"output": _last_assistant_text(messages)}


def _run_once(
    runtime: Runtime, prompt: str, options: dict[str, Any], context: dict[str, Any],
) -> dict[str, str]:
    timeout = int(options.get("config", {}).get("timeout", 60))
    base_url = _base_url(runtime, options, context)
    vars_ = context.get("vars", {})
    own_thread = not _conversation_key(base_url, vars_)
    thread_id = ""
    try:
        url = f"{base_url}/assistants?api-version={runtime.DATA_AGENT_API_VERSION}"
        assistant_id = runtime._field(
            runtime._authed_json("POST", url, timeout=timeout, json={}), "id", url
        )
        thread_id = _thread_id(runtime, base_url, vars_, timeout)
        if own_thread:
            thread_id = _post_message(runtime, base_url, vars_, thread_id, prompt, timeout)
            return _answer(runtime, base_url, thread_id, assistant_id, timeout)
        thread_id = _post_turn(runtime, base_url, vars_, thread_id, prompt, timeout)
        return _answer_posted_turn(runtime, base_url, thread_id, assistant_id, timeout)
    finally:
        if own_thread and thread_id:
            with contextlib.suppress(Exception):
                runtime._authed_json(
                    "DELETE",
                    f"{base_url}/threads/{_segment(thread_id)}?api-version={runtime.DATA_AGENT_API_VERSION}",
                    timeout=timeout,
                )


def _report_progress(runtime: Runtime, prompt: str, started: float, result: dict[str, Any]) -> None:
    path = os.environ.get(runtime.PROGRESS_VAR)
    if not path:
        return
    entry = {"query": prompt, "seconds": round(time.monotonic() - started), "error": "error" in result}
    if "error" in result:
        entry["message"] = result["error"]
        if retry_after := (result.get("metadata") or {}).get("retry_after"):
            entry["retry_after"] = retry_after
    line = json.dumps(entry)
    with contextlib.suppress(OSError), runtime._PROGRESS_LOCK, open(path, "a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def _blocked_result(text: str, until: float) -> dict[str, Any]:
    return {
        "error": text,
        "metadata": {"retry_after": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(until))},
    }


def _block(
    runtime: Runtime, base_url: str, why: str, delay: float | None, *, for_run: bool = False,
) -> dict[str, Any]:
    until = runtime._now() + (delay or runtime._BLOCK_SECONDS_WITHOUT_HEADER)
    with runtime._THREAD_LOCK:
        runtime._BLOCKED[base_url] = (until, why, for_run)
    return _blocked_result(why, until)


def _still_blocked(runtime: Runtime, base_url: str) -> dict[str, Any] | None:
    with runtime._THREAD_LOCK:
        until, why, for_run = runtime._BLOCKED.get(base_url, (0.0, "", False))
    return _blocked_result(f"Not asked: {why}", until) if for_run or runtime._now() < until else None


def _final_result(runtime: Runtime, base_url: str, exc: RuntimeError) -> dict[str, Any]:
    if exc.wait is not None:
        return _block(runtime, base_url, runtime._redact(str(exc)), exc.wait)
    return {"error": runtime._redact(str(exc))}


def _call_api(
    runtime: Runtime, prompt: str, options: dict[str, Any], context: dict[str, Any],
) -> dict[str, Any]:
    """Retry one question in the single layer owned by the provider."""
    config = options.get("config", {})
    retries = int(config.get("max_retries", 3))
    retry_delay = float(config.get("retry_delay", 2))
    budget = float(config.get("timeout", 60))
    try:
        base_url = _base_url(runtime, options, context)
    except runtime._Final as exc:
        return {"error": runtime._redact(str(exc))}
    if blocked := _still_blocked(runtime, base_url):
        return blocked
    waited, last = False, ""
    for attempt in range(retries + 1):
        try:
            return _run_once(runtime, prompt, options, context)
        except runtime._Final as exc:
            return _final_result(runtime, base_url, exc)
        except runtime._Retry as exc:
            if exc.delay is not None:
                if waited or exc.delay > budget or attempt >= retries:
                    return _block(runtime, base_url, str(exc), exc.delay, for_run=waited)
                waited = True
                runtime._sleep(exc.delay)
                continue
            last = str(exc)
        except Exception as exc:  # noqa: BLE001 - promptfoo needs every failure as an error response
            last = runtime._error_text(exc)
        if attempt >= retries:
            return {"error": last}
        runtime._sleep(policy.backoff(attempt, retry_delay))
    raise AssertionError("unreachable")


def call_api(
    runtime: Runtime, prompt: str, options: dict[str, Any], context: dict[str, Any],
) -> dict[str, Any]:
    """Run one promptfoo provider call and persist its progress line."""
    started = time.monotonic()
    result = _call_api(runtime, prompt, options, context)
    _report_progress(runtime, prompt, started, result)
    return result
