"""Contract tests for the packaged Fabric Data Agent promptfoo provider.

Always mocked: no live token endpoint, no live Fabric agent. Ported from
PR #49, plus what it missed: promptfoo loads the provider by file path, and
credentials come from fab-test's own service-principal resolution.
"""

from __future__ import annotations

import importlib.util
import io
import urllib.error
from pathlib import Path

import pytest

pytestmark = [pytest.mark.fab_test, pytest.mark.data_agent]

BASE = "https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/agent/aiassistant/openai"
API = "api-version=2024-05-01-preview"
SECRET = "super-secret-value"
_SP_VARS = (
    "FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
    "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET",
)


def _options(base_url: str = BASE, **overrides):
    return {"config": {"base_url": base_url, "timeout": 5, "max_retries": 1, "retry_delay": 0, **overrides}}


def _http_error(url: str, *, code: int = 404, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "boom", hdrs=None, fp=io.BytesIO(body.encode("utf-8")))


class FakeAgent:
    """The token endpoint and the agent's Assistants API, answering as a healthy agent does.

    Tests change one behaviour by setting an attribute: ``run_status`` (what each run reports, in
    order), ``on_message`` / ``on_assistant`` (raise or not, given the call), ``reply``.
    """

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []
        self.tokens_issued = 0
        self.threads_created = 0
        self.messages_posted = 0
        self.run_status = ["completed"]
        self.reply = "42"
        self.on_message = None
        self.on_assistant = None

    def __call__(self, method, url, **kwargs):
        token = kwargs.get("token", "")
        self.calls.append((method, url, token))
        if "oauth2/v2.0/token" in url:
            self.tokens_issued += 1
            return {"access_token": f"token-{self.tokens_issued}", "expires_in": 3600}
        if url.endswith(f"/assistants?{API}"):
            if self.on_assistant:
                self.on_assistant(url, token)
            return {"id": "assistant-1"}
        if url.endswith(f"/threads?{API}"):
            self.threads_created += 1
            return {"id": f"thread-{self.threads_created}"}
        if f"/messages?{API}" in url and method == "POST":
            self.messages_posted += 1
            if self.on_message:
                self.on_message(url, self.messages_posted)
            return {"id": "message-1"}
        if url.endswith(f"/runs?{API}"):
            return {"id": "run-1", "status": self.run_status[0]}
        if url.endswith(f"/runs/run-1?{API}"):
            return {"id": "run-1", "status": self.run_status[-1]}
        if "/messages?order=asc" in url:
            return {"data": [{"role": "assistant", "content": [{"type": "text", "text": {"value": self.reply}}]}]}
        if "/threads/thread-" in url and method == "DELETE":
            return {}
        raise AssertionError(f"unexpected request: {method} {url}")

    def deleted(self) -> list[str]:
        return [url for method, url, _ in self.calls if method == "DELETE"]


@pytest.fixture
def no_env_file(monkeypatch, tmp_path):
    """No service principal from anywhere: not the environment, not the repo's own .fab-test/.env."""
    for var in _SP_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(tmp_path / "absent.env"))
    return tmp_path


@pytest.fixture
def provider(monkeypatch, no_env_file):
    from fab_test.scripts import fabric_data_agent_provider as module

    module._TOKEN_CACHE.clear()
    module._THREAD_CACHE.clear()
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-id")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client-id")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", SECRET)
    monkeypatch.delenv("FABRIC_SCOPE", raising=False)
    monkeypatch.setattr(module, "_sleep", lambda _seconds: None)
    return module


@pytest.fixture
def agent(provider, monkeypatch):
    fake = FakeAgent()
    monkeypatch.setattr(provider, "_http_json", fake)
    return fake


# -- promptfoo's loader ------------------------------------------------------


def test_given_promptfoos_loader_should_import_the_provider_by_file_path():
    """promptfoo 0.124.0 (dist/src/python/wrapper.py) loads a provider with
    spec_from_file_location(<file stem>, path): no parent package, so a relative import fails."""
    from fab_test.scripts import fabric_data_agent_provider as packaged

    path = Path(packaged.__file__)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert callable(module.call_api)


# -- the lifecycle -----------------------------------------------------------


