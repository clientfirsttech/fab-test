"""Contract tests for `fab-test auth` (Artifact Targeting and Auth §8-9).

Scope
-----
`auth status` is the command that checks credentials *for real*: it is the
one place allowed to acquire a token, which is why the §7 probe can report
an ambient credential as unverified and point here. `auth login` mints
nothing — it delegates to the tool that owns the credential, or names the
command to run.

Behavior is driven in-process with the network boundaries monkeypatched,
so these are deterministic and never touch Azure, never open a browser,
and always pass on any machine. The CLI tests cover wiring and the paths
that provably make no network call.
"""

import json
import os
import subprocess
import sys

import pytest

from fab_test.scripts import fab_test as fab_test_module
from fab_test.scripts import fab_test_admin
from fab_test.scripts._credentials import CredentialStatus

_GUID = "33333333-3333-3333-3333-333333333333"
_SECRET = "s3cr3t-do-not-print"


def _args(**overrides):
    import argparse

    defaults = {
        "auth_command": "status",
        "output_format": "text",
        "workspace_id": "",
        "playwright_env_file": None,
        "cloud": "public",
        "file_config": {},
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _resolved(**overrides):
    defaults = {
        "source": "environment",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "verified": True,
        "detail": "service principal from environment",
        "remediation": None,
    }
    defaults.update(overrides)
    return CredentialStatus(**defaults)


def _run_cli(*argv, env=None, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
        cwd=cwd,
        check=False,
    )


# --------------------------------------------------------------------------- #
# auth status
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_status_exits_zero_when_credentials_resolve(monkeypatch, capsys):
    """The happy path: a verified identity is reported and the command succeeds."""
    monkeypatch.setattr(fab_test_admin, "probe_credentials", lambda **kw: _resolved())

    assert fab_test_module._auth(_args()) == 0
    assert "environment" in capsys.readouterr().out


@pytest.mark.fab_test
def test_status_exits_127_when_nothing_resolves(monkeypatch, capsys):
    """No credentials is a missing prerequisite, the established 127."""
    monkeypatch.setattr(
        fab_test_admin,
        "probe_credentials",
        lambda **kw: CredentialStatus(
            source=None,
            tenant_id=None,
            verified=False,
            detail="no credentials resolved",
            remediation="set FABRIC_TENANT_ID...; or sign in with `az login`",
        ),
    )

    assert fab_test_module._auth(_args()) == 127
    assert "az login" in capsys.readouterr().out


@pytest.mark.fab_test
def test_status_verifies_an_unverified_ambient_credential(monkeypatch, capsys):
    """The §7 probe defers to here; here it actually acquires a token."""
    monkeypatch.setattr(
        fab_test_admin,
        "probe_credentials",
        lambda **kw: _resolved(source="ambient:DefaultAzureCredential", verified=False),
    )
    monkeypatch.setattr(fab_test_admin, "_verify_ambient_credential", lambda: None)

    assert fab_test_module._auth(_args()) == 0
    assert "verified" in capsys.readouterr().out.lower()


@pytest.mark.fab_test
def test_status_reports_why_an_ambient_credential_failed(monkeypatch, capsys):
    """A sign-in that does not resolve names the reason rather than just failing."""

    def _fail():
        raise RuntimeError("DefaultAzureCredential found no usable credential")

    monkeypatch.setattr(
        fab_test_admin,
        "probe_credentials",
        lambda **kw: _resolved(source="ambient:DefaultAzureCredential", verified=False),
    )
    monkeypatch.setattr(fab_test_admin, "_verify_ambient_credential", _fail)

    assert fab_test_module._auth(_args()) == 127
    assert "no usable credential" in capsys.readouterr().out


@pytest.mark.fab_test
def test_status_reports_workspace_reachability(monkeypatch, capsys):
    """Moved here from §7: reachability needs a network call the probe cannot make."""
    monkeypatch.setattr(fab_test_admin, "probe_credentials", lambda **kw: _resolved())
    monkeypatch.setattr(fab_test_admin, "_check_workspace_reachable", lambda ws, args: True)

    assert fab_test_module._auth(_args(workspace_id=_GUID)) == 0
    assert "reachable" in capsys.readouterr().out.lower()


@pytest.mark.fab_test
def test_status_exits_1_when_the_workspace_is_unreachable(monkeypatch):
    """Credentials work but the workspace does not: a real failure, not a missing tool."""
    monkeypatch.setattr(fab_test_admin, "probe_credentials", lambda **kw: _resolved())
    monkeypatch.setattr(fab_test_admin, "_check_workspace_reachable", lambda ws, args: False)

    assert fab_test_module._auth(_args(workspace_id=_GUID)) == 1


@pytest.mark.fab_test
def test_status_makes_no_network_call_without_a_workspace(monkeypatch):
    """Nothing to reach means nothing is reached."""
    monkeypatch.setattr(fab_test_admin, "probe_credentials", lambda **kw: _resolved())

    def _fail(ws, args):
        raise AssertionError("must not check reachability with no workspace")

    monkeypatch.setattr(fab_test_admin, "_check_workspace_reachable", _fail)

    assert fab_test_module._auth(_args()) == 0


@pytest.mark.fab_test
def test_status_json_is_one_document(monkeypatch, capsys):
    """--format json emits a single parseable document."""
    monkeypatch.setattr(fab_test_admin, "probe_credentials", lambda **kw: _resolved())

    fab_test_module._auth(_args(output_format="json"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"]["source"] == "environment"
    assert payload["identity"]["verified"] is True


@pytest.mark.fab_test
def test_status_reports_fab_test_env_as_the_origin(tmp_path):
    """`auth status` names .fab-test/.env, not a generic ".env", as the source.

    Task 8 unifies discovery so both `_credentials` and the Playwright
    config loader prefer `.fab-test/.env` over a root `.env` when both
    exist; `auth status` is the caller that surfaces which one won.
    """
    fab_test_dir = tmp_path / ".fab-test"
    fab_test_dir.mkdir()
    (fab_test_dir / ".env").write_text(
        "FABRIC_TENANT_ID=11111111-1111-1111-1111-111111111111\n"
        "FABRIC_CLIENT_ID=22222222-2222-2222-2222-222222222222\n"
        "FABRIC_CLIENT_SECRET=s3cr3t-do-not-print\n",
        encoding="utf-8",
    )

    # `_run_cli` merges this dict onto a copy of the real os.environ rather
    # than replacing it, so a key merely absent here (via a filtered
    # comprehension) is not actually unset when the real environment has
    # it -- as GITHUB_WORKSPACE always does in CI, never locally, which is
    # exactly why this needs to be an explicit override, not an omission.
    _unset = (
        "FABRIC_TENANT_ID",
        "FABRIC_CLIENT_ID",
        "FABRIC_CLIENT_SECRET",
        "FABRIC_SERVICE_PRINCIPAL_ID",
        "FABRIC_SERVICE_PRINCIPAL_SECRET",
        "PLAYWRIGHT_ENV_FILE",
        # `_repo_root()` prefers GITHUB_WORKSPACE over cwd, which would
        # make discovery ignore `cwd=tmp_path` below and look in the real
        # checkout instead of the `.fab-test/.env` written above.
        "GITHUB_WORKSPACE",
    )
    env = {k: v for k, v in os.environ.items() if k not in _unset}
    env.update(dict.fromkeys(_unset, ""))
    result = _run_cli("auth", "status", "--format", "json", env=env, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["identity"]["source"] == ".fab-test/.env"


@pytest.mark.fab_test
def test_status_redacts_a_live_secret_that_reaches_the_output(monkeypatch, capsys):
    """Defense in depth for the secrets constraint.

    The probe is tested never to put a secret in these fields, but this
    output is the one place a live credential value could reach a terminal
    or a CI log, so a value found in the environment is scrubbed on the
    way out regardless of how it got there.
    """
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", _SECRET)
    monkeypatch.setattr(
        fab_test_admin,
        "probe_credentials",
        lambda **kw: _resolved(detail=f"service principal ({_SECRET})"),
    )

    fab_test_module._auth(_args(output_format="json"))

    output = capsys.readouterr().out
    assert _SECRET not in output
    assert "<redacted>" in output


@pytest.mark.fab_test
def test_status_json_reports_an_absent_workspace_as_null(monkeypatch, capsys):
    """A consumer tests one thing rather than a missing key."""
    monkeypatch.setattr(fab_test_admin, "probe_credentials", lambda **kw: _resolved())

    fab_test_module._auth(_args(output_format="json"))

    assert json.loads(capsys.readouterr().out)["workspace"] is None


# --------------------------------------------------------------------------- #
# auth login
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_login_delegates_to_pql_test_and_propagates_its_exit_code(monkeypatch, capsys):
    """fab-test owns no credential store; the underlying tool does the login."""
    monkeypatch.setattr(fab_test_admin.shutil, "which", lambda name: f"/usr/bin/{name}")
    recorded = {}

    def _fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 3)

    monkeypatch.setattr(fab_test_admin.subprocess, "run", _fake_run)

    assert fab_test_module._auth(_args(auth_command="login")) == 3
    assert recorded["cmd"][:3] == ["/usr/bin/pql-test", "auth", "login"]
    assert "pql-test auth login" in capsys.readouterr().out


@pytest.mark.fab_test
def test_login_prints_the_command_before_running_it(monkeypatch, capsys):
    """The caller can reproduce the login without fab-test in the loop."""
    monkeypatch.setattr(fab_test_admin.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        fab_test_admin.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0)
    )

    fab_test_module._auth(_args(auth_command="login"))

    assert "/usr/bin/pql-test" in capsys.readouterr().out


@pytest.mark.fab_test
def test_login_passes_the_cloud_through(monkeypatch):
    """--cloud selects a sovereign cloud and reaches the delegated tool."""
    monkeypatch.setattr(fab_test_admin.shutil, "which", lambda name: f"/usr/bin/{name}")
    recorded = {}

    def _fake_run(cmd, **kwargs):
        recorded["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(fab_test_admin.subprocess, "run", _fake_run)

    fab_test_module._auth(_args(auth_command="login", cloud="USGov"))

    assert "--environment" in recorded["cmd"]
    assert "USGov" in recorded["cmd"]


@pytest.mark.fab_test
def test_login_without_a_delegable_tool_names_the_alternative(monkeypatch, capsys):
    """No pql-test: say what to run instead rather than failing silently."""
    monkeypatch.setattr(fab_test_admin.shutil, "which", lambda name: None)

    assert fab_test_module._auth(_args(auth_command="login")) == 127
    output = capsys.readouterr().out
    assert "az login" in output
    assert "FABRIC_SERVICE_PRINCIPAL_ID" in output


@pytest.mark.fab_test
def test_login_writes_no_credential_file(monkeypatch, tmp_path):
    """The whole point of delegating: fab-test never becomes a credential store."""
    monkeypatch.setattr(fab_test_admin.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        fab_test_admin.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0)
    )
    monkeypatch.chdir(tmp_path)

    fab_test_module._auth(_args(auth_command="login"))

    assert list(tmp_path.iterdir()) == [], "auth login must not write anything"


# --------------------------------------------------------------------------- #
# CLI wiring and the --env / --cloud distinction
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_auth_is_a_real_subcommand():
    """`fab-test auth --help` lists both verbs."""
    result = _run_cli("auth", "--help")

    assert result.returncode == 0, result.stderr
    assert "status" in result.stdout
    assert "login" in result.stdout


@pytest.mark.fab_test
def test_auth_login_without_pql_test_on_path_exits_127(tmp_path):
    """Provably no network call: with an empty PATH there is nothing to delegate to."""
    result = _run_cli("auth", "login", env={"PATH": str(tmp_path)})

    assert result.returncode == 127, result.stdout + result.stderr
    assert "az login" in result.stdout


@pytest.mark.fab_test
def test_env_still_means_the_test_environment_label():
    """--env is DEV/PROD; --cloud is the Azure cloud. The two must never merge."""
    result = _run_cli("pql-test", "--help")

    assert result.returncode == 0, result.stderr
    assert "Environment label" in result.stdout
    assert "--cloud" not in result.stdout


@pytest.mark.fab_test
def test_cloud_is_spelled_cloud_not_environment():
    """auth login's sovereign-cloud selector must not reuse the --env name."""
    result = _run_cli("auth", "login", "--help")

    assert result.returncode == 0, result.stderr
    assert "--cloud" in result.stdout
