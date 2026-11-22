"""Data Agent runs as the developer's az login identity (Data Agent az login epic).

Always mocked: AzureCliCredential is replaced, so no `az` process runs and no token is issued.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import ClassVar

import pytest

from fab_test.scripts import _credentials
from fab_test.scripts import invoke_data_agent as wrapper

pytestmark = [pytest.mark.fab_test, pytest.mark.data_agent]

SCOPE = "https://analysis.windows.net/powerbi/api/.default"
_REAL_CLI_CREDENTIAL = _credentials._cli_credential  # conftest refuses it; fake_cli restores it over a fake class
_SP_VARS = ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
            "FABRIC_SERVICE_PRINCIPAL_ID", "FABRIC_SERVICE_PRINCIPAL_SECRET")


class _FakeCli:
    """AzureCliCredential's surface: get_token(scope) -> AccessToken, or the SDK's exceptions."""

    made: ClassVar[list[dict]] = []
    error: ClassVar[Exception | None] = None
    scopes: ClassVar[list[str]] = []

    def __init__(self, **kwargs):
        _FakeCli.made.append(kwargs)

    def get_token(self, scope):
        _FakeCli.scopes.append(scope)
        if _FakeCli.error is not None:
            raise _FakeCli.error
        from azure.core.credentials import AccessToken

        return AccessToken("az-cli-token-value", 1_900_000_000)


@pytest.fixture
def fake_cli(monkeypatch):
    import azure.identity

    _FakeCli.made, _FakeCli.error, _FakeCli.scopes = [], None, []
    monkeypatch.setattr(azure.identity, "AzureCliCredential", _FakeCli)
    monkeypatch.setattr(_credentials, "_cli_credential", _REAL_CLI_CREDENTIAL)
    return _FakeCli


@pytest.fixture
def no_principal(monkeypatch, tmp_path):
    for var in (*_SP_VARS, _credentials.DATA_AGENT_AUTH_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(tmp_path / "absent.env"))


@pytest.fixture
def principal(monkeypatch, no_principal):
    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-id")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client-id")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "private-secret-value")


# -- the shared az token ------------------------------------------------------


def test_given_az_is_signed_in_should_return_its_token_and_expiry(fake_cli):
    assert _credentials.azure_cli_token(SCOPE) == ("az-cli-token-value", 1_900_000_000.0)
    assert fake_cli.scopes == [SCOPE]
    assert fake_cli.made[0]["process_timeout"] >= 30  # a cold az on Windows takes seconds


@pytest.mark.parametrize("reason", ["Please run 'az login' to set up an account", "Azure CLI not found on path"])
def test_given_az_is_not_signed_in_should_say_az_login_in_one_sentence(fake_cli, reason):
    from azure.identity import CredentialUnavailableError

    fake_cli.error = CredentialUnavailableError(reason)
    with pytest.raises(_credentials.AzureCliSignInError) as raised:
        _credentials.azure_cli_token(SCOPE)
    message = str(raised.value)
    assert reason in message and "Run `az login`" in message and "\n" not in message


def test_given_az_reports_an_authentication_error_should_keep_its_reason(fake_cli):
    from azure.core.exceptions import ClientAuthenticationError

    fake_cli.error = ClientAuthenticationError("AADSTS700082: The refresh token has expired.\nTrace ID: x")
    with pytest.raises(_credentials.AzureCliSignInError, match=r"AADSTS700082.*Run `az login`") as raised:
        _credentials.azure_cli_token(SCOPE)
    assert "\n" not in str(raised.value)


@pytest.mark.parametrize("requested,configured,expected", [
    ("az", True, "az"),
    ("az", False, "az"),
    ("service-principal", True, "service-principal"),
    ("", True, "service-principal"),
    ("", False, "az"),
])
def test_auth_mode_follows_the_chain_unless_asked(monkeypatch, no_principal, requested, configured, expected):
    if configured:
        monkeypatch.setenv("FABRIC_TENANT_ID", "t")
        monkeypatch.setenv("FABRIC_CLIENT_ID", "c")
        monkeypatch.setenv("FABRIC_CLIENT_SECRET", "s-secret-value")
    assert _credentials.data_agent_auth(requested) == expected


def test_auth_mode_refuses_a_half_set_principal_unless_az_is_asked(monkeypatch, no_principal):
    monkeypatch.setenv("FABRIC_TENANT_ID", "t")
    with pytest.raises(_credentials.IncompleteServicePrincipalError):
        _credentials.data_agent_auth("")
    assert _credentials.data_agent_auth("az") == "az"


def test_asking_for_a_service_principal_that_is_not_set_should_refuse(no_principal):
    with pytest.raises(_credentials.IncompleteServicePrincipalError, match="FABRIC_TENANT_ID"):
        _credentials.data_agent_auth("service-principal")


# -- the provider -------------------------------------------------------------


@pytest.fixture
def provider(monkeypatch):
    from fab_test.scripts import fabric_data_agent_provider as module

    module._TOKEN_CACHE.clear()
    module._THREAD_CACHE.clear()
    module._BLOCKED.clear()
    monkeypatch.setattr(module, "_sleep", lambda _seconds: None)
    return module


def _agent(provider, monkeypatch, *, status=None):
    calls = []

    def http_json(method, url, **kwargs):
        calls.append((method, url, kwargs.get("token")))
        if "oauth2" in url:
            raise AssertionError("az mode must not call the token endpoint")
        if status is not None and url.endswith("/assistants?api-version=2024-05-01-preview"):
            import io
            import urllib.error

            raise urllib.error.HTTPError(url, status, "no", hdrs=None, fp=io.BytesIO(b"{}"))
        if url.endswith("/assistants?api-version=2024-05-01-preview"):
            return {"id": "assistant-1"}
        if url.endswith("/threads?api-version=2024-05-01-preview"):
            return {"id": "thread-1"}
        if "/messages?api-version" in url:
            return {"id": "message-1"}
        if "/runs" in url:
            return {"id": "run-1", "status": "completed"}
        if "/messages?order=asc" in url:
            return {"data": [{"role": "assistant", "content": [{"type": "text", "text": {"value": "42"}}]}]}
        return {}

    monkeypatch.setattr(provider, "_http_json", http_json)
    return calls


def _ask(provider):
    base = "https://api.fabric.microsoft.com/v1/workspaces/ws/dataagents/agent/aiassistant/openai"
    options = {"config": {"base_url": base, "timeout": 5, "max_retries": 1, "retry_delay": 0}}
    return provider.call_api("How many?", options, {"vars": {}})


def test_given_no_az_and_nothing_set_the_provider_says_so_in_one_sentence(provider, monkeypatch, no_principal):
    calls = _agent(provider, monkeypatch)  # conftest refuses the real az
    assert "az" in _ask(provider)["error"] and calls == []


def test_given_az_mode_should_use_the_az_token_even_with_a_principal_set(
        provider, monkeypatch, principal, fake_cli):
    monkeypatch.setenv(_credentials.DATA_AGENT_AUTH_VAR, "az")
    calls = _agent(provider, monkeypatch)
    assert _ask(provider)["output"] == "42"
    assert {token for _method, _url, token in calls} == {"az-cli-token-value"}
    assert len(fake_cli.made) == 1  # cached for the process: one az call, not one per request


def test_given_no_principal_and_no_mode_should_use_az(provider, monkeypatch, no_principal, fake_cli):
    calls = _agent(provider, monkeypatch)
    assert _ask(provider)["output"] == "42"
    assert calls and all(token == "az-cli-token-value" for _m, _u, token in calls)


def test_given_az_fails_should_be_final_in_one_sentence_without_a_request(
        provider, monkeypatch, no_principal, fake_cli):
    from azure.identity import CredentialUnavailableError

    monkeypatch.setenv(_credentials.DATA_AGENT_AUTH_VAR, "az")
    fake_cli.error = CredentialUnavailableError("Please run 'az login' to set up an account")
    calls = _agent(provider, monkeypatch)
    result = _ask(provider)
    assert "Run `az login`" in result["error"]
    assert calls == [] and len(fake_cli.scopes) == 1  # final: not retried


@pytest.mark.parametrize("status,words", [(401, "az login"), (403, "az login")])
def test_given_a_rejection_under_az_should_name_the_az_identity(
        provider, monkeypatch, no_principal, fake_cli, status, words):
    monkeypatch.setenv(_credentials.DATA_AGENT_AUTH_VAR, "az")
    _agent(provider, monkeypatch, status=status)
    error = _ask(provider)["error"]
    assert words in error and "service principal may not" not in error


# -- the wrapper and the CLI --------------------------------------------------


def _wrapper_args(tmp_path, **overrides):
    suite = tmp_path / "Sales.DataAgent.promptfoo.yaml"
    suite.write_text("tests:\n- vars: {query: 'Revenue?'}\n", encoding="utf-8")
    return argparse.Namespace(**{
        "artifact_path": str(tmp_path / "Sales.DataAgent"), "tests": str(suite),
        "base_url": "https://api.fabric.microsoft.com/v1/x/aiassistant/openai",
        "promptfoo_path": str(tmp_path / "cli.js"), "env_file": None, "auth": "",
        "output_path": str(tmp_path / "results" / "envelope.json"), "timeout": 60, **overrides,
    })


def _capture(monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen["env"] = kwargs["env"]
        seen["file_exists"] = Path(kwargs["env"]["PLAYWRIGHT_ENV_FILE"]).exists()
        Path(command[command.index("--output") + 1]).write_text(
            json.dumps({"results": {"results": [{"success": True}]}}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wrapper, "_terminal", lambda: None)
    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "promptfoo_command", lambda path: ["node", str(path)])
    return seen


def test_given_auth_az_the_worker_gets_the_mode_and_no_principal_file(tmp_path, monkeypatch, principal):
    seen = _capture(monkeypatch)
    assert wrapper.run_data_agent(_wrapper_args(tmp_path, auth="az")) == 0
    assert seen["env"][_credentials.DATA_AGENT_AUTH_VAR] == "az"
    assert not seen["file_exists"]
    assert "private-secret-value" not in json.dumps(seen["env"])


def test_given_nothing_set_the_worker_uses_az(tmp_path, monkeypatch, no_principal):
    seen = _capture(monkeypatch)
    assert wrapper.run_data_agent(_wrapper_args(tmp_path)) == 0
    assert seen["env"][_credentials.DATA_AGENT_AUTH_VAR] == "az"


def test_given_a_principal_and_no_auth_the_worker_uses_it(tmp_path, monkeypatch, principal):
    seen = _capture(monkeypatch)
    assert wrapper.run_data_agent(_wrapper_args(tmp_path)) == 0
    assert seen["env"][_credentials.DATA_AGENT_AUTH_VAR] == "service-principal"
    assert seen["file_exists"]  # the principal file exists while promptfoo runs


def test_given_auth_service_principal_and_nothing_set_should_exit_127_without_promptfoo(
        tmp_path, monkeypatch, no_principal):
    def run(*_args, **_kwargs):
        raise AssertionError("promptfoo must not start")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    monkeypatch.setattr(wrapper, "_terminal", lambda: None)
    args = _wrapper_args(tmp_path, auth="service-principal")
    assert wrapper.run_data_agent(args) == 127
    envelope = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
    assert envelope["message"].count("fab-test auth status") == 1


def test_the_wrapper_accepts_auth(monkeypatch):
    seen = {}

    def run(args):
        seen["auth"] = args.auth
        return 0

    monkeypatch.setattr("sys.argv", ["invoke_data_agent", "--artifact-path", "x.DataAgent", "--auth", "az"])
    monkeypatch.setattr(wrapper, "run_data_agent", run)
    assert wrapper.main() == 0
    assert seen["auth"] == "az"


def test_the_cli_parses_and_forwards_auth(tmp_path):
    from fab_test.scripts._data_agent_run import build_data_agent_command
    from fab_test.scripts.fab_test_parser import build_parser

    args, _unknown = build_parser().parse_known_args(["data-agent", "--auth", "az"])
    assert args.data_agent_auth == "az"
    command = build_data_agent_command(tmp_path / "Sales.DataAgent", args, tmp_path)
    assert command[command.index("--auth") + 1] == "az"
    default, _ = build_parser().parse_known_args(["data-agent"])
    assert "--auth" not in build_data_agent_command(tmp_path / "Sales.DataAgent", default, tmp_path)


def test_given_auth_az_the_run_resolves_urls_with_an_az_token(tmp_path, monkeypatch, principal, fake_cli):
    from fab_test.scripts import _data_agent_run as run

    seen = {}

    class Client:
        @classmethod
        def from_access_token(cls, token, **kwargs):
            seen.update(token=token, **kwargs)
            return cls()

    monkeypatch.setattr(run, "_token_client_class", lambda: Client)
    monkeypatch.setattr(run, "build_service_client", lambda _a: pytest.fail("must not use the principal"))
    monkeypatch.setattr(run, "resolve_workspace_id", lambda client, workspace: "ws-id")
    args = argparse.Namespace(data_agent_auth="az", playwright_env_file=None,
                              data_agent_mode=argparse.Namespace(workspace="fab-test-working-area"))
    assert isinstance(run._client(args), Client)
    assert seen["token"] == "az-cli-token-value" and seen["credential_source"] == "azure-cli"
    assert fake_cli.scopes == [SCOPE]
