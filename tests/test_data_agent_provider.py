"""Contract tests for the packaged Fabric Data Agent promptfoo provider.

Always mocked: no live token endpoint, no live Fabric agent.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest


def _options(
    base_url: str = "https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/agent/aiassistant/openai",
    **overrides,
):
    return {
        "config": {
            "base_url": base_url,
            "timeout": 5,
            "max_retries": 1,
            "retry_delay": 0,
            **overrides,
        }
    }


def _http_error(url: str, *, code: int = 404, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "boom", hdrs=None, fp=io.BytesIO(body.encode("utf-8")))


@pytest.fixture
def provider_module(monkeypatch):
    from fab_test.scripts import fabric_data_agent_provider as provider

    provider._TOKEN_CACHE.clear()
    provider._THREAD_CACHE.clear()
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-id")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client-id")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setenv("FABRIC_SCOPE", "https://analysis.windows.net/powerbi/api/.default")
    monkeypatch.setattr(provider, "_sleep", lambda _seconds: None)
    return provider


@pytest.mark.fab_test
def test_call_api_runs_the_lifecycle_and_reuses_a_cached_token(provider_module, monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_http(method, url, **kwargs):
        calls.append((method, url))
        if "oauth2/v2.0/token" in url:
            return {"access_token": "token-1", "expires_in": 3600}
        if url.endswith("/assistants?api-version=2024-05-01-preview"):
            return {"id": "assistant-1"}
        if url.endswith("/threads?api-version=2024-05-01-preview"):
            return {"id": "thread-1"}
        if "/messages?api-version" in url and method == "POST":
            return {"id": "message-1"}
        if url.endswith("/runs?api-version=2024-05-01-preview"):
            return {"id": "run-1", "status": "queued"}
        if url.endswith("/runs/run-1?api-version=2024-05-01-preview"):
            return {"id": "run-1", "status": "completed"}
        if "/messages?order=asc" in url:
            return {
                "data": [
                    {"role": "assistant", "content": [{"type": "text", "text": {"value": "42"}}]}
                ]
            }
        if "/threads/thread-1?api-version" in url and method == "DELETE":
            return {}
        raise AssertionError(f"unexpected request: {method} {url} {kwargs}")

    monkeypatch.setattr(provider_module, "_http_json", _fake_http)

    first = provider_module.call_api("What is the answer?", _options(), {"vars": {}})
    second = provider_module.call_api("Ask again", _options(), {"vars": {}})

    assert first == {"output": "42"}
    assert second == {"output": "42"}
    token_calls = [url for _method, url in calls if "oauth2/v2.0/token" in url]
    assert len(token_calls) == 1


@pytest.mark.fab_test
def test_call_api_retries_transient_failures_before_returning_output(provider_module, monkeypatch):
    attempts = {"count": 0}

    def _fake_http(method, url, **kwargs):
        if "oauth2/v2.0/token" in url:
            return {"access_token": "token-1", "expires_in": 3600}
        if url.endswith("/assistants?api-version=2024-05-01-preview"):
            return {"id": "assistant-1"}
        if url.endswith("/threads?api-version=2024-05-01-preview"):
            return {"id": "thread-1"}
        if "/messages?api-version" in url and method == "POST":
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("temporary failure")
            return {"id": "message-1"}
        if url.endswith("/runs?api-version=2024-05-01-preview"):
            return {"id": "run-1", "status": "completed"}
        if "/messages?order=asc" in url:
            return {
                "data": [
                    {"role": "assistant", "content": [{"type": "text", "text": {"value": "ready"}}]}
                ]
            }
        if "/threads/thread-1?api-version" in url and method == "DELETE":
            return {}
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(provider_module, "_http_json", _fake_http)

    result = provider_module.call_api("Retry me", _options(), {"vars": {}})

    assert result == {"output": "ready"}
    assert attempts["count"] == 2


@pytest.mark.fab_test
def test_call_api_reuses_resets_and_recreates_conversation_threads(provider_module, monkeypatch):
    calls: list[tuple[str, str, str]] = []
    state = {"thread_creations": 0, "message_posts": 0}

    def _fake_http(method, url, **kwargs):
        body = kwargs.get("json")
        calls.append((method, url, json.dumps(body, sort_keys=True) if body is not None else ""))
        if "oauth2/v2.0/token" in url:
            return {"access_token": "token-1", "expires_in": 3600}
        if url.endswith("/assistants?api-version=2024-05-01-preview"):
            return {"id": "assistant-1"}
        if url.endswith("/threads?api-version=2024-05-01-preview"):
            state["thread_creations"] += 1
            return {"id": f"thread-{state['thread_creations']}"}
        if "/messages?api-version" in url and method == "POST":
            state["message_posts"] += 1
            if state["message_posts"] == 2:
                raise _http_error(url, body='{"error":"No thread found with id thread-1"}')
            return {"id": "message-1"}
        if "/runs?api-version=2024-05-01-preview" in url:
            return {"id": "run-1", "status": "completed"}
        if "/messages?order=asc" in url:
            return {
                "data": [
                    {"role": "assistant", "content": [{"type": "text", "text": {"value": "ok"}}]}
                ]
            }
        if "/threads/thread-" in url and method == "DELETE":
            return {}
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(provider_module, "_http_json", _fake_http)

    one = provider_module.call_api(
        "Turn one",
        _options(),
        {"vars": {"conversation": "sales", "reset": True}},
    )
    two = provider_module.call_api(
        "Turn two",
        _options(),
        {"vars": {"conversation": "sales"}},
    )

    assert one == {"output": "ok"}
    assert two == {"output": "ok"}
    assert state["thread_creations"] == 2
    assert (
        provider_module._THREAD_CACHE[
            "https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/agent/aiassistant/openai::sales"
        ]
        == "thread-2"
    )


@pytest.mark.fab_test
def test_call_api_redacts_credentials_in_error_responses(provider_module, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("secret super-secret-value leaked Authorization: ******")

    monkeypatch.setattr(provider_module, "_http_json", _boom)

    result = provider_module.call_api("Nope", _options(), {"vars": {}})

    assert result == {"error": result["error"]}
    assert "super-secret-value" not in result["error"]
    assert "<redacted>" in result["error"]


@pytest.mark.fab_test
def test_call_api_uses_https_only(provider_module):
    result = provider_module.call_api("Nope", _options(base_url="http://example.test/agent"), {"vars": {}})

    assert set(result) == {"error"}
    assert "https" in result["error"].lower()


@pytest.mark.fab_test
def test_call_api_refreshes_token_when_margin_is_reached(provider_module, monkeypatch):
    scope = "https://analysis.windows.net/powerbi/api/.default"
    provider_module._TOKEN_CACHE[provider_module._token_cache_key(scope)] = (
        "stale-token",
        provider_module._now() + 300,
    )
    calls: list[str] = []

    def _fake_http(method, url, **kwargs):
        calls.append(url)
        assert method == "POST"
        return {"access_token": "fresh-token", "expires_in": 3600}

    monkeypatch.setattr(provider_module, "_http_json", _fake_http)

    token = provider_module._get_token()

    assert token == "fresh-token"
    assert calls == [provider_module._token_url()]


@pytest.mark.fab_test
def test_call_api_refreshes_the_token_once_after_a_401(provider_module, monkeypatch):
    calls: list[tuple[str, str, str]] = []

    def _fake_http(method, url, **kwargs):
        token = kwargs.get("token", "")
        calls.append((method, url, token))
        if "oauth2/v2.0/token" in url:
            return {
                "access_token": "token-1" if len([c for c in calls if "oauth2/v2.0/token" in c[1]]) == 1 else "token-2",
                "expires_in": 3600,
            }
        if url.endswith("/assistants?api-version=2024-05-01-preview"):
            if token == "token-1":
                raise _http_error(url, code=401, body='{"error":"expired"}')
            return {"id": "assistant-1"}
        if url.endswith("/threads?api-version=2024-05-01-preview"):
            return {"id": "thread-1"}
        if "/messages?api-version" in url and method == "POST":
            return {"id": "message-1"}
        if url.endswith("/runs?api-version=2024-05-01-preview"):
            return {"id": "run-1", "status": "completed"}
        if "/messages?order=asc" in url:
            return {
                "data": [
                    {"role": "assistant", "content": [{"type": "text", "text": {"value": "refreshed"}}]}
                ]
            }
        if "/threads/thread-1?api-version" in url and method == "DELETE":
            return {}
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(provider_module, "_http_json", _fake_http)

    result = provider_module.call_api("Refresh me", _options(max_retries=0), {"vars": {}})

    assert result == {"output": "refreshed"}
    token_calls = [url for _method, url, _token in calls if "oauth2/v2.0/token" in url]
    assert len(token_calls) == 2


@pytest.mark.fab_test
def test_call_api_times_out_and_deletes_non_conversation_threads(provider_module, monkeypatch):
    calls: list[tuple[str, str]] = []
    marks = iter([0.0, 6.0])

    def _fake_http(method, url, **kwargs):
        calls.append((method, url))
        if "oauth2/v2.0/token" in url:
            return {"access_token": "token-1", "expires_in": 3600}
        if url.endswith("/assistants?api-version=2024-05-01-preview"):
            return {"id": "assistant-1"}
        if url.endswith("/threads?api-version=2024-05-01-preview"):
            return {"id": "thread-1"}
        if "/messages?api-version" in url and method == "POST":
            return {"id": "message-1"}
        if url.endswith("/runs?api-version=2024-05-01-preview"):
            return {"id": "run-1", "status": "queued"}
        if url.endswith("/runs/run-1?api-version=2024-05-01-preview"):
            return {"id": "run-1", "status": "queued"}
        if "/threads/thread-1?api-version" in url and method == "DELETE":
            return {}
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(provider_module, "_http_json", _fake_http)
    monkeypatch.setattr(provider_module, "_monotonic", lambda: next(marks))

    result = provider_module.call_api("Wait forever", _options(timeout=5, max_retries=0), {"vars": {}})

    assert set(result) == {"error"}
    assert "timed out" in result["error"].lower()
    assert any(method == "DELETE" and "thread-1" in url for method, url in calls)


@pytest.mark.fab_test
def test_call_api_reports_non_completed_runs(provider_module, monkeypatch):
    def _fake_http(method, url, **kwargs):
        if "oauth2/v2.0/token" in url:
            return {"access_token": "token-1", "expires_in": 3600}
        if url.endswith("/assistants?api-version=2024-05-01-preview"):
            return {"id": "assistant-1"}
        if url.endswith("/threads?api-version=2024-05-01-preview"):
            return {"id": "thread-1"}
        if "/messages?api-version" in url and method == "POST":
            return {"id": "message-1"}
        if url.endswith("/runs?api-version=2024-05-01-preview"):
            return {"id": "run-1", "status": "failed"}
        if "/threads/thread-1?api-version" in url and method == "DELETE":
            return {}
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(provider_module, "_http_json", _fake_http)

    result = provider_module.call_api("Fail me", _options(max_retries=0), {"vars": {}})

    assert set(result) == {"error"}
    assert "status 'failed'" in result["error"]
