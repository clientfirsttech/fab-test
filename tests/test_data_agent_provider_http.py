"""The Data Agent provider is polite to a throttled or failing Fabric (Polite HTTP epic, Data Agent Provider).

One test per failure class: how many requests it makes, how long it waits, and the sentence the caller
gets. Always mocked: the evidence is in tasks/archive/2026-11-22-polite-http-epic.md.
"""

from __future__ import annotations

import email.message
import http.client
import io
import json
import socket
import ssl
import urllib.error

import pytest

from tests.test_data_agent_provider import BASE, FakeAgent, _options, agent, no_env_file, provider

pytestmark = [pytest.mark.fab_test, pytest.mark.data_agent]
__all__ = ["agent", "no_env_file", "provider"]  # fixtures, used by name

NOW = 1_795_000_000.0  # 11:06:40 UTC


def _error(url, code, body=None, **headers):
    message = email.message.Message()
    for key, value in headers.items():
        message[key.replace("_", "-")] = str(value)
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    return urllib.error.HTTPError(url, code, "reason", hdrs=message, fp=io.BytesIO(payload))


def _blocked(url):
    return _error(url, 429, {"errorCode": "RequestBlocked", "isRetriable": True,
                             "message": "Request is blocked by the upstream service until: 11/22/2026 4:23:38 PM (UTC)",
                             },
                  Retry_After=16)


def _assistant_calls(agent: FakeAgent) -> int:
    return sum(1 for _method, url, _token in agent.calls if "/assistants?" in url)


def _raise(make):
    def raiser(url, _token):
        raise make(url)
    return raiser


