"""Contract tests for the fab-test readiness probe (CLI Agent Ergonomics §7).

Scope
-----
The probe answers "could this analyzer run?" without downloading anything,
touching artifacts, or spawning a subprocess — it is the engine behind
`fab-test doctor`. Always passes on any machine.
"""

import json
import tempfile
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._analyzer_tool_bootstrap import probe_executable
from fabric_ci_cd_dataops.scripts.fab_test_registry import check_readiness

# A path guaranteed not to exist, so credential/env-file resolution in this
# module never picks up a real `.fab-test/.env` or `.env` a developer keeps
# in their own checkout -- these tests must always pass on any machine.
_NO_SUCH_ENV_FILE = str(Path(tempfile.gettempdir()) / "fab-test-test-isolation" / ".env")


def _write_metadata(metadata_path, analyzer_name, tool_install):
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps({"analyzer_registry": {analyzer_name: {"tool_install": tool_install}}}),
        encoding="utf-8",
    )


@pytest.mark.fab_test
def test_probe_ready_when_explicit_path_resolves(tmp_path):
    """A usable explicit_path reports ready with its resolved path and no remediation."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    existing = repo_root / "TabularEditor.exe"
    existing.write_text("binary", encoding="utf-8")
    _write_metadata(
        metadata,
        "tabular_editor_bpa",
        {"env_var": "TABULAR_EDITOR_PATH", "default_path": ""},
    )

    result = probe_executable(
        "tabular_editor_bpa", metadata, repo_root, explicit_path=str(existing)
    )

    assert result["ready"] is True
    assert result["resolved_path"] == str(existing.resolve())
    assert "CLI argument" in result["reason"]
    assert result["remediation"] is None


@pytest.mark.fab_test
def test_probe_ready_when_env_var_path_resolves(tmp_path, monkeypatch):
    """A usable env-var path reports ready without needing explicit_path."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    existing = repo_root / "PBIRInspectorCLI"
    existing.write_text("binary", encoding="utf-8")
    _write_metadata(
        metadata, "pbir_inspector", {"env_var": "PBIR_INSPECTOR_PATH", "default_path": ""}
    )
    monkeypatch.setenv("PBIR_INSPECTOR_PATH", str(existing))

    result = probe_executable("pbir_inspector", metadata, repo_root)

    assert result["ready"] is True
    assert result["resolved_path"] == str(existing.resolve())
    assert "PBIR_INSPECTOR_PATH" in result["reason"]


@pytest.mark.fab_test
def test_probe_reports_would_download_without_downloading(tmp_path, monkeypatch):
    """A tool that would need downloading reports the install URL, but never fetches it."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(
        metadata,
        "tabular_editor_bpa",
        {
            "env_var": "TABULAR_EDITOR_PATH",
            "default_path": "./TabularEditor/TabularEditor.exe",
            "install_url_env_var": "TABULAR_EDITOR_INSTALL_URL",
            "install_url": "https://cdn.tabulareditor.com/files/TabularEditor.2.28.0.zip",
        },
    )
    monkeypatch.delenv("TABULAR_EDITOR_PATH", raising=False)
    monkeypatch.delenv("TABULAR_EDITOR_INSTALL_URL", raising=False)

    from fabric_ci_cd_dataops.scripts import _analyzer_tool_bootstrap as bootstrap

    def _fail_if_called(*_a, **_k):
        raise AssertionError("probe must never download")

    monkeypatch.setattr(bootstrap, "urlopen", _fail_if_called)

    result = probe_executable("tabular_editor_bpa", metadata, repo_root)

    assert result["ready"] is False
    assert result["resolved_path"] is None
    assert "TabularEditor.2.28.0.zip" in result["remediation"]


@pytest.mark.fab_test
def test_probe_reports_unsupported_platform(tmp_path, monkeypatch):
    """A platform mismatch is reported as not-ready with the supported platform named."""
    import sys

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(
        metadata,
        "tabular_editor_bpa",
        {"env_var": "TABULAR_EDITOR_PATH", "requires_platform": "win32"},
    )
    monkeypatch.setattr(sys, "platform", "linux")

    result = probe_executable("tabular_editor_bpa", metadata, repo_root)

    assert result["ready"] is False
    assert result["resolved_path"] is None
    assert "linux" in result["reason"]
    assert "win32" in result["remediation"]


@pytest.mark.fab_test
def test_probe_not_ready_with_no_candidates_and_no_install_url(tmp_path):
    """No usable path and no install URL configured is a clear not-ready state."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(metadata, "tabular_editor_bpa", {"env_var": "TABULAR_EDITOR_PATH"})

    result = probe_executable("tabular_editor_bpa", metadata, repo_root)

    assert result["ready"] is False
    assert result["resolved_path"] is None
    assert "TABULAR_EDITOR_PATH" in result["remediation"]


