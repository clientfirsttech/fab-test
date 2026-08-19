"""Contract tests for Power BI Desktop instance detection (Local Desktop First Run §3).

Mocks the filesystem and subprocess primitives Power BI Desktop's local
Analysis Services instance is discoverable through, so these tests pass on
any machine without Power BI Desktop installed or running.

    pytest tests/test_desktop_detection.py
"""

import re
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._desktop import (
    DesktopInstance,
    DesktopMatchError,
    _extract_file_arg,
    detect_desktop_instances,
    match_instance_to_artifact,
)


def _write_port_file(workspaces_root, workspace_name, port):
    data_dir = workspaces_root / workspace_name / "Data"
    data_dir.mkdir(parents=True)
    (data_dir / "msmdsrv.port.txt").write_text(str(port), encoding="utf-16")


@pytest.mark.fab_test
def test_detect_returns_empty_list_on_non_windows_platform(tmp_path, monkeypatch):
    """Detection returns empty rather than failing on a non-Windows platform."""
    from fabric_ci_cd_dataops.scripts import _desktop

    monkeypatch.setattr(_desktop.platform, "system", lambda: "Linux")
    _write_port_file(tmp_path, "AnalysisServicesWorkspace_1", 12345)

    assert detect_desktop_instances(tmp_path) == []


@pytest.mark.fab_test
def test_detect_returns_empty_list_when_workspaces_root_missing(tmp_path, monkeypatch):
    """A nonexistent workspaces root returns an empty list without raising."""
    from fabric_ci_cd_dataops.scripts import _desktop

    monkeypatch.setattr(_desktop.platform, "system", lambda: "Windows")

    assert detect_desktop_instances(tmp_path / "does-not-exist") == []


@pytest.mark.fab_test
def test_detect_returns_empty_list_when_no_instance_running(tmp_path, monkeypatch):
    """An existing but empty workspaces root returns an empty list."""
    from fabric_ci_cd_dataops.scripts import _desktop

    monkeypatch.setattr(_desktop.platform, "system", lambda: "Windows")

    assert detect_desktop_instances(tmp_path) == []


@pytest.mark.fab_test
def test_detect_returns_single_instance_with_port_and_file_path(tmp_path, monkeypatch):
    """A single running instance resolves both its port and open file path."""
    from fabric_ci_cd_dataops.scripts import _desktop

    monkeypatch.setattr(_desktop.platform, "system", lambda: "Windows")
    _write_port_file(tmp_path, "AnalysisServicesWorkspace_1", 51234)

    class _FakeProc:
        stdout = 'powershell.exe "C:\\Reports\\Foo.pbix"\n'

    monkeypatch.setattr(
        _desktop.subprocess, "run", lambda *a, **k: _FakeProc()
    )

    instances = detect_desktop_instances(tmp_path)

    assert instances == [DesktopInstance(port=51234, open_file_path=Path("C:\\Reports\\Foo.pbix"))]


@pytest.mark.fab_test
def test_detect_leaves_file_path_unresolved_when_multiple_instances(tmp_path, monkeypatch):
    """Multiple simultaneous instances report every port but no guessed file path."""
    from fabric_ci_cd_dataops.scripts import _desktop

    monkeypatch.setattr(_desktop.platform, "system", lambda: "Windows")
    _write_port_file(tmp_path, "AnalysisServicesWorkspace_1", 111)
    _write_port_file(tmp_path, "AnalysisServicesWorkspace_2", 222)

    instances = detect_desktop_instances(tmp_path)

    assert {i.port for i in instances} == {111, 222}
    assert all(i.open_file_path is None for i in instances)


@pytest.mark.fab_test
def test_detect_returns_none_file_path_when_powershell_unavailable(tmp_path, monkeypatch):
    """A single instance whose command line can't be read still reports its port."""
    from fabric_ci_cd_dataops.scripts import _desktop

    monkeypatch.setattr(_desktop.platform, "system", lambda: "Windows")
    _write_port_file(tmp_path, "AnalysisServicesWorkspace_1", 999)

    def _raise(*_a, **_k):
        raise FileNotFoundError("powershell not found")

    monkeypatch.setattr(_desktop.subprocess, "run", _raise)

    instances = detect_desktop_instances(tmp_path)

    assert instances == [DesktopInstance(port=999, open_file_path=None)]


