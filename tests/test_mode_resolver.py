"""Contract tests for the mode resolver (Service Targeting epic, Mode Resolver).

Pure function: no filesystem, no network, always passes on any machine.
"""

import pytest

from fab_test.scripts._mode import ModeError, resolve_mode
from fab_test.scripts._target import parse_target


def _t(raw):
    return parse_target(raw) if raw else None


def test_given_bare_invocation_should_be_local_default():
    r = resolve_mode(None)
    assert (r.mode, r.workspace, r.source, r.path) == ("local", None, "default", ".")


@pytest.mark.parametrize("raw", ["Sales.SemanticModel", "./src/Sales.SemanticModel"])
def test_given_path_target_should_be_local_from_target(raw):
    r = resolve_mode(_t(raw))
    assert (r.mode, r.source) == ("local", "target")


def test_given_desktop_target_should_be_local_at_that_instance():
    """Power BI Desktop is on this machine too: one local mode, the instance as its path."""
    r = resolve_mode(_t("local/Sales"))
    assert (r.mode, r.workspace, r.source, r.path) == ("local", None, "target", "local/Sales")


def test_given_workspace_target_should_be_service():
    r = resolve_mode(_t("Dev.Workspace/Sales.SemanticModel"))
    assert (r.mode, r.workspace, r.source) == ("service", "Dev", "target")


def test_given_workspace_flag_alone_should_be_service_from_flag():
    r = resolve_mode(None, workspace_flag="Dev")
    assert (r.mode, r.workspace, r.source) == ("service", "Dev", "flag")


def test_given_desktop_target_and_workspace_flag_should_raise_naming_both():
    with pytest.raises(ModeError, match=r"local/Sales.*--workspace"):
        resolve_mode(_t("local/Sales"), workspace_flag="Dev")


def test_given_flag_and_target_naming_other_workspace_should_raise():
    with pytest.raises(ModeError, match=r"Dev.*Prod"):
        resolve_mode(_t("Dev.Workspace/Sales.Report"), workspace_flag="Prod")


def test_given_flag_matching_target_workspace_should_be_service():
    r = resolve_mode(_t("Dev.Workspace/Sales.Report"), workspace_flag="Dev")
    assert (r.mode, r.workspace, r.source) == ("service", "Dev", "target")


def test_given_path_target_with_workspace_flag_should_be_service():
    r = resolve_mode(_t("Sales.Report"), workspace_flag="Dev")
    assert (r.mode, r.workspace, r.source) == ("service", "Dev", "flag")


def test_given_explicit_artifact_dir_with_workspace_flag_should_be_local():
    r = resolve_mode(None, workspace_flag="Dev", artifact_dir_explicit=True)
    assert r.mode == "local"


def test_given_an_artifact_dir_inside_the_working_directory_should_show_it_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_mode(None, artifact_dir=str(tmp_path)).path == "."
    assert resolve_mode(None, artifact_dir=str(tmp_path / "src")).path == "src"


def test_given_an_artifact_dir_outside_the_working_directory_should_show_it_whole(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = str(tmp_path.parent / "elsewhere")
    assert resolve_mode(None, artifact_dir=outside).path == outside


def test_banner_line_shape():
    r = resolve_mode(_t("Dev.Workspace/Sales.Report"))
    assert r.banner() == "mode=service workspace=Dev source=target"
    assert resolve_mode(None).banner() == "mode=local path=. source=default"
    assert resolve_mode(_t("local/Sales")).banner() == "mode=local path=local/Sales source=target"
