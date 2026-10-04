"""Contract tests for the packaged Fabric Data Agent promptfoo provider.

Always mocked: no live token endpoint, no live Fabric agent.
"""

from __future__ import annotations

import json

import pytest


def _options(base_url: str = "https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/agent/aiassistant/openai"):
    return {"config": {"base_url": base_url, "timeout": 5, "max_retries": 1, "retry_delay": 0}}


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
                raise RuntimeError("No thread found with id thread-1 (404)")
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
    delete_calls = [url for method, url, _body in calls if method == "DELETE"]
    assert any("thread-1" in url for url in delete_calls)


@pytest.mark.fab_test
def test_call_api_redacts_credentials_in_error_responses(provider_module, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("secret super-secret-value leaked")

    monkeypatch.setattr(provider_module, "_http_json", _boom)

    result = provider_module.call_api("Nope", _options(), {"vars": {}})

    assert result["output"] == ""
    assert "super-secret-value" not in result["error"]
    assert "<redacted>" in result["error"]