def test_given_a_prompt_should_run_the_lifecycle_delete_the_thread_and_reuse_the_token(provider, agent):
    agent.run_status = ["queued", "completed"]

    first = provider.call_api("What is the answer?", _options(), {"vars": {}})
    second = provider.call_api("Ask again", _options(), {"vars": {}})

    assert first == second == {"output": "42"}
    assert agent.tokens_issued == 1
    assert len(agent.deleted()) == 2


def test_given_a_transient_failure_should_retry_and_return_the_output(provider, agent):
    def fail_first(url, posted):
        if posted == 1:
            raise RuntimeError("temporary failure")

    agent.on_message = fail_first
    agent.reply = "ready"

    assert provider.call_api("Retry me", _options(), {"vars": {}}) == {"output": "ready"}
    assert agent.messages_posted == 2


def test_given_a_conversation_should_reuse_reset_and_recreate_its_thread(provider, agent):
    def thread_gone_on_second(url, posted):
        if posted == 2:
            raise _http_error(url, body='{"error":"No thread found with id thread-1"}')

    agent.on_message = thread_gone_on_second

    one = provider.call_api("Turn one", _options(), {"vars": {"conversation": "sales", "reset": True}})
    two = provider.call_api("Turn two", _options(), {"vars": {"conversation": "sales"}})

    assert one == two == {"output": "42"}
    assert agent.threads_created == 2
    assert provider._THREAD_CACHE[f"{BASE}::sales"] == "thread-2"
    assert agent.deleted() == []  # a conversation's thread outlives the turn


def test_given_a_run_that_never_finishes_should_time_out_and_still_delete_the_thread(provider, agent, monkeypatch):
    agent.run_status = ["queued"]
    marks = iter([0.0, 6.0])
    monkeypatch.setattr(provider, "_monotonic", lambda: next(marks))

    result = provider.call_api("Wait forever", _options(timeout=5, max_retries=0), {"vars": {}})

    assert "timed out" in result["error"].lower()
    assert agent.deleted()


def test_given_a_failed_run_should_name_its_status(provider, agent):
    agent.run_status = ["failed"]

    result = provider.call_api("Fail me", _options(max_retries=0), {"vars": {}})

    assert "status 'failed'" in result["error"]


def test_given_an_http_url_should_refuse_it(provider, agent):
    result = provider.call_api("Nope", _options(base_url="http://example.test/agent"), {"vars": {}})

    assert set(result) == {"error"}
    assert "https" in result["error"]
    assert agent.calls == []


# -- where the token may go (decision 17) --------------------------------------


@pytest.mark.parametrize("agent_url", [
    "https://evil.example/agent",
    "https://api.fabric.microsoft.com.evil.example/agent",
    "https://evilfabric.microsoft.com/agent",
    "https://user@evil.example/agent",
], ids=["foreign", "suffix-spoof", "no-dot-boundary", "userinfo"])
def test_given_a_base_url_off_the_fabric_hosts_should_refuse_it_before_any_token(provider, agent, agent_url):
    result = provider.call_api("q", _options(base_url=agent_url), {"vars": {}})

    assert set(result) == {"error"}
    assert "FAB_TEST_DATA_AGENT_ALLOWED_HOSTS" in result["error"]
    assert agent.calls == []  # no token requested, none sent


@pytest.mark.parametrize("agent_url", [
    BASE,
    "https://westus.fabric.microsoft.com/v1/x",
    "https://wabi-west-us.analysis.windows.net.powerbi.com/x",
    "https://API.Fabric.Microsoft.com/v1/x",
], ids=["api", "regional", "powerbi", "case"])
def test_given_a_fabric_or_power_bi_host_should_accept_it(provider, agent_url):
    assert provider._validated_base_url(agent_url) == agent_url.rstrip("/")


def test_given_a_host_allowed_by_the_callers_environment_should_call_it(provider, monkeypatch):
    monkeypatch.setenv("FAB_TEST_DATA_AGENT_ALLOWED_HOSTS", " gateway.contoso.example , other.example")

    assert provider._validated_base_url("https://Gateway.Contoso.Example/agent/") == (
        "https://Gateway.Contoso.Example/agent"
    )
    with pytest.raises(provider._Final):
        provider._validated_base_url("https://sub.gateway.contoso.example/agent")  # exact hosts only


def test_given_a_bearer_request_to_a_foreign_host_should_refuse_without_sending(provider, monkeypatch):
    sent = []
    monkeypatch.setattr(provider, "_urlopen", lambda request, timeout: sent.append(request))

    with pytest.raises(provider._Final, match=r"evil\.example"):
        provider._http_json("GET", "https://evil.example/threads", token="tok-123")
    assert sent == []


