"""Telemetry context: git branch/commit/actor, run origin, machine context.

Scope
-----
_git_context's GitHub-Actions-vs-local-git precedence, _detect_origin's
CI-platform detection, _machine_context's platform/python/version capture,
and how _build_telemetry_payload folds both into a payload.

    pytest -m fab_test
"""
import sys
from pathlib import Path

import pytest

from fabric_ci_cd_dataops import __version__ as fab_test_version
from fabric_ci_cd_dataops.scripts.fab_test import (
    _build_telemetry_payload,
    _detect_origin,
    _git_context,
    _machine_context,
)
from tests.conftest import _clear_github_env, _fake_git_run

# --------------------------------------------------------------------------- #
# Git context (telemetry): branch, commit, actor
# --------------------------------------------------------------------------- #




@pytest.mark.fab_test
def test_git_context_prefers_github_env_vars(monkeypatch):
    """GitHub Actions env vars are used as-is when present."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setenv("GITHUB_REPOSITORY", "kerski/fab-test")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_ACTOR", "ci-bot")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("git should not run")),
    )

    ctx = _git_context()
    assert ctx == {
        "repository": "kerski/fab-test",
        "branch": "main",
        "commit": "abc123",
        "actor": "ci-bot",
        "workflow_run_id": "42",
    }


@pytest.mark.fab_test
def test_git_context_falls_back_to_local_git_branch_and_commit(monkeypatch):
    """Outside GitHub Actions, branch and commit come from local git."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse HEAD": "deadbeef\n",
                "rev-parse --abbrev-ref HEAD": "feature/x\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )

    ctx = _git_context()
    assert ctx["commit"] == "deadbeef"
    assert ctx["branch"] == "feature/x"


@pytest.mark.fab_test
def test_git_context_falls_back_to_local_git_user_email_for_actor(monkeypatch):
    """When GITHUB_ACTOR is unset, the actor falls back to git config user.email."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "rev-parse HEAD": "deadbeef\n",
                "rev-parse --abbrev-ref HEAD": "main\n",
                "config user.email": "dev@example.com\n",
            }
        ),
    )

    ctx = _git_context()
    assert ctx["actor"] == "dev@example.com"


@pytest.mark.fab_test
def test_git_context_falls_back_to_local_git_remote_for_repository_https(monkeypatch):
    """Outside GitHub Actions, repository is parsed from an HTTPS origin remote."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "remote get-url origin": "https://github.com/kerski/fab-test.git\n",
            }
        ),
    )

    ctx = _git_context()
    assert ctx["repository"] == "kerski/fab-test"


@pytest.mark.fab_test
def test_git_context_falls_back_to_local_git_remote_for_repository_ssh(monkeypatch):
    """Outside GitHub Actions, repository is parsed from an SSH origin remote."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {
                "remote get-url origin": "git@github.com:kerski/fab-test.git\n",
            }
        ),
    )

    ctx = _git_context()
    assert ctx["repository"] == "kerski/fab-test"


@pytest.mark.fab_test
def test_git_context_repository_empty_when_no_origin_remote(monkeypatch):
    """No origin remote configured leaves repository empty, not crashing."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess, "run", _fake_git_run({})  # every command "fails"
    )

    ctx = _git_context()
    assert ctx["repository"] == ""


@pytest.mark.fab_test
def test_git_context_repository_not_overridden_by_git_when_github_repository_set(monkeypatch):
    """GITHUB_REPOSITORY wins over the local origin remote even if both resolve."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setenv("GITHUB_REPOSITORY", "kerski/fab-test")
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run(
            {"remote get-url origin": "https://github.com/someone-else/fork.git\n"}
        ),
    )

    ctx = _git_context()
    assert ctx["repository"] == "kerski/fab-test"


@pytest.mark.fab_test
def test_git_context_actor_empty_when_git_config_has_no_email(monkeypatch):
    """A git config with no user.email set leaves actor empty, not crashing."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess, "run", _fake_git_run({})  # every command "fails"
    )

    ctx = _git_context()
    assert ctx["actor"] == ""
    assert ctx["branch"] == ""
    assert ctx["commit"] == ""


@pytest.mark.fab_test
def test_git_context_returns_empty_strings_when_git_is_unavailable(monkeypatch):
    """If git itself is missing, _git_context degrades to empty fields, no crash."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git not found")),
    )

    ctx = _git_context()
    assert ctx == {
        "repository": "",
        "branch": "",
        "commit": "",
        "actor": "",
        "workflow_run_id": "",
    }


@pytest.mark.fab_test
def test_git_context_actor_not_overridden_by_git_when_github_actor_set(monkeypatch):
    """GITHUB_ACTOR wins over the local git user.email even if both are set."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    _clear_github_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTOR", "ci-bot")
    monkeypatch.setattr(
        fab_test_module.subprocess,
        "run",
        _fake_git_run({"config user.email": "dev@example.com\n"}),
    )

    ctx = _git_context()
    assert ctx["actor"] == "ci-bot"