@pytest.mark.fab_test
def test_probe_never_spawns_a_subprocess(tmp_path, monkeypatch):
    """The probe never invokes subprocess.run, regardless of outcome."""
    import subprocess

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    metadata = repo_root / ".github" / "metadata" / "analyzers.json"
    _write_metadata(metadata, "tabular_editor_bpa", {"env_var": "TABULAR_EDITOR_PATH"})

    def _fail_if_called(*_a, **_k):
        raise AssertionError("probe must never spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", _fail_if_called)

    probe_executable("tabular_editor_bpa", metadata, repo_root)  # must not raise


@pytest.mark.fab_test
def test_check_readiness_bpa_delegates_to_probe(tmp_path, monkeypatch):
    """check_readiness('bpa', args) resolves via the CLI flag like preflight_error does."""
    import sys

    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    # bpa's tool_install requires_platform is "win32" (Tabular Editor is a
    # Windows executable) -- pin the platform so this delegation test
    # passes on any host, matching test_probe_reports_unsupported_platform.
    monkeypatch.setattr(sys, "platform", "win32")

    existing = tmp_path / "TabularEditor.exe"
    existing.write_text("binary", encoding="utf-8")

    class _Args:
        tabular_editor_path = str(existing)

    monkeypatch.setattr(registry, "ANALYZERS_JSON", registry.ANALYZERS_JSON)
    result = registry.check_readiness("bpa", _Args())

    assert result["ready"] is True
    assert result["resolved_path"] == str(existing.resolve())


@pytest.mark.fab_test
def test_check_readiness_a11y_delegates_to_probe_via_its_own_flag(tmp_path):
    """check_readiness('a11y', args) resolves via --a11y-path like bpa/pbir do."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    existing = tmp_path / "cli.js"
    existing.write_text("// built", encoding="utf-8")

    class _Args:
        a11y_path = str(existing)

    result = registry.check_readiness("a11y", _Args())

    assert result["ready"] is True
    assert result["resolved_path"] == str(existing.resolve())


@pytest.mark.fab_test
def test_a11y_is_a_fully_advertised_analyzer():
    """`a11y` is a first-class analyzer: registered, visible, and answerable.

    Hidden only briefly (Task 2, before its command builder/subparser
    existed) -- Task 4 registered both, so it belongs on the advertised
    surface the same as bpa/pbir, not tucked away like pql_lint.
    """
    from fabric_ci_cd_dataops.scripts.fab_test_registry import (
        HIDDEN_ANALYZERS,
        visible_analyzers,
    )

    assert "a11y" not in HIDDEN_ANALYZERS
    assert "a11y" in visible_analyzers()
    result = check_readiness("a11y", None)
    assert set(result.keys()) == {"ready", "resolved_path", "reason", "remediation", "version"}


@pytest.mark.fab_test
def test_check_readiness_non_bootstrapped_analyzer_is_always_ready():
    """An analyzer with no external tool and no cloud dependency is always ready.

    pql_lint only reads files on disk. pql_test and playwright also resolve
    no binary but do need a workspace or a Desktop instance, so they take
    the cloud branch instead -- see the §6 tests at the end of this file.
    """
    result = check_readiness("pql_lint", None)

    assert result["ready"] is True
    assert result["resolved_path"] is None
    assert "no external tool" in result["reason"]


@pytest.mark.fab_test
def test_check_readiness_returns_same_shape_for_every_analyzer():
    """Every analyzer's readiness dict has the same five keys (stable for `doctor`)."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import ANALYZER_REGISTRY

    expected_keys = {"ready", "resolved_path", "reason", "remediation", "version"}
    for name in ANALYZER_REGISTRY:
        result = check_readiness(name, None)
        assert set(result.keys()) == expected_keys, f"{name} readiness shape mismatch"