@pytest.fixture
def clock(provider, monkeypatch):
    """The provider's wall clock and sleeps: sleeping moves the clock, so a block can expire."""
    state = {"now": NOW, "slept": []}

    def sleep(seconds):
        state["slept"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(provider, "_now", lambda: state["now"])
    monkeypatch.setattr(provider, "_sleep", sleep)
    provider._BLOCKED.clear()
    return state


# -- a server that names a wait ----------------------------------------------------------


def test_given_a_block_with_retry_after_should_wait_it_once_and_then_answer(provider, agent, clock):
    attempts = iter([True, False])
    agent.on_assistant = lambda url, _t: (_ for _ in ()).throw(_blocked(url)) if next(attempts) else None

    result = provider.call_api("q", _options(timeout=60, max_retries=3, retry_delay=2), {"vars": {}})

    assert result == {"output": "42"}
    assert _assistant_calls(agent) == 2
    assert clock["slept"][0] >= 16


def test_given_a_block_that_outlasts_one_wait_should_stop_asking_that_agent_for_the_run(provider, agent, clock):
    agent.on_assistant = _raise(_blocked)

    first = provider.call_api("q1", _options(timeout=60, max_retries=3, retry_delay=2), {"vars": {}})
    second = provider.call_api("q2", _options(timeout=60, max_retries=3, retry_delay=2), {"vars": {}})

    assert _assistant_calls(agent) == 2, "one request, one probe after Retry-After, then none"
    assert "RequestBlocked" in first["error"] and "until" in first["error"] and "{" not in first["error"]
    assert second["error"].startswith("Not asked: ") and "RequestBlocked" in second["error"]


def test_given_the_block_has_passed_should_probe_the_agent_again(provider, agent, clock):
    agent.on_assistant = _raise(_blocked)
    provider.call_api("q1", _options(timeout=60), {"vars": {}})
    agent.on_assistant = None
    clock["now"] += 600

    assert provider.call_api("q2", _options(timeout=60), {"vars": {}}) == {"output": "42"}


def test_given_a_wait_longer_than_the_budget_should_not_spend_the_budget_waiting(provider, agent, clock):
    agent.on_assistant = _raise(lambda url: _error(url, 429, {"errorCode": "RequestBlocked"}, Retry_After=120))

    result = provider.call_api("q", _options(timeout=30, max_retries=3), {"vars": {}})

    assert _assistant_calls(agent) == 1 and clock["slept"] == []
    assert "until 11:08:40 UTC" in result["error"]


def test_given_a_block_with_no_retry_after_should_still_wait_fabrics_minute(provider, agent, clock):
    agent.on_assistant = _raise(lambda url: _error(url, 429, {"errorCode": "RequestBlocked"}))

    provider.call_api("q", _options(timeout=120, max_retries=3), {"vars": {}})

    assert clock["slept"] == [60.0]


# -- final failures: one request ------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 404, 405, 409, 410, 422])
def test_given_a_final_status_should_report_it_after_one_request(provider, agent, clock, status):
    agent.on_assistant = _raise(lambda url: _error(url, status, {"errorCode": "SomeCode", "message": "It broke."}))

    result = provider.call_api("q", _options(max_retries=3), {"vars": {}})

    assert _assistant_calls(agent) == 1 and clock["slept"] == []
    assert f"api.fabric.microsoft.com answered HTTP {status} SomeCode: It broke." in result["error"]


def test_given_a_dns_failure_should_report_it_after_one_request_naming_the_host(provider, agent, clock):
    agent.on_assistant = _raise(lambda _url: urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")))

    result = provider.call_api("q", _options(max_retries=3), {"vars": {}})

    assert _assistant_calls(agent) == 1
    assert "cannot resolve api.fabric.microsoft.com" in result["error"] and "<urlopen" not in result["error"]


def test_given_an_untrusted_certificate_should_name_the_proxy_fix(provider, agent, clock):
    agent.on_assistant = _raise(lambda _url: urllib.error.URLError(
        ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate in chain")))

    result = provider.call_api("q", _options(max_retries=3), {"vars": {}})

    assert _assistant_calls(agent) == 1 and "SSL_CERT_FILE" in result["error"]


def test_given_a_token_endpoint_that_refuses_the_secret_should_not_ask_again(provider, monkeypatch, clock):
    asked = []

    def token_endpoint(method, url, **_kwargs):
        asked.append(url)
        raise _error(url, 401, {"error": "invalid_client", "error_description": "AADSTS7000215: Invalid secret."})

    monkeypatch.setattr(provider, "_http_json", token_endpoint)

    result = provider.call_api("q", _options(max_retries=3), {"vars": {}})

    assert len(asked) == 1 and "login.microsoftonline.com answered HTTP 401" in result["error"]


# -- transient failures: bounded backoff -----------------------------------------------------


@pytest.mark.parametrize("make", [
    lambda url: _error(url, 500, {"errorCode": "InternalError", "message": "Oops."}),
    lambda url: _error(url, 503, {}),
    lambda _url: urllib.error.URLError(ConnectionResetError(10054, "reset by peer")),
    lambda _url: TimeoutError("The read operation timed out"),
    lambda _url: http.client.IncompleteRead(b"partial"),
    lambda _url: ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
], ids=["500", "503-no-retry-after", "reset", "read-timeout", "incomplete-read", "tls-eof-on-read"])
def test_given_a_transient_failure_should_back_off_and_retry_within_the_attempts(provider, agent, clock, make):
    agent.on_assistant = _raise(make)

    result = provider.call_api("q", _options(max_retries=2, retry_delay=2), {"vars": {}})

    assert _assistant_calls(agent) == 3
    assert len(clock["slept"]) == 2 and clock["slept"][1] > clock["slept"][0] >= 2
    assert "api.fabric.microsoft.com" in result["error"] and "{" not in result["error"]


def test_given_a_server_error_with_retry_after_should_wait_at_least_that_long(provider, agent, clock):
    attempts = iter([True, False])
    agent.on_assistant = lambda url, _t: (
        (_ for _ in ()).throw(_error(url, 500, {"errorCode": "InternalError"}, Retry_After=7)) if next(attempts)
        else None)

    assert provider.call_api("q", _options(timeout=60, max_retries=3, retry_delay=2), {"vars": {}}) == {"output": "42"}
    assert clock["slept"][0] >= 7


# -- what came back was wrong -----------------------------------------------------------------


def test_given_a_2xx_body_that_is_not_json_should_say_so_and_not_ask_again(provider, monkeypatch):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(provider, "_urlopen", lambda _request, timeout: Response(b"<html>maintenance</html>"))

    with pytest.raises(provider._Final, match="not JSON") as raised:
        provider._http_json("GET", f"{BASE}/threads", token="tok-123")
    assert "<html>maintenance" in str(raised.value)


def test_given_a_run_that_fails_should_report_its_status_and_error_without_asking_again(provider, agent, clock):
    agent.run_status = ["failed"]
    agent.run_error = {"code": "server_error", "message": "The agent could not query the model."}

    result = provider.call_api("Lone", _options(max_retries=3), {"vars": {}})

    assert agent.messages_posted == 1
    assert "status 'failed'" in result["error"] and "could not query the model" in result["error"]
