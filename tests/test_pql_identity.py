"""Contract tests for the fab-test / pql-test identity guard.

A service-mode pql-test run lists models as fab-test's account and connects
to them as pql-test's. These pin when the guard stops the run and when it
must stay out of the way. `pql-test auth status` is stubbed: no subprocess.
"""

import base64
import json
import sys

import pytest

from fab_test.scripts import _pql_identity as guard


def _token(**claims) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


USER = _token(upn="john@kerski.net")


@pytest.fixture(autouse=True)
def _no_pql_env(monkeypatch):
    for var in ("PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)


def _status(monkeypatch, **fields):
    monkeypatch.setattr(guard, "_pql_auth_status", lambda: fields or None)


def test_token_account_reads_the_signed_in_name():
    assert guard.token_account(USER) == "john@kerski.net"
    assert guard.token_account(_token(preferred_username="a@b.c")) == "a@b.c"


@pytest.mark.parametrize("token", [_token(appid="app-guid"), "not-a-jwt", "a.!!!.c"])
def test_token_account_is_empty_for_an_app_or_unreadable_token(token):
    assert guard.token_account(token) == ""


def test_token_tenant_reads_the_tid_claim():
    assert guard.token_tenant(_token(upn="a@b.c", tid="tenant-guid")) == "tenant-guid"
    assert guard.token_tenant("not-a-jwt") == ""


def test_given_different_accounts_should_name_both(monkeypatch):
    _status(monkeypatch, Status="Authenticated", Method="interactive", Account="jkerski@cftechnologiesllc.com")
    message = guard.pql_identity_mismatch(USER)
    assert "john@kerski.net" in message
    assert "jkerski@cftechnologiesllc.com" in message
    assert "pql-test auth login" in message


def test_given_the_same_account_in_another_case_should_proceed(monkeypatch):
    _status(monkeypatch, Status="Authenticated", Method="interactive", Account="John@Kerski.net")
    assert guard.pql_identity_mismatch(USER) is None


def test_given_pql_test_not_signed_in_should_say_so(monkeypatch):
    _status(monkeypatch, Status="Not authenticated")
    assert "not signed in" in guard.pql_identity_mismatch(USER)


def test_given_a_saved_service_principal_login_should_refuse(monkeypatch):
    _status(monkeypatch, Status="Authenticated", Method="service_principal_secret")
    assert "service_principal_secret" in guard.pql_identity_mismatch(USER)


def test_given_an_app_only_fabric_token_should_not_ask_pql_test(monkeypatch):
    """A service principal is shared with pql-test through PQL_* variables."""
    monkeypatch.setattr(guard, "_pql_auth_status", lambda: pytest.fail("must not run"))
    assert guard.pql_identity_mismatch(_token(appid="app-guid")) is None


def test_given_pql_credential_variables_should_not_ask_pql_test(monkeypatch):
    monkeypatch.setenv("PQL_CLIENT_ID", "x")
    monkeypatch.setattr(guard, "_pql_auth_status", lambda: pytest.fail("must not run"))
    assert guard.pql_identity_mismatch(USER) is None


def test_given_pql_test_cannot_run_should_proceed(monkeypatch):
    _status(monkeypatch)
    assert guard.pql_identity_mismatch(USER) is None


def _print_as_pql_test(monkeypatch, stdout: str) -> None:
    """Stand in a real process that prints ``stdout`` for `pql-test auth status`."""
    script = f"import sys; sys.stdout.write({stdout!r})"
    monkeypatch.setattr(
        "fab_test.scripts.invoke_pql_test._resolve_pql_command",
        lambda command: [sys.executable, "-c", script],
    )


def test_auth_status_reads_pql_tests_signed_in_output(monkeypatch):
    """The exact layout pql-test 0.1.19 prints, indentation included."""
    _print_as_pql_test(
        monkeypatch,
        "Status: Authenticated\n  Method: interactive\n  Account: a@b.c\n  Environment: Public\n",
    )
    assert guard._pql_auth_status() == {"Status": "Authenticated", "Method": "interactive", "Account": "a@b.c"}


def test_auth_status_reads_pql_tests_signed_out_output(monkeypatch):
    _print_as_pql_test(monkeypatch, "Status: Not authenticated\n\nTo log in, run: pql-test auth login\n")
    assert guard._pql_auth_status() == {"Status": "Not authenticated"}


def test_auth_status_is_none_when_pql_test_cannot_start(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "fab_test.scripts.invoke_pql_test._resolve_pql_command",
        lambda command: [str(tmp_path / "no-such-pql-test")],
    )
    assert guard._pql_auth_status() is None