def test_given_a_redirect_should_refuse_to_follow_it_with_the_token(provider):
    import urllib.request

    request = urllib.request.Request(f"{BASE}/threads", headers={"Authorization": "Bearer tok-123"})  # noqa: S310
    handler = provider._RefuseRedirects()

    with pytest.raises(provider._Final, match="redirect") as raised:
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/steal")
    assert "evil.example" in str(raised.value)
    assert "tok-123" not in str(raised.value)


def test_given_server_issued_ids_should_quote_them_into_the_path(provider, agent, monkeypatch):
    odd, quoted = "../../evil?x=", "..%2F..%2Fevil%3Fx%3D"
    urls = []

    def odd_thread_ids(method, url, **kwargs):
        urls.append(url)
        if url.endswith(f"/threads?{API}"):
            return {"id": odd}
        return agent(method, url.replace(quoted, "thread-1"), **kwargs)

    monkeypatch.setattr(provider, "_http_json", odd_thread_ids)

    assert provider.call_api("q", _options(), {"vars": {}}) == {"output": "42"}
    assert any(quoted in url for url in urls)
    assert not any(odd in url for url in urls)


@pytest.mark.parametrize("vars_", [
    {"agent": "sales"},
    {"query": "sales|||What were sales last month?"},
], ids=["vars.agent", "key|||question"])
def test_given_the_templates_fabric_urls_should_route_to_the_named_agent(provider, agent, vars_):
    options = {"config": {"fabric_urls": {"sales": BASE + "/", "hr": "https://elsewhere.test/x"},
                          "max_retries": 0}}

    assert provider.call_api("q", options, {"vars": vars_}) == {"output": "42"}
    assert all(url.startswith(BASE) for _m, url, _t in agent.calls if "oauth2" not in url)


def test_given_no_agent_url_should_say_which_keys_set_one(provider, agent):
    result = provider.call_api("q", {"config": {"max_retries": 3}}, {"vars": {}})

    assert "base_url" in result["error"] and "fabric_urls" in result["error"]
    assert agent.calls == []


def test_given_a_server_error_should_retry_then_report_its_status_and_body(provider, agent):
    def unavailable(url, token):
        raise _http_error(url, code=503, body="Service Unavailable")

    agent.on_assistant = unavailable

    result = provider.call_api("q", _options(max_retries=2), {"vars": {}})

    assert result == {"error": "HTTP 503: Service Unavailable"}
    assert sum(1 for _m, url, _t in agent.calls if url.endswith(f"/assistants?{API}")) == 3


def test_given_a_request_should_send_json_with_the_bearer_token(provider, monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"id": "thread-9"}'

    def urlopen(request, timeout):
        seen.update(method=request.get_method(), url=request.full_url, body=request.data,
                    auth=request.get_header("Authorization"), timeout=timeout)
        return Response()

    monkeypatch.setattr(provider, "_urlopen", urlopen)

    result = provider._http_json("POST", f"{BASE}/threads?{API}", token="tok-123", timeout=7, json={"a": 1})

    assert result == {"id": "thread-9"}
    assert seen == {"method": "POST", "url": f"{BASE}/threads?{API}", "body": b'{"a": 1}',
                    "auth": "Bearer tok-123", "timeout": 7}


# -- tokens ------------------------------------------------------------------


def test_given_a_token_within_the_refresh_margin_should_fetch_a_new_one(provider, agent):
    scope = "https://analysis.windows.net/powerbi/api/.default"
    provider._TOKEN_CACHE[provider._token_cache_key(scope)] = ("stale-token", provider._now() + 300)

    assert provider._get_token() == "token-1"
    assert agent.tokens_issued == 1


def test_given_a_401_should_refresh_the_token_once_and_carry_on(provider, agent):
    def reject_first_token(url, token):
        if token == "token-1":
            raise _http_error(url, code=401, body='{"error":"expired"}')

    agent.on_assistant = reject_first_token

    assert provider.call_api("Refresh me", _options(max_retries=0), {"vars": {}}) == {"output": "42"}
    assert agent.tokens_issued == 2


