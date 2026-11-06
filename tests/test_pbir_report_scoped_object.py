"""A report-scoped, per-visual finding names its page(s), not "N/A".

Rules like the filter-pane pair (`part: Report`, mapping over
`{"part": "Visuals"}`) aren't attached to any one page, so PBIR Inspector
reports `ParentDisplayName: "N/A"` even though `Actual` lists the specific
offending visuals. A user reading the envelope has no way to tell which
page(s) those visuals are on without cross-referencing ids by hand --
confusing enough in practice to be worth fixing on its own (PBIR Visual
Filter Panel Double-Count epic, follow-up).

Always passes on any machine: no PBIR Inspector binary is invoked.
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from fab_test.scripts.invoke_pbir_inspector import run_inspector

pytestmark = pytest.mark.pbir


def _add_visual(artifact: Path, page_id: str, page_name: str, visual_id: str) -> None:
    page_dir = artifact / "definition" / "pages" / page_id
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "page.json").write_text(json.dumps({"displayName": page_name}), encoding="utf-8")
    visual_dir = page_dir / "visuals" / visual_id
    visual_dir.mkdir(parents=True, exist_ok=True)
    (visual_dir / "visual.json").write_text("{}", encoding="utf-8")


def _run(tmp_path: Path, results: list[dict], monkeypatch, build_pages=None):
    monkeypatch.chdir(tmp_path)
    artifact = tmp_path / "SalesReport.Report"
    artifact.mkdir()
    if build_pages:
        build_pages(artifact)
    rules = tmp_path / "rules.json"
    rules.write_text("[]", encoding="utf-8")
    inspector = tmp_path / "PBIRInspectorCLI"
    inspector.write_text("fake", encoding="utf-8")
    inspector.chmod(0o755)
    output = tmp_path / "fab-test-results" / "pbir" / "SalesReport" / "envelope.json"

    native_dir = tmp_path / "fab-test-results" / "pbir" / "SalesReport"
    native_dir.mkdir(parents=True, exist_ok=True)
    (native_dir / "native.json").write_text(json.dumps({"Results": results}), encoding="utf-8")

    class Args:
        artifact_path = str(artifact)
        rules_path = str(rules)
        inspector_path = str(inspector)
        output_path = str(output)
        emit_html = False

    with mock.patch("fab_test.scripts.invoke_pbir_inspector.subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        run_inspector(Args())
    return json.loads(output.read_text(encoding="utf-8"))


def _filter_pane_result(actual: list[str]) -> dict:
    return {
        "RuleId": "NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL",
        "LogType": 0,
        "Pass": False,
        "ParentDisplayName": "N/A",
        "Actual": actual,
        "Message": "...",
    }


def test_a_report_scoped_finding_names_the_single_page_its_visual_is_on(tmp_path, monkeypatch):
    def build(artifact):
        _add_visual(artifact, "pageA", "Page 2", "visA")

    data = _run(tmp_path, [_filter_pane_result(["visA"])], monkeypatch, build)

    assert data["findings"][0]["object"] == "Page 2"


def test_a_report_scoped_finding_names_every_distinct_page_once(tmp_path, monkeypatch):
    def build(artifact):
        _add_visual(artifact, "pageA", "Page 1", "visA")
        _add_visual(artifact, "pageB", "Page 2", "visB")

    data = _run(tmp_path, [_filter_pane_result(["visA", "visB"])], monkeypatch, build)

    assert data["findings"][0]["object"] == "Page 1, Page 2"


def test_two_visuals_on_the_same_page_name_it_only_once(tmp_path, monkeypatch):
    def build(artifact):
        _add_visual(artifact, "pageA", "Page 1", "visA")
        _add_visual(artifact, "pageA", "Page 1", "visB")

    data = _run(tmp_path, [_filter_pane_result(["visA", "visB"])], monkeypatch, build)

    assert data["findings"][0]["object"] == "Page 1"


def test_an_actual_value_that_matches_no_known_visual_stays_na(tmp_path, monkeypatch):
    """Not every `Actual` list is visual ids (e.g. custom-visual names) -- leave it alone."""
    def build(artifact):
        _add_visual(artifact, "pageA", "Page 1", "visA")

    data = _run(tmp_path, [_filter_pane_result(["someCustomVisualTypeName"])], monkeypatch, build)

    assert data["findings"][0]["object"] == "N/A"


def test_a_page_scoped_finding_keeps_its_own_parent_display_name(tmp_path, monkeypatch):
    """A rule PBIR Inspector already attaches to a page must not be overridden."""
    result = {**_filter_pane_result(["visA"]), "ParentDisplayName": "Page 1"}

    def build(artifact):
        _add_visual(artifact, "pageA", "Page 2", "visA")

    data = _run(tmp_path, [result], monkeypatch, build)

    assert data["findings"][0]["object"] == "Page 1"
