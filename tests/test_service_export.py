"""Contract tests for the definition export seam (Service Targeting epic).

A fake Fabric client stands in for the service, so these exercise export,
enumeration, caching, cleanup and refusal rules without a tenant.
"""

import argparse
import base64
import re
from pathlib import Path

import pytest

from fab_test.scripts import _service_export as svc
from fab_test.scripts._mode import resolve_mode
from fab_test.scripts._target import parse_target
from fab_test.scripts.playwright_validation.service_client import ServiceClientError

WS = "11111111-1111-1111-1111-111111111111"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class FakeClient:
    access_token = "token"

    def __init__(self, count: int = 1) -> None:
        self.items = [{"id": f"id{i}", "displayName": f"Item{i}"} for i in range(count)]

    def list_items(self, workspace_id, item_type):
        return self.items


@pytest.fixture
def fake(monkeypatch):
    calls: list[str] = []
    client = FakeClient()

    def get_definition(self, workspace_id, item_id, *, definition_format=""):
        calls.append(item_id)
        return [
            {"path": "definition/model.tmdl", "payload": _b64("connectionString: ******;")},
            {"path": "definition.pbism", "payload": _b64("{}")},
        ]

    monkeypatch.setattr(svc, "build_service_client", lambda args: client)
    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition",
        get_definition,
    )
    return client, calls


def _args(target=None, **extra):
    resolved = parse_target(target, default_type="SemanticModel") if target else None
    ns = argparse.Namespace(
        resolved_target=resolved,
        workspace_id=extra.pop("workspace_id", "Dev"),
        analyzer=extra.pop("analyzer", "bpa"),
        dry_run=False,
        keep_export=False,
        all_items=False,
        mode="service",
        **extra,
    )
    ns.resolved_mode = resolve_mode(resolved, workspace_flag="" if resolved else ns.workspace_id)
    return ns


def test_given_typed_target_should_export_definition_folder(fake, tmp_path):
    client, calls = fake
    client.items = [{"id": "m1", "displayName": "Sales"}]
    args = _args("Dev.Workspace/Sales.SemanticModel", workspace_id=WS)
    [artifact] = svc.export_for_analyzer("bpa", args, tmp_path)
    assert artifact.name == "Sales.SemanticModel"
    assert (artifact / "definition" / "model.tmdl").exists()
    assert calls == ["m1"]


def test_given_untyped_target_should_resolve_by_analyzer_type(fake, tmp_path):
    client, _ = fake
    client.items = [{"id": "m1", "displayName": "Sales"}]
    args = _args("Dev.Workspace/Sales", workspace_id=WS)
    assert args.resolved_target.type == "SemanticModel"
    assert svc.export_for_analyzer("bpa", args, tmp_path)[0].name == "Sales.SemanticModel"


def test_given_unknown_name_should_name_the_candidates(fake, tmp_path):
    client, _ = fake
    client.items = [{"id": "m1", "displayName": "Sales"}]
    args = _args("Dev.Workspace/Nope.SemanticModel", workspace_id=WS)
    with pytest.raises(svc.ServiceExportError, match="Sales"):
        svc.export_for_analyzer("bpa", args, tmp_path)


def test_given_no_target_should_enumerate_every_item(fake, tmp_path):
    client, calls = fake
    client.items = [{"id": f"m{i}", "displayName": f"M{i}"} for i in range(3)]
    args = _args(None, workspace_id=WS)
    assert len(svc.export_for_analyzer("bpa", args, tmp_path)) == 3
    assert calls == ["m0", "m1", "m2"]


def test_given_more_than_50_items_should_refuse_with_exit_2_unless_all(fake, tmp_path):
    client, _ = fake
    client.items = [{"id": f"m{i}", "displayName": f"M{i}"} for i in range(51)]
    with pytest.raises(svc.ServiceExportError, match="--all") as refused:
        svc.export_for_analyzer("bpa", _args(None, workspace_id=WS), tmp_path)
    assert refused.value.code == 2
    forced = _args(None, workspace_id=WS)
    forced.all_items = True
    assert len(svc.export_for_analyzer("bpa", forced, tmp_path)) == 51


def test_given_two_analyzers_on_one_report_should_export_once(fake, tmp_path):
    client, calls = fake
    client.items = [{"id": "r1", "displayName": "Rpt"}]
    args = _args("Dev.Workspace/Rpt.Report", workspace_id=WS)
    first = svc.export_for_analyzer("pbir", args, tmp_path)
    second = svc.export_for_analyzer("a11y", args, tmp_path)
    assert first == second
    assert calls == ["r1"]