def test_given_a_401_after_refreshing_should_name_a_rejected_token_and_not_retry(provider, agent):
    def reject_every_token(url, token):
        raise _http_error(url, code=401, body='{"error":"InvalidAuthenticationToken"}')

    agent.on_assistant = reject_every_token

    result = provider.call_api("Who am I", _options(max_retries=3), {"vars": {}})

    assert "rejected the token (HTTP 401)" in result["error"]
    assert "fab-test auth status" in result["error"]
    assert agent.tokens_issued == 2  # one refresh, then no retries: a retry can't fix authentication


def test_given_a_403_should_name_the_access_it_needs_and_not_retry(provider, agent):
    def forbid(url, token):
        raise _http_error(url, code=403, body='{"error":"Forbidden"}')

    agent.on_assistant = forbid

    result = provider.call_api("May I", _options(max_retries=3), {"vars": {}})

    assert "HTTP 403" in result["error"]
    assert "workspace" in result["error"]
    assert agent.tokens_issued == 1


# -- credentials -------------------------------------------------------------


def test_given_no_service_principal_should_name_the_variables_and_call_nothing(provider, agent, monkeypatch):
    for var in _SP_VARS:
        monkeypatch.delenv(var, raising=False)

    result = provider.call_api("Hello", _options(max_retries=3), {"vars": {}})

    for var in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET", "fab-test auth status"):
        assert var in result["error"]
    assert agent.calls == []


def test_given_part_of_a_service_principal_should_name_what_is_missing(provider, agent, monkeypatch):
    monkeypatch.delenv("FABRIC_CLIENT_SECRET")

    result = provider.call_api("Hello", _options(max_retries=3), {"vars": {}})

    assert "partially configured" in result["error"]
    assert "FABRIC_SERVICE_PRINCIPAL_SECRET" in result["error"]
    assert agent.calls == []


def test_given_a_service_principal_in_an_env_file_should_use_it_and_redact_its_secret(
    provider, monkeypatch, no_env_file
):
    file_secret = "secret-from-env-file"
    env_file = no_env_file / "sp.env"
    env_file.write_text(
        f"FABRIC_TENANT_ID=t\nFABRIC_SERVICE_PRINCIPAL_ID=c\nFABRIC_SERVICE_PRINCIPAL_SECRET={file_secret}\n",
        encoding="utf-8",
    )
    for var in _SP_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(env_file))
    sent = {}

    def echo_secret(method, url, **kwargs):
        sent.update(kwargs)
        raise RuntimeError(f"token endpoint said: bad client_secret {file_secret}")

    monkeypatch.setattr(provider, "_http_json", echo_secret)

    result = provider.call_api("Hello", _options(max_retries=0), {"vars": {}})

    assert file_secret.encode() in sent["data"]  # the file's principal was the one used
    assert file_secret not in result["error"]
    assert "<redacted>" in result["error"]


def test_given_an_error_carrying_the_secret_or_a_token_should_redact_both(provider, agent):
    def leak(url, posted):
        raise RuntimeError(f"secret {SECRET} and Authorization: Bearer token-1 leaked")

    agent.on_message = leak

    result = provider.call_api("Nope", _options(max_retries=0), {"vars": {}})

    assert SECRET not in result["error"]
    assert "token-1" not in result["error"]


# -- progress, so a minute of live calls never looks hung (follow-up 18) ---------------


def test_each_answer_is_reported_to_the_progress_file_as_it_lands(provider, agent, monkeypatch, tmp_path):
    import json

    progress = tmp_path / "progress.jsonl"
    monkeypatch.setenv("FAB_TEST_DATA_AGENT_PROGRESS", str(progress))
    agent.run_status = ["failed"]

    provider.call_api("How many?", _options(), {"vars": {}})
    agent.run_status = ["completed"]
    provider.call_api("And now?", _options(), {"vars": {}})

    lines = [json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()]
    assert [(line["query"], line["error"]) for line in lines] == [("How many?", True), ("And now?", False)]
    assert all(isinstance(line["seconds"], int) for line in lines)
    assert SECRET not in progress.read_text(encoding="utf-8")


def test_without_a_progress_file_nothing_is_written(provider, agent, monkeypatch, tmp_path):
    monkeypatch.delenv("FAB_TEST_DATA_AGENT_PROGRESS", raising=False)
    monkeypatch.chdir(tmp_path)
    assert provider.call_api("How many?", _options(), {"vars": {}}) == {"output": "42"}
    assert list(tmp_path.iterdir()) == []