# --------------------------------------------------------------------------- #
# Cloud-analyzer readiness (Artifact Targeting and Auth §6)
#
# check_readiness used to short-circuit to ready for every analyzer without an
# external binary, so `doctor` greenlit pql_test and playwright with no
# credentials and no reachable workspace. These tests pin the honest answer.
# --------------------------------------------------------------------------- #

_CLOUD_ENV_VARS = (
    "FABRIC_WORKSPACE_ID",
    "FABRIC_TENANT_ID",
    "FABRIC_SERVICE_PRINCIPAL_ID",
    "FABRIC_SERVICE_PRINCIPAL_SECRET",
    "FABRIC_CLIENT_ID",
    "FABRIC_CLIENT_SECRET",
)


def _clear_cloud_env(monkeypatch):
    """Remove every workspace and credential variable the probe consults.

    Also pins `PLAYWRIGHT_ENV_FILE` to a nonexistent path -- the highest
    priority source in `resolve_env_file`'s search order -- so a real
    `.fab-test/.env` or `.env` in this checkout can never leak into these
    tests via ambient discovery.
    """
    for var in _CLOUD_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", _NO_SUCH_ENV_FILE)


def _set_service_principal(monkeypatch):
    monkeypatch.setenv("FABRIC_TENANT_ID", "11111111-1111-1111-1111-111111111111")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_ID", "22222222-2222-2222-2222-222222222222")
    monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "s3cr3t-do-not-print")


@pytest.mark.fab_test
def test_cloud_analyzer_not_ready_without_workspace_credentials_or_desktop(monkeypatch):
    """pql_test with nothing configured is not ready -- the false green this fixes."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(registry, "desktop_ports", list)  # no instance running

    result = registry.check_readiness("pql_test", None)

    assert result["ready"] is False
    assert result["remediation"] is not None


@pytest.mark.fab_test
def test_cloud_analyzer_remediation_names_every_accepted_source(monkeypatch):
    """Not-ready remediation names the workspace variable, the credentials, and Desktop."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(registry, "desktop_ports", list)  # no instance running

    remediation = registry.check_readiness("pql_test", None)["remediation"]

    assert "FABRIC_WORKSPACE_ID" in remediation
    assert "FABRIC_SERVICE_PRINCIPAL_ID" in remediation
    assert "Desktop" in remediation


@pytest.mark.fab_test
def test_cloud_analyzer_ready_with_workspace_and_service_principal(monkeypatch):
    """A workspace plus resolvable credentials reports ready and names the source."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "33333333-3333-3333-3333-333333333333")
    _set_service_principal(monkeypatch)

    result = registry.check_readiness("playwright", None)

    assert result["ready"] is True
    assert "workspace" in result["reason"].lower()
    assert result["remediation"] is None


@pytest.mark.fab_test
def test_cloud_analyzer_with_workspace_but_no_credentials_is_not_ready(monkeypatch):
    """A workspace alone is not enough, and the remediation asks only for credentials.

    Ambient Azure is switched off explicitly: azure-identity is installed
    in this environment, so leaving it on would resolve the chain and make
    this analyzer ready for a different (and correct) reason. See
    tests/test_credentials.py for the ambient path itself.
    """
    from fabric_ci_cd_dataops.scripts import _credentials
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "33333333-3333-3333-3333-333333333333")
    monkeypatch.setattr(registry, "desktop_ports", list)  # no instance running
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: False)

    result = registry.check_readiness("pql_test", None)

    assert result["ready"] is False
    assert "FABRIC_SERVICE_PRINCIPAL_ID" in result["remediation"]
    assert "FABRIC_WORKSPACE_ID" not in result["remediation"]


@pytest.mark.fab_test
def test_workspace_plus_ambient_credential_is_ready_but_flagged_unverified(monkeypatch):
    """An az-logged-in developer is not reported red, but the reason says unproven."""
    from fabric_ci_cd_dataops.scripts import _credentials
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "33333333-3333-3333-3333-333333333333")
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: True)

    result = registry.check_readiness("pql_test", None)

    assert result["ready"] is True
    assert "unverified" in result["reason"]
    assert "auth status" in result["reason"]


@pytest.mark.fab_test
def test_pql_test_is_ready_via_a_running_desktop_instance(monkeypatch):
    """A running Desktop instance makes pql_test ready with no workspace at all."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(registry, "desktop_ports", lambda: [51001])

    result = registry.check_readiness("pql_test", None)

    assert result["ready"] is True
    assert "desktop" in result["reason"].lower()