def test_given_a_run_should_delete_exports_by_default(fake, tmp_path):
    client, _ = fake
    client.items = [{"id": "m1", "displayName": "Sales"}]
    args = _args("Dev.Workspace/Sales.SemanticModel", workspace_id=WS)
    [artifact] = svc.export_for_analyzer("bpa", args, tmp_path)
    svc.finalize_exports(args)
    assert not artifact.exists()


def test_given_keep_export_should_keep_and_redact_secrets(fake, tmp_path):
    client, _ = fake
    client.items = [{"id": "m1", "displayName": "Sales"}]
    args = _args("Dev.Workspace/Sales.SemanticModel", workspace_id=WS)
    args.keep_export = True
    [artifact] = svc.export_for_analyzer("bpa", args, tmp_path)
    svc.finalize_exports(args)
    text = (artifact / "definition" / "model.tmdl").read_text()
    assert "hunter2" not in text
    assert "******" in text


def test_given_dry_run_with_typed_target_should_not_touch_the_service(monkeypatch, tmp_path):
    def boom(args):
        raise AssertionError("dry-run must not build a client")

    monkeypatch.setattr(svc, "build_service_client", boom)
    args = _args("Dev.Workspace/Sales.SemanticModel")
    args.dry_run = True
    assert svc.export_for_analyzer("bpa", args, tmp_path) == [Path("Dev/Sales.SemanticModel")]


@pytest.mark.parametrize("status,needle", [(404, "enhanced/Git-integration"), (403, "fab-test auth status")])
def test_given_getdefinition_failure_should_name_a_remediation(fake, tmp_path, monkeypatch, status, needle):
    client, _ = fake
    client.items = [{"id": "m1", "displayName": "Sales"}]

    def fail(self, *a, **k):
        raise ServiceClientError("HTTP", status_code=status, body="raw body")

    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition", fail
    )
    args = _args("Dev.Workspace/Sales.SemanticModel", workspace_id=WS)
    with pytest.raises(svc.ServiceExportError, match=needle) as err:
        svc.export_for_analyzer("bpa", args, tmp_path)
    assert "raw body" not in str(err.value)


def test_given_a_failed_getdefinition_operation_should_name_fabric_error_code(fake, tmp_path, monkeypatch):
    client, _ = fake
    client.items = [{"id": "r1", "displayName": "Rpt"}]
    body = '{"status":"Failed","error":{"errorCode":"Some_FabricError","message":"it broke"}}'

    def fail(self, *a, **k):
        raise ServiceClientError("Long-running operation failed", status_code=200, body=body)

    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition", fail
    )
    args = _args("Dev.Workspace/Rpt.Report", workspace_id=WS, analyzer="pbir")
    with pytest.raises(svc.ServiceExportError, match="Some_FabricError: it broke"):
        svc.export_for_analyzer("pbir", args, tmp_path)


def _report_parts(legacy: bool) -> list[dict[str, str]]:
    report = "report.json" if legacy else "definition/report.json"
    return [{"path": "definition.pbir", "payload": _b64("{}")}, {"path": report, "payload": _b64("{}")}]


@pytest.fixture
def reports(monkeypatch):
    """Fake service holding one PBIR and one PBIR-Legacy report."""
    client = FakeClient()
    client.items = [{"id": "new", "displayName": "Modern"}, {"id": "old", "displayName": "Legacy"}]
    formats: list[str] = []

    def get_definition(self, workspace_id, item_id, *, definition_format=""):
        formats.append(definition_format)
        return _report_parts(legacy=item_id == "old")

    monkeypatch.setattr(svc, "build_service_client", lambda args: client)
    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition",
        get_definition,
    )
    return client, formats


def test_given_a_pbir_legacy_report_should_skip_it_and_fail_the_run(reports, tmp_path, capsys):
    _, formats = reports
    args = _args(None, workspace_id=WS, analyzer="pbir")
    artifacts = svc.export_for_analyzer("pbir", args, tmp_path)
    assert [a.name for a in artifacts] == ["Modern.Report"]
    assert formats == ["", ""]  # the report's stored format; Fabric will not convert legacy
    assert "Legacy.Report skipped" in capsys.readouterr().out
    assert svc.service_skip_exit("pbir", args) == 1


def test_given_only_pbir_legacy_reports_should_exit_1_naming_them(reports, tmp_path):
    client, _ = reports
    client.items = [{"id": "old", "displayName": "Legacy"}]
    args = _args(None, workspace_id=WS, analyzer="pbir")
    with pytest.raises(svc.ServiceExportError, match=r"Legacy\.Report.*PBIR-Legacy") as err:
        svc.export_for_analyzer("pbir", args, tmp_path)
    assert err.value.code == 1