@pytest.mark.fab_test
def test_detect_ignores_unreadable_port_file(tmp_path, monkeypatch):
    """A malformed port file is skipped rather than raising."""
    from fabric_ci_cd_dataops.scripts import _desktop

    monkeypatch.setattr(_desktop.platform, "system", lambda: "Windows")
    data_dir = tmp_path / "AnalysisServicesWorkspace_1" / "Data"
    data_dir.mkdir(parents=True)
    (data_dir / "msmdsrv.port.txt").write_text("not-a-port-number", encoding="utf-16")

    assert detect_desktop_instances(tmp_path) == []


@pytest.mark.fab_test
def test_extract_file_arg_handles_quoted_pbix_path():
    """A quoted .pbix path in the command line is extracted."""
    assert _extract_file_arg('"C:\\Program Files\\...\\PBIDesktop.exe" "C:\\Reports\\Foo.pbix"') == (
        Path("C:\\Reports\\Foo.pbix")
    )


@pytest.mark.fab_test
def test_extract_file_arg_handles_unquoted_pbip_path():
    """An unquoted .pbip path in the command line is extracted."""
    assert _extract_file_arg("PBIDesktop.exe C:\\Reports\\Foo.pbip") == Path("C:\\Reports\\Foo.pbip")


@pytest.mark.fab_test
def test_extract_file_arg_returns_none_when_no_file_argument():
    """A command line with no recognizable file argument returns None."""
    assert _extract_file_arg("PBIDesktop.exe") is None


# --------------------------------------------------------------------------- #
# Matching a running instance to an artifact (Local Desktop First Run §4)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_match_selects_the_single_matching_instance(tmp_path):
    """The one instance whose open file matches the target is selected."""
    target = tmp_path / "SampleModel.pbip"
    instances = [DesktopInstance(port=111, open_file_path=target)]

    matched = match_instance_to_artifact(instances, target)

    assert matched.port == 111


@pytest.mark.fab_test
def test_match_raises_naming_the_file_when_no_instance_matches(tmp_path):
    """No matching instance raises, naming the file the user needs to open."""
    target = tmp_path / "SampleModel.pbip"
    instances = [DesktopInstance(port=111, open_file_path=tmp_path / "Other.pbip")]

    with pytest.raises(DesktopMatchError, match=re.escape(str(target))):
        match_instance_to_artifact(instances, target)


@pytest.mark.fab_test
def test_match_raises_naming_the_file_when_no_instances_running(tmp_path):
    """An empty instance list raises the same "open the file" error."""
    target = tmp_path / "SampleModel.pbip"

    with pytest.raises(DesktopMatchError, match=re.escape(str(target))):
        match_instance_to_artifact([], target)


@pytest.mark.fab_test
def test_match_raises_reporting_every_candidate_when_multiple_match(tmp_path):
    """Multiple instances with the same open file raise, naming every candidate port."""
    target = tmp_path / "SampleModel.pbip"
    instances = [
        DesktopInstance(port=111, open_file_path=target),
        DesktopInstance(port=222, open_file_path=target),
    ]

    with pytest.raises(DesktopMatchError) as exc_info:
        match_instance_to_artifact(instances, target)
    assert "111" in str(exc_info.value)
    assert "222" in str(exc_info.value)


@pytest.mark.fab_test
def test_match_ignores_instances_with_unresolved_file_path(tmp_path):
    """An instance with no known open file is never treated as a match."""
    target = tmp_path / "SampleModel.pbip"
    instances = [
        DesktopInstance(port=111, open_file_path=None),
        DesktopInstance(port=222, open_file_path=target),
    ]

    matched = match_instance_to_artifact(instances, target)

    assert matched.port == 222