@pytest.mark.fab_test
def test_playwright_does_not_fall_back_to_desktop(monkeypatch):
    """Only pql_test binds to Desktop; playwright needs a real workspace."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(registry, "desktop_ports", lambda: [51001])

    result = registry.check_readiness("playwright", None)

    assert result["ready"] is False


@pytest.mark.fab_test
def test_playwright_ambient_credential_is_not_ready(monkeypatch):
    """Playwright needs a real service principal; ambient auth is not enough.

    Unlike pql_test, which can authenticate interactively,
    ``get_embed_context`` always calls MSAL with a service-principal secret.
    Reporting ready here would be the false green task 1 exists to remove --
    an az-logged-in developer would see green and then hit an MSAL
    traceback on the one command that cannot use their sign-in.
    """
    from fabric_ci_cd_dataops.scripts import _credentials
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "33333333-3333-3333-3333-333333333333")
    monkeypatch.setattr(_credentials, "ambient_credential_available", lambda: True)

    result = registry.check_readiness("playwright", None)

    assert result["ready"] is False
    assert result["remediation"] is not None


@pytest.mark.fab_test
def test_explicit_workspace_id_argument_is_honored(monkeypatch):
    """--workspace-id counts as a resolved workspace even with no env var set."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    class _CloudArgs:
        workspace_id = "44444444-4444-4444-4444-444444444444"

    _clear_cloud_env(monkeypatch)
    _set_service_principal(monkeypatch)

    result = registry.check_readiness("pql_test", _CloudArgs())

    assert result["ready"] is True


@pytest.mark.fab_test
def test_file_only_analyzer_stays_ready_without_any_credentials(monkeypatch):
    """pql_lint reads files on disk, so it is ready with nothing configured."""
    _clear_cloud_env(monkeypatch)

    result = check_readiness("pql_lint", None)

    assert result["ready"] is True
    assert "no external tool" in result["reason"]


@pytest.mark.fab_test
def test_readiness_never_echoes_a_credential_value(monkeypatch):
    """The secrets constraint: no probe output ever contains the secret itself."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "33333333-3333-3333-3333-333333333333")
    _set_service_principal(monkeypatch)

    result = registry.check_readiness("pql_test", None)

    assert "s3cr3t-do-not-print" not in json.dumps(result)


@pytest.mark.fab_test
def test_cloud_analyzer_readiness_keeps_the_stable_five_keys(monkeypatch):
    """A not-ready cloud row has the same shape as every other row (JSON consumers)."""
    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)
    monkeypatch.setattr(registry, "desktop_ports", list)  # no instance running

    result = registry.check_readiness("pql_test", None)

    assert set(result.keys()) == {"ready", "resolved_path", "reason", "remediation", "version"}


@pytest.mark.fab_test
def test_readiness_probe_spawns_no_subprocess_for_a_cloud_analyzer(monkeypatch):
    """The probe stays cheap: no subprocess, per check_readiness's contract."""
    import subprocess

    from fabric_ci_cd_dataops.scripts import fab_test_registry as registry

    _clear_cloud_env(monkeypatch)

    def _fail(*args, **kwargs):
        raise AssertionError("check_readiness must not spawn a subprocess")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)

    registry.check_readiness("pql_test", None)