def test_given_no_skipped_report_should_not_change_the_exit(reports, tmp_path):
    client, _ = reports
    client.items = [{"id": "new", "displayName": "Modern"}]
    args = _args(None, workspace_id=WS, analyzer="pbir")
    svc.export_for_analyzer("pbir", args, tmp_path)
    assert svc.service_skip_exit("pbir", args) == 0


@pytest.mark.parametrize(
    "credential_source,expected",
    [
        ("ambient:DefaultAzureCredential", "auth=ambient:DefaultAzureCredential"),
        ("service-principal", "auth=service-principal (.fab-test/.env)"),
    ],
)
def test_given_a_service_export_should_name_the_credential_once(
    fake, tmp_path, monkeypatch, capsys, credential_source, expected
):
    client, _ = fake
    client.credential_source = credential_source
    client.items = [{"id": "r1", "displayName": "Rpt"}]
    monkeypatch.setattr(
        svc, "probe_credentials", lambda env_file=None: argparse.Namespace(source=".fab-test/.env")
    )
    args = _args("Dev.Workspace/Rpt.Report", workspace_id=WS, analyzer="all")
    svc.export_for_analyzer("pbir", args, tmp_path)
    svc.export_for_analyzer("a11y", args, tmp_path)
    assert capsys.readouterr().err.count(expected) == 1


def test_given_json_output_should_not_print_the_credential(fake, tmp_path, capsys):
    client, _ = fake
    client.credential_source = "ambient:DefaultAzureCredential"
    client.items = [{"id": "r1", "displayName": "Rpt"}]
    args = _args("Dev.Workspace/Rpt.Report", workspace_id=WS, analyzer="pbir", output_format="json")
    svc.export_for_analyzer("pbir", args, tmp_path)
    assert "auth=" not in capsys.readouterr().err


def test_given_unsafe_definition_path_should_refuse(tmp_path):
    parts = [{"path": "../evil.tmdl", "payload": _b64("x")}]
    with pytest.raises(svc.ServiceExportError, match="unsafe"):
        svc._write_parts(parts, tmp_path, "SemanticModel", "Sales")


def test_given_paginated_report_should_write_a_flat_rdl(tmp_path):
    parts = [{"path": "report.rdl", "payload": _b64("<Report/>")}]
    artifact = svc._write_parts(parts, tmp_path, "PaginatedReport", "Weekly")
    assert artifact.name == "Weekly.rdl"
    assert artifact.read_text() == "<Report/>"


def test_given_ci_or_flag_off_should_refuse_interactive(monkeypatch):
    for var in svc._CI_VARIABLES:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("FAB_TEST_INTERACTIVE_AUTH", raising=False)
    args = argparse.Namespace(interactive=True, file_config={})
    assert svc.interactive_refusal(args) is None
    args.file_config = {"interactive_auth": "off"}
    assert "interactive_auth" in svc.interactive_refusal(args)
    args.file_config = {"interactive_auth": False}
    assert svc.interactive_refusal(args)
    args.file_config = {}
    monkeypatch.setenv("FAB_TEST_INTERACTIVE_AUTH", "0")
    assert "FAB_TEST_INTERACTIVE_AUTH" in svc.interactive_refusal(args)
    monkeypatch.delenv("FAB_TEST_INTERACTIVE_AUTH")
    monkeypatch.setenv("CI", "true")
    assert "CI" in svc.interactive_refusal(args)


def test_given_pql_test_should_only_export_under_all():
    args = argparse.Namespace(mode="service", analyzer="pql_test")
    assert not svc.is_service_run("pql_test", args)
    args.analyzer = "all"
    assert svc.is_service_run("pql_test", args)
    args.mode = "repo"
    assert not svc.is_service_run("bpa", args)


def test_given_a_path_target_with_workspace_should_refuse():
    args = argparse.Namespace(
        mode="service", analyzer="bpa", resolved_target=parse_target("./src/Sales.SemanticModel")
    )
    assert "path" in svc.service_target_refusal("bpa", args)


# --------------------------------------------------------------------------- #
# CLI wiring
# --------------------------------------------------------------------------- #


def _cli(*argv, env=None, cwd=None):
    import os
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        cwd=cwd,
        check=False,
    )


def test_given_any_run_should_print_the_mode_banner_first(tmp_path):
    result = _cli("bpa", "--dry-run", "--artifact-dir", str(tmp_path))
    assert result.stderr.splitlines()[0] == "mode=repo workspace=— source=default"


def test_given_desktop_target_with_workspace_flag_should_exit_2(tmp_path):
    result = _cli("bpa", "local/Sales", "--workspace", "Dev", "--artifact-dir", str(tmp_path))
    assert result.returncode == 2
    assert "local/Sales" in result.stderr