# --------------------------------------------------------------------------- #
# Distinguish local vs pipeline origin
# --------------------------------------------------------------------------- #


def _clear_ci_env(monkeypatch):
    for name in ("GITHUB_ACTIONS", "CI", "GITLAB_CI", "CIRCLECI", "AZURE_DEVOPS"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.fab_test
def test_detect_origin_github_actions(monkeypatch):
    """GITHUB_ACTIONS maps origin to 'github-actions'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert _detect_origin() == "github-actions"


@pytest.mark.fab_test
def test_detect_origin_gitlab_ci(monkeypatch):
    """GITLAB_CI maps origin to 'gitlab-ci'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("GITLAB_CI", "true")
    assert _detect_origin() == "gitlab-ci"


@pytest.mark.fab_test
def test_detect_origin_circleci(monkeypatch):
    """CIRCLECI maps origin to 'circleci'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("CIRCLECI", "true")
    assert _detect_origin() == "circleci"


@pytest.mark.fab_test
def test_detect_origin_azure_devops(monkeypatch):
    """AZURE_DEVOPS maps origin to 'azure-devops'."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("AZURE_DEVOPS", "true")
    assert _detect_origin() == "azure-devops"


@pytest.mark.fab_test
def test_detect_origin_local_when_no_ci_env_present(monkeypatch):
    """With no known CI env vars, origin is 'local'."""
    _clear_ci_env(monkeypatch)
    assert _detect_origin() == "local"


@pytest.mark.fab_test
def test_detect_origin_github_actions_takes_precedence(monkeypatch):
    """If multiple CI env vars are somehow set, GITHUB_ACTIONS wins."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITLAB_CI", "true")
    assert _detect_origin() == "github-actions"


@pytest.mark.fab_test
def test_build_telemetry_payload_includes_origin(monkeypatch):
    """The telemetry payload carries the detected origin field."""
    _clear_ci_env(monkeypatch)
    monkeypatch.setenv("CIRCLECI", "true")

    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert payload["origin"] == "circleci"


# --------------------------------------------------------------------------- #
# Capture machine context
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_machine_context_includes_platform_python_and_fab_test_version():
    """Machine context carries platform, python_version, and fab_test_version."""
    context = _machine_context()
    assert context["platform"] == sys.platform
    assert context["python_version"]
    assert context["fab_test_version"] == fab_test_version


@pytest.mark.fab_test
def test_machine_context_omits_platform_when_undetectable(monkeypatch):
    """If the OS platform can't be read, the field is omitted, not a crash."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module,
        "_current_os_platform",
        lambda: (_ for _ in ()).throw(RuntimeError("no platform")),
    )

    context = _machine_context()
    assert "platform" not in context
    assert context["python_version"]
    assert context["fab_test_version"] == fab_test_version


# `_redact_pii` and its two tests were deleted deliberately. It hashed the
# git email to `sha256:...`, which answered "was this the same person as last
# time" and nothing else -- while the operating-system username shipped in
# plaintext through the absolute paths inside the embedded `results`
# envelope, which it never touched. It bought no privacy and cost the
# attribution the field exists for. `actor` is now recorded as given and
# payload paths are made repository-relative; see
# tests/test_telemetry_identity.py.


@pytest.mark.fab_test
def test_build_telemetry_payload_includes_machine_context():
    """The telemetry payload carries platform/python_version/fab_test_version."""
    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert payload["platform"] == sys.platform
    assert payload["fab_test_version"] == fab_test_version


@pytest.mark.fab_test
def test_build_telemetry_payload_records_the_actor_as_given(monkeypatch):
    """An email-shaped actor reaches the payload unchanged.

    This test previously asserted the opposite. Inspecting real ingested
    rows showed the hash achieved neither goal: it made `actor`
    unresolvable, losing the attribution the field exists for, while the
    operating-system username shipped in plaintext through the absolute
    paths inside the embedded `results` envelope, which the redaction never
    touched. See tests/test_telemetry_identity.py.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(
        fab_test_module, "_git_context", lambda: {"actor": "dev@example.com"}
    )
    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert payload["actor"] == "dev@example.com"


@pytest.mark.fab_test
def test_build_telemetry_payload_actor_unchanged_when_not_email(monkeypatch):
    """A non-email actor (e.g. GITHUB_ACTOR) passes through unredacted."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "_git_context", lambda: {"actor": "ci-bot"})
    payload = _build_telemetry_payload(
        "bpa",
        Path("SampleModel.SemanticModel"),
        {"status": "passed", "findings": []},
        "DEV",
    )
    assert payload["actor"] == "ci-bot"


