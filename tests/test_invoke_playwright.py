"""Contract tests for the invoke_playwright wrapper."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# Match the import path used by invoke_playwright.py so exception classes compare
# equal when patched.
from fabric_ci_cd_dataops.scripts.invoke_playwright import (
    _build_config_from_args,
    _build_env_for_pytest,
    _parse_pytest_summary,
    _write_findings,
    main,
    parse_args,
    run_playwright_validation,
)
from fabric_ci_cd_dataops.scripts.playwright_validation.config import PlaywrightValidationConfig
from fabric_ci_cd_dataops.scripts.playwright_validation.power_bi_api import EmbedContext, PowerBiApiError
from fabric_ci_cd_dataops.scripts.playwright_validation.resolver import (
    ResolvedEnvironment,
    ResolvedReport,
    ServiceResolutionError,
)


@pytest.fixture
def config() -> PlaywrightValidationConfig:
    """Return a minimal config for wrapper tests."""
    return PlaywrightValidationConfig(
        workspace_id="ws-1",
        report_id="rpt-1",
        report_name="Report",
        dataset_id="ds-1",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=60,
        headless=True,
    )


def test_parse_args_requires_no_arguments() -> None:
    """The wrapper can be invoked with no CLI arguments."""
    args = parse_args([])
    assert args.env_file is None
    assert args.output_path is None
    assert args.verbose == 0


def test_parse_args_picks_up_env_file_and_output_path() -> None:
    """CLI flags are parsed into the namespace."""
    args = parse_args(["--env-file", ".env", "--output-path", "out.json", "-vv"])
    assert args.env_file == ".env"
    assert args.output_path == "out.json"
    assert args.verbose == 2


def test_write_findings_empty_on_success() -> None:
    """No findings are emitted when the run succeeds."""
    from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import TestCase

    case = TestCase(
        test_case="Report_default-page_no-bookmark",
        report_name="Report",
        report_id="rpt-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="ds-1",
        user_name="",
        role="",
    )
    assert _write_findings([case], success=True, message="") == []


def test_write_findings_on_failure() -> None:
    """Each case becomes an error finding when the run fails."""
    from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import TestCase

    case = TestCase(
        test_case="Report_default-page_no-bookmark",
        report_name="Report",
        report_id="rpt-1",
        workspace_id="ws-1",
        page_id="",
        page_name="",
        bookmark_id="",
        bookmark_name="",
        dataset_id="ds-1",
        user_name="",
        role="",
    )
    findings = _write_findings([case], success=False, message="render timeout")

    assert len(findings) == 1
    assert findings[0]["rule"] == "visual_load_failed"
    assert findings[0]["severity"] == "error"
    assert findings[0]["object"] == "Report_default-page_no-bookmark"
    assert findings[0]["message"] == "render timeout"


@pytest.mark.fab_test
def test_pytest_html_and_pytest_playwright_are_dev_dependencies() -> None:
    """`_run_pytest` passes `--html`/`--self-contained-html`, and the spec needs
    `pytest-playwright`'s fixtures. A fresh `pip install -e ".[dev]"` must provide
    both, or pytest rejects the flags as unrecognized (as it did in production)."""
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(d.startswith("pytest-html") for d in dev), dev
    assert any(d.startswith("pytest-playwright") for d in dev), dev


def test_build_env_for_pytest_sets_expected_vars(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """The pytest environment includes CSV path, embed config, timeout,
    and results root."""

    from fabric_ci_cd_dataops.scripts.playwright_validation.test_cases import generate_test_cases

    cases = generate_test_cases(config)
    embed_config = {"type": "report", "id": "rpt-1"}

    env = _build_env_for_pytest(config, cases, embed_config, tmp_path)

    assert env["PLAYWRIGHT_TEST_CASES"] == str((tmp_path / "test-cases.csv").resolve())
    assert env["PLAYWRIGHT_EMBED_CONFIG"] == '{"type": "report", "id": "rpt-1"}'
    assert env["PLAYWRIGHT_TIMEOUT_MS"] == "60000"
    assert env["PLAYWRIGHT_HEADLESS"] == "true"
    assert env["PLAYWRIGHT_RESULTS_ROOT"] == str(tmp_path.resolve())


def test_parse_pytest_summary_extracts_short_summary() -> None:
    """The pytest short summary line is extracted from stdout."""
    stdout = "some output\n1 passed in 1.23s"
    assert _parse_pytest_summary(stdout) == "1 passed in 1.23s"


def test_main_writes_envelope_and_returns_zero_on_success(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """A successful pytest run writes a passed envelope and returns 0."""
    output_path = tmp_path / "envelope.json"
    embed_context = EmbedContext(
        embed_url="https://app.powerbi.com/embed",
        embed_token="token",
        report_id="rpt-1",
        dataset_id="ds-1",
    )
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="1 passed in 1.0s",
        stderr="",
    )

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_discovery", return_value=(None, None)),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.discovery.get_embed_context",
            return_value=embed_context,
        ),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._run_pytest", return_value=completed),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 0
    assert output_path.exists()
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "passed"' in data


def test_main_writes_envelope_and_returns_one_on_failure(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """A failed pytest run writes a failed envelope and returns 1."""
    output_path = tmp_path / "envelope.json"
    embed_context = EmbedContext(
        embed_url="https://app.powerbi.com/embed",
        embed_token="token",
        report_id="rpt-1",
        dataset_id="ds-1",
    )
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="1 failed in 1.0s",
        stderr="",
    )

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_discovery", return_value=(None, None)),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.discovery.get_embed_context",
            return_value=embed_context,
        ),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._run_pytest", return_value=completed),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 1
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "failed"' in data


def test_main_returns_one_on_api_error(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """A Power BI API error writes an error envelope and returns 1."""
    output_path = tmp_path / "envelope.json"

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_discovery", return_value=(None, None)),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.discovery.get_embed_context",
            side_effect=PowerBiApiError("boom", 400),
        ),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 1
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "error"' in data
    assert "boom" in data


def test_discovered_roles_without_user_name_fail_before_minting_a_token(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """Discovered roles with no PLAYWRIGHT_USER_NAME abort before any embed
    token is minted -- GenerateToken silently drops the RLS identity when
    the username is empty, so the run would otherwise pass while testing
    no role at all."""
    output_path = tmp_path / "envelope.json"

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_discovery",
            return_value=(None, ["Manager"]),
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.acquire_embed_configs"
        ) as mock_acquire,
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 1
    mock_acquire.assert_not_called()
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "error"' in data
    assert "PLAYWRIGHT_USER_NAME" in data
    assert "Manager" in data


def test_resolution_exception_writes_envelope_instead_of_a_traceback(
    tmp_path: Path,
) -> None:
    """An exception while resolving config/client (not just embed-context)
    never reaches the console as a traceback either.

    Live-testing task 7's end-to-end scenario surfaced this: a real
    `azure.core.exceptions.ClientAuthenticationError` from
    `build_fabric_service_client` during `--artifact` discovery -- raised
    by `_build_config_from_args`, before `_run_single_report` is ever
    called -- ran clean off the top of `run_playwright_validation` even
    after task 2's embed-context catch-all, because that catch-all only
    wraps `get_embed_context`. The wrapper's own goal ("no traceback, no
    metadata scavenger hunt") does not stop at the embed-token step.
    """
    with patch(
        "fabric_ci_cd_dataops.scripts.invoke_playwright._build_config_from_args",
        side_effect=RuntimeError("token service unreachable"),
    ):
        args = parse_args(
            ["--artifact", "ThinReport", "--env", "dev", "--output-path", str(tmp_path / "envelope.json")]
        )
        code = run_playwright_validation(args)

    assert code == 1
    data = (tmp_path / "envelope.json").read_text(encoding="utf-8")
    assert '"status": "error"' in data
    assert "token service unreachable" in data


def test_main_returns_one_on_unexpected_exception(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
) -> None:
    """Any exception during embed-context acquisition writes an envelope,
    never a bare traceback.

    `_run_single_report` used to catch only `PowerBiApiError`; every other
    exception -- an `msal` `ValueError` chief among them -- ran clean off
    the top of `sys.exit(main())`. The agent caller sees `run.json`'s
    ``"detail": null`` for that, which is worse than a wrong answer.
    """
    output_path = tmp_path / "envelope.json"

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_discovery", return_value=(None, None)),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.discovery.get_embed_context",
            side_effect=ValueError("Unable to parse QueryString"),
        ),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    assert code == 1
    data = output_path.read_text(encoding="utf-8")
    assert '"status": "error"' in data
    assert "Unable to parse QueryString" in data


def test_unexpected_exception_writes_error_annotation_to_stderr(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
    capsys,
) -> None:
    """The catch-all emits ``::error::`` to stderr, keeping stdout pure JSON."""
    output_path = tmp_path / "envelope.json"

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_discovery", return_value=(None, None)),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.discovery.get_embed_context",
            side_effect=RuntimeError("boom"),
        ),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root", return_value=tmp_path),
    ):
        code = main(["--env-file", ".env", "--output-path", str(output_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert "::error::" in captured.err
    assert "boom" in captured.err
    assert "Traceback" not in captured.err


def test_resolution_failure_in_impact_run_leaves_other_artifacts_intact(
    config: PlaywrightValidationConfig,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """One report's unexpected exception does not stop the other reports in
    the same `--impact-manifest` run, and each result lands in the summary."""
    import json as _json

    monkeypatch.chdir(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        _json.dumps(
            {
                "reports": [
                    {
                        "workspace_id": "ws-1",
                        "report_id": "rpt-bad",
                        "report_name": "Bad Report",
                        "semantic_model_id": "ds-1",
                        "environment": "DEV",
                    },
                    {
                        "workspace_id": "ws-1",
                        "report_id": "rpt-good",
                        "report_name": "Good Report",
                        "semantic_model_id": "ds-1",
                        "environment": "DEV",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    embed_context = EmbedContext(
        embed_url="https://app.powerbi.com/embed",
        embed_token="token",
        report_id="rpt-good",
        dataset_id="ds-1",
    )
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="1 passed in 1.0s", stderr=""
    )

    def fake_get_embed_context(cfg):
        if cfg.report_id == "rpt-bad":
            raise RuntimeError("token service unavailable")
        return embed_context

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config",
            return_value=config,
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_discovery",
            return_value=(None, None),
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.playwright_validation.discovery.get_embed_context",
            side_effect=fake_get_embed_context,
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright._run_pytest",
            return_value=completed,
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright._repo_root",
            return_value=tmp_path,
        ),
    ):
        args = parse_args(["--impact-manifest", str(manifest_path)])
        code = run_playwright_validation(args)

    assert code == 1  # overall failed because one report errored

    from fabric_ci_cd_dataops.scripts._analyzer_envelope import envelope_path

    bad_envelope = envelope_path("playwright", "Bad Report")
    good_envelope = envelope_path("playwright", "Good Report")
    assert '"status": "error"' in bad_envelope.read_text(encoding="utf-8")
    assert '"status": "passed"' in good_envelope.read_text(encoding="utf-8")


def test_build_config_from_args_uses_service_client_for_artifact() -> None:
    """--artifact resolves the deployed report via the Fabric service client."""
    config = PlaywrightValidationConfig(
        workspace_id="",
        report_id="",
        report_name="",
        dataset_id="",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=60,
        headless=True,
    )
    resolved = ResolvedReport(
        workspace_id="ws-resolved",
        report_id="rpt-resolved",
        report_name="Resolved Report",
        semantic_model_id="ds-resolved",
        environment="DEV",
    )
    client = object()

    with (
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_environment") as mock_env,
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_report", return_value=resolved) as mock_report,
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.build_fabric_service_client",
            return_value=client,
        ) as mock_client,
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV",
            workspace_id="ws-resolved",
        )
        args = parse_args(
            ["--artifact", "Resolved Report", "--env", "dev", "--env-file", ".env"]
        )
        result = _build_config_from_args(args)

    assert result.workspace_id == "ws-resolved"
    assert result.report_id == "rpt-resolved"
    assert result.report_name == "Resolved Report"
    assert result.dataset_id == "ds-resolved"
    mock_client.assert_called_once()
    mock_env.assert_called_once_with(
        "dev",
        workspace_id_override="",
    )
    mock_report.assert_called_once_with(
        "Resolved Report", mock_env.return_value, client
    )


def test_build_config_loads_config_without_required_ids_for_artifact() -> None:
    """Static report IDs are not required when --artifact performs service lookup."""
    config = PlaywrightValidationConfig(
        workspace_id="",
        report_id="",
        report_name="",
        dataset_id="",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="client-1",
        client_secret="secret-1",
        tenant_id="tenant-1",
        timeout_seconds=60,
        headless=True,
    )
    resolved = ResolvedReport(
        workspace_id="ws-resolved",
        report_id="rpt-resolved",
        report_name="Resolved Report",
        semantic_model_id="ds-resolved",
        environment="DEV",
    )

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config",
            return_value=config,
        ) as mock_load,
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_environment") as mock_env,
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_report", return_value=resolved),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.build_fabric_service_client"),
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV",
            workspace_id="ws-resolved",
        )
        args = parse_args(
            ["--artifact", "Resolved Report", "--env", "dev"]
        )
        _build_config_from_args(args)

    mock_load.assert_called_once_with(None, required=False)


@pytest.mark.playwright
def test_build_config_refuses_incomplete_service_principal_before_any_client(
) -> None:
    """`--artifact` with an incomplete service principal refuses immediately.

    `_build_config_from_args` used to disable the required-field check
    whenever `--artifact` was passed -- which the CLI always does -- so an
    empty tenant reached msal two API calls later as a raw traceback. The
    fix validates the service principal unconditionally, before
    `build_fabric_service_client` is even imported, let alone called.
    """
    incomplete = PlaywrightValidationConfig(
        workspace_id="",
        report_id="",
        report_name="",
        dataset_id="",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="",
        client_secret="",
        tenant_id="",
        timeout_seconds=60,
        headless=True,
    )

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config",
            return_value=incomplete,
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.build_fabric_service_client"
        ) as mock_client,
    ):
        args = parse_args(["--artifact", "ThinReport", "--env", "dev"])

        with pytest.raises(ValueError) as exc_info:
            _build_config_from_args(args)

    message = str(exc_info.value)
    assert "FABRIC_TENANT_ID" in message
    assert "FABRIC_CLIENT_ID" in message
    assert "FABRIC_CLIENT_SECRET" in message
    assert ".env" in message
    assert "--env-file" in message
    mock_client.assert_not_called()


@pytest.mark.playwright
def test_incomplete_service_principal_refusal_exits_127() -> None:
    """The refusal is a missing prerequisite (127), not a generic failure (1).

    127 is the readiness-probe exit code the rest of the CLI already uses
    for "cannot even attempt this" -- see vision.md's exit-code contract.
    """
    incomplete = PlaywrightValidationConfig(
        workspace_id="",
        report_id="",
        report_name="",
        dataset_id="",
        page_ids=[],
        bookmark_ids=[],
        user_name="",
        role="",
        use_rls=False,
        cloud="public",
        client_id="",
        client_secret="",
        tenant_id="",
        timeout_seconds=60,
        headless=True,
    )

    with patch(
        "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config",
        return_value=incomplete,
    ):
        args = parse_args(["--artifact", "ThinReport", "--env", "dev"])

        exit_code = run_playwright_validation(args)

    assert exit_code == 127


@pytest.mark.playwright
def test_complete_service_principal_behaves_as_before(config) -> None:
    """A complete service principal still resolves via the service client."""
    resolved = ResolvedReport(
        workspace_id="ws-resolved",
        report_id="rpt-resolved",
        report_name="Resolved Report",
        semantic_model_id="ds-resolved",
        environment="DEV",
    )

    with (
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config",
            return_value=config,
        ),
        patch("fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_environment") as mock_env,
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.resolve_report",
            return_value=resolved,
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.build_fabric_service_client"
        ) as mock_client,
    ):
        mock_env.return_value = ResolvedEnvironment(
            environment="DEV",
            workspace_id="ws-resolved",
        )
        args = parse_args(["--artifact", "Resolved Report", "--env", "dev"])

        result = _build_config_from_args(args)

    assert result.report_id == "rpt-resolved"
    mock_client.assert_called_once()


@pytest.mark.playwright
def test_build_config_refuses_an_artifact_with_no_environment(config) -> None:
    """`fab-test playwright` from a bare CWD used to crash with a traceback.

    The environment came from ``args.environment or config.environment or
    "dev"``, and `PlaywrightValidationConfig` has no ``environment`` field
    -- so the middle term raised AttributeError and the `"dev"` fallback
    behind it was unreachable. Only a truthy ``args.environment``
    short-circuited past it, which is why passing --env hid this.
    """
    with patch(
        "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config
    ):
        args = parse_args(["--artifact", "ThinReport"])

        with pytest.raises(ServiceResolutionError) as exc_info:
            _build_config_from_args(args)

    message = str(exc_info.value)
    assert "--env" in message, f"the error must say how to fix it: {message}"
    assert "ThinReport" in message


@pytest.mark.playwright
def test_no_environment_is_reported_before_a_credential_is_built(config) -> None:
    """Fail on the missing flag, not on the authentication it would need.

    Building the service client first reports a credential problem when
    the real problem is an absent --env, and spends a network round trip
    against the tenant to do it.
    """
    with (
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config
        ),
        patch(
            "fabric_ci_cd_dataops.scripts.invoke_playwright.build_fabric_service_client"
        ) as mock_client,
    ):
        args = parse_args(["--artifact", "ThinReport"])

        with pytest.raises(ServiceResolutionError):
            _build_config_from_args(args)

    mock_client.assert_not_called()


@pytest.mark.playwright
def test_a_missing_environment_exits_one_without_a_traceback(config, capsys) -> None:
    """The wrapper already catches ServiceResolutionError; keep it that way.

    A traceback across two artifacts is what the user saw. One
    ``::error::`` line and exit 1 is what a CI log and an agent can read.
    """
    with patch(
        "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config
    ):
        args = parse_args(["--artifact", "ThinReport"])

        assert run_playwright_validation(args) == 1

    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.playwright
def test_missing_environment_abort_writes_its_message_to_stderr(config, capsys):
    """Given no --env, the abort message goes to stderr, not stdout.

    The abort happens before any envelope is written, so this message is the
    only record of the reason. fab-test inherits a child's stdout under
    `--format text` and pipes its stderr in every format, so the stream is
    what decides whether `run.json` can carry the remediation or reports
    `"detail": null` -- see tests/test_run_manifest.py. Every other analyzer
    wrapper already sends `::error::` here.

    Uses the full-service-principal `config` fixture so this test isolates
    the missing-`--env` abort from the missing-service-principal refusal
    task 1 added ahead of it.
    """
    args = parse_args(["--artifact", "ThinReport", "--output-path", "unused.json"])

    with patch(
        "fabric_ci_cd_dataops.scripts.invoke_playwright.load_config", return_value=config
    ):
        exit_code = run_playwright_validation(args)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "::error::" in captured.err
    assert "Pass --env" in captured.err
    assert "::error::" not in captured.out
