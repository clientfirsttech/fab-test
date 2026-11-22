"""How the Data Agent provider fails: what it retries, what it never retries, and what it cleans up.

Review 2 should-fix 8 and 11 (Review 1 items 14 and 17). Always mocked: no live token endpoint or agent.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from tests.test_data_agent_provider import BASE, FakeAgent, _http_error, _options, agent, no_env_file, provider

pytestmark = [pytest.mark.fab_test, pytest.mark.data_agent]
__all__ = ["agent", "no_env_file", "provider"]  # fixtures, used by name


def _fabric_error(url, code, error_code, *, retriable=False):
    body = json.dumps({"requestId": "r-1", "errorCode": error_code, "message": f"{error_code} happened",
                       "isRetriable": retriable})
    return _http_error(url, code=code, body=body)


def _assistant_calls(agent: FakeAgent) -> int:
    return sum(1 for _method, url, _token in agent.calls if "/assistants?" in url)


# -- what is never retried ---------------------------------------------------------


def test_given_fabric_says_an_error_is_not_retriable_should_report_it_at_once(provider, agent):
    agent.on_assistant = lambda url, _token: (_ for _ in ()).throw(_fabric_error(url, 409, "ItemLocked"))

    result = provider.call_api("q", _options(max_retries=3), {"vars": {}})

    assert _assistant_calls(agent) == 1
    assert "ItemLocked" in result["error"] and "ItemLocked happened" in result["error"]


def test_given_a_retriable_fabric_error_should_still_retry(provider, agent):
    agent.on_assistant = lambda url, _token: (_ for _ in ()).throw(
        _fabric_error(url, 429, "TooManyRequests", retriable=True))

    provider.call_api("q", _options(max_retries=2), {"vars": {}})

    assert _assistant_calls(agent) == 3


def test_given_a_paused_capacity_should_say_to_resume_it_and_not_retry(provider, agent):
    agent.on_assistant = lambda url, _token: (_ for _ in ()).throw(_fabric_error(url, 404, "CapacityNotActive"))

    result = provider.call_api("q", _options(max_retries=3), {"vars": {}})

    assert _assistant_calls(agent) == 1
    assert "CapacityNotActive" in result["error"] and "resume" in result["error"].lower()


def test_given_a_run_that_times_out_should_not_ask_again(provider, agent, monkeypatch):
    """A retry would wait the whole timeout again: one test could take 4 x --timeout."""
    agent.run_status = ["queued"]
    clock = iter(range(0, 1000, 6))
    monkeypatch.setattr(provider, "_monotonic", lambda: float(next(clock)))

    result = provider.call_api("Wait forever", _options(timeout=5, max_retries=3), {"vars": {}})

    assert "timed out" in result["error"].lower()
    assert agent.messages_posted == 1


def test_given_a_conversation_should_never_post_its_turn_twice(provider, agent):
    """A retry after the post would put the same user turn on the shared thread again."""
    agent.run_status = ["failed"]

    result = provider.call_api("Turn one", _options(max_retries=3), {"vars": {"conversation": "c", "reset": True}})

    assert "status 'failed'" in result["error"]
    assert agent.messages_posted == 1


def test_given_a_lone_question_whose_run_fails_should_report_it_and_not_ask_again(provider, agent):
    """A failed, cancelled or expired run is the agent's verdict, not a transient fault (Polite HTTP decision 5)."""
    agent.run_status = ["failed"]

    result = provider.call_api("Lone", _options(max_retries=1), {"vars": {}})

    assert "status 'failed'" in result["error"]
    assert agent.messages_posted == 1 and agent.threads_created == 1


# -- cleanup -------------------------------------------------------------------------


def test_given_the_post_fails_should_still_delete_the_thread_it_created(provider, agent):
    def refuse(_url, _posted):
        raise RuntimeError("post failed")

    agent.on_message = refuse

    provider.call_api("q", _options(max_retries=0), {"vars": {}})

    assert agent.deleted() == [f"{BASE}/threads/thread-1?api-version=2024-05-01-preview"]


# -- where the token goes ------------------------------------------------------------


def test_given_any_request_should_go_through_the_opener_that_refuses_redirects(provider, monkeypatch):
    """A revert to urllib.request.urlopen would follow a redirect with the token."""
    assert any(isinstance(handler, provider._RefuseRedirects) for handler in provider._OPENER.handlers)
    opened = []

    class Opener:
        def open(self, request, timeout):
            opened.append(request.full_url)
            raise OSError("stop here")

    monkeypatch.setattr(provider, "_OPENER", Opener())
    with pytest.raises(OSError, match="stop here"):
        provider._http_json("GET", f"{BASE}/threads", token="tok-123")
    assert opened == [f"{BASE}/threads"]


def test_given_user_info_on_a_fabric_host_should_refuse_it(provider, monkeypatch):
    sent = []
    monkeypatch.setattr(provider, "_urlopen", lambda request, timeout: sent.append(request))

    with pytest.raises(provider._Final, match="user info") as raised:
        provider._http_json("GET", "https://me:pw@api.fabric.microsoft.com/v1/x", token="tok-123")
    assert sent == [] and "pw" not in str(raised.value)


def test_the_opener_is_a_urllib_opener():
    from fab_test.scripts import fabric_data_agent_provider as module

    assert isinstance(module._OPENER, urllib.request.OpenerDirector)