def test_given_interactive_in_ci_should_exit_2_naming_ci(tmp_path):
    result = _cli("bpa", "--workspace", WS, "--interactive", env={"CI": "true"}, cwd=tmp_path)
    assert result.returncode == 2
    assert "CI" in result.stderr


def test_given_typed_service_target_dry_run_should_list_the_item_without_credentials(tmp_path):
    result = _cli(
        "rdl", "Dev.Workspace/Weekly.PaginatedReport", "--dry-run", "--artifact-dir", str(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    assert "mode=service workspace=Dev source=target" in result.stderr
    assert "Weekly.rdl" in result.stdout


def test_given_json_format_should_keep_stderr_silent_but_still_resolve_mode(tmp_path):
    result = _cli("bpa", "--dry-run", "--format", "json", "--artifact-dir", str(tmp_path))
    assert "mode=" not in result.stderr


def test_given_dot_dot_names_should_never_escape_the_output_dir(fake, tmp_path):
    client, _ = fake
    client.items = [{"id": "m1", "displayName": ".."}]
    args = _args("Dev.Workspace/Sales.SemanticModel", workspace_id=WS)
    args.resolved_target = parse_target("Dev.Workspace/...SemanticModel", default_type="SemanticModel")
    [artifact] = svc.export_for_analyzer("bpa", args, tmp_path / "out")
    assert (tmp_path / "out").resolve() in artifact.resolve().parents
    svc.finalize_exports(args)
    assert (tmp_path / "out").exists()


def test_given_json_secrets_should_be_redacted_in_kept_exports(fake, tmp_path):
    client, _ = fake
    client.items = [{"id": "m1", "displayName": "Sales"}]
    args = _args("Dev.Workspace/Sales.SemanticModel", workspace_id=WS)
    args.keep_export = True
    [artifact] = svc.export_for_analyzer("bpa", args, tmp_path)
    (artifact / "x.dat").write_text('{"password": "hunter2"}')
    svc.finalize_exports(args)
    assert "hunter2" not in (artifact / "x.dat").read_text()


@pytest.mark.parametrize("verbose", [0, 1])
def test_given_default_or_verbose_should_announce_each_export_with_its_duration(fake, tmp_path, capsys, verbose):
    client, _ = fake
    client.items = [{"id": "m0", "displayName": "Sales"}, {"id": "m1", "displayName": "Ops"}]
    svc.export_for_analyzer("bpa", _args(None, workspace_id=WS, verbose=verbose), tmp_path)
    auth, *lines = capsys.readouterr().err.splitlines()
    assert auth.startswith("auth=")  # the credential is named before any export starts
    assert [line.split("...")[0] for line in lines] == [
        "exporting Sales.SemanticModel",
        "exporting Ops.SemanticModel",
    ]
    assert all(re.search(r"\.\.\. done \(\d+\.\ds\)$", line) for line in lines)


@pytest.mark.parametrize("extra", [{"quiet": True}, {"output_format": "json"}])
def test_given_quiet_or_json_should_export_silently(fake, tmp_path, capsys, extra):
    svc.export_for_analyzer("bpa", _args(None, workspace_id=WS, **extra), tmp_path)
    assert capsys.readouterr().err == ""


def test_given_a_failed_export_should_close_its_progress_line(fake, tmp_path, capsys, monkeypatch):
    def fail(self, *a, **k):
        raise ServiceClientError("HTTP", status_code=404)

    monkeypatch.setattr(
        "fab_test.scripts.playwright_validation.service_client.FabricRestClient.get_item_definition", fail
    )
    with pytest.raises(svc.ServiceExportError):
        svc.export_for_analyzer("bpa", _args(None, workspace_id=WS), tmp_path)
    assert capsys.readouterr().err.endswith("\nexporting Item0.SemanticModel... failed\n")


def test_given_no_target_should_skip_microsoft_usage_metrics_models(fake, tmp_path):
    client, calls = fake
    client.items = [
        {"id": "m1", "displayName": "Sales"},
        {"id": "um", "displayName": "Dashboard Usage Metrics Model"},
    ]
    [artifact] = svc.export_for_analyzer("bpa", _args(None, workspace_id=WS), tmp_path)
    assert artifact.name == "Sales.SemanticModel"
    assert calls == ["m1"]


def test_given_a_usage_metrics_model_named_as_target_should_still_export_it(fake, tmp_path):
    client, calls = fake
    client.items = [{"id": "um", "displayName": "Dashboard Usage Metrics Model"}]
    args = _args("Dev.Workspace/Dashboard Usage Metrics Model.SemanticModel", workspace_id=WS)
    assert svc.export_for_analyzer("bpa", args, tmp_path)[0].name == "Dashboard Usage Metrics Model.SemanticModel"
    assert calls == ["um"]
