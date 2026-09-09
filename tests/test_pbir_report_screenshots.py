"""Contract test for the PBIR Inspector screenshot fix (PBIR Report Completeness epic).

FabInspCLI's ``TestRun.html`` builds each per-object screenshot's ``src`` at
render time from ``PBIInspectorPNG\\<Id>.png`` -- a Windows-style relative
path that 404s once the report is viewed from anywhere that didn't keep
that exact sibling folder. The fix injects a lookup table of the
screenshots already sitting in that folder, inlined as base64 data URIs,
and points the template's own ``src`` function at it first -- the same
technique the favicon fix (`test_pbir_report_favicon.py`) already uses.

Always passes on any machine: no PBIR Inspector binary is invoked.
"""

import base64
import json
from pathlib import Path

import pytest

from fab_test.scripts._pbir_report_fixups import fix_screenshot_images

_TEMPLATE_SNIPPET = (
    '{ "<>": "img", "src": function () { if (this.ParentName != null) { '
    'return "PBIInspectorPNG\\\\" + this.Id + ".png" } else { return '
    '"data:image/png;base64,iVBORw0KGgo=" } } }'
)


def _write_report(tmp_path: Path, body: str = _TEMPLATE_SNIPPET) -> Path:
    report = tmp_path / "TestRun.html"
    report.write_text(f"<html><head></head><body>{body}</body></html>", encoding="utf-8")
    return report


def _write_screenshot(tmp_path: Path, object_id: str, content: bytes = b"fake-png-bytes") -> Path:
    folder = tmp_path / "PBIInspectorPNG"
    folder.mkdir(exist_ok=True)
    png = folder / f"{object_id}.png"
    png.write_bytes(content)
    return png


@pytest.mark.pbir
def test_the_broken_relative_path_template_is_replaced_with_a_lookup(tmp_path):
    report = _write_report(tmp_path)
    _write_screenshot(tmp_path, "033389f2-f4fe-4f3e-b162-81112ebb664f")

    fix_screenshot_images(report)

    html = report.read_text(encoding="utf-8")
    assert 'return "PBIInspectorPNG\\\\" + this.Id + ".png"' not in html
    assert "window.__pbirScreenshots" in html


@pytest.mark.pbir
def test_the_injected_lookup_decodes_back_to_the_original_screenshot_bytes(tmp_path):
    report = _write_report(tmp_path)
    object_id = "033389f2-f4fe-4f3e-b162-81112ebb664f"
    _write_screenshot(tmp_path, object_id, b"real-screenshot-bytes")

    fix_screenshot_images(report)

    html = report.read_text(encoding="utf-8")
    start = html.index("window.__pbirScreenshots = ") + len("window.__pbirScreenshots = ")
    end = html.index(";</script>", start)
    images = json.loads(html[start:end])
    assert base64.b64decode(images[object_id].removeprefix("data:image/png;base64,")) == (
        b"real-screenshot-bytes"
    )


@pytest.mark.pbir
def test_an_id_with_no_screenshot_file_still_falls_back_to_the_relative_path(tmp_path):
    """Given the folder exists but is missing one object's file, that one degrades, not the report."""
    report = _write_report(tmp_path)
    _write_screenshot(tmp_path, "has-a-file")

    fix_screenshot_images(report)

    html = report.read_text(encoding="utf-8")
    assert '"PBIInspectorPNG\\\\" + this.Id + ".png"' in html


@pytest.mark.pbir
def test_missing_screenshot_folder_leaves_the_report_unchanged(tmp_path):
    report = _write_report(tmp_path)
    original = report.read_text(encoding="utf-8")

    fix_screenshot_images(report)

    assert report.read_text(encoding="utf-8") == original


@pytest.mark.pbir
def test_missing_report_file_does_not_raise(tmp_path):
    _write_screenshot(tmp_path, "some-id")

    fix_screenshot_images(tmp_path / "does-not-exist.html")


@pytest.mark.pbir
def test_report_without_the_expected_template_marker_is_left_untouched(tmp_path):
    """A future FabInspCLI template change should degrade gracefully, not crash the run."""
    report = _write_report(tmp_path, body="<p>no images here</p>")
    _write_screenshot(tmp_path, "some-id")
    original = report.read_text(encoding="utf-8")

    fix_screenshot_images(report)

    assert report.read_text(encoding="utf-8") == original


@pytest.mark.pbir
def test_running_the_fix_twice_does_not_double_encode(tmp_path):
    report = _write_report(tmp_path)
    _write_screenshot(tmp_path, "033389f2-f4fe-4f3e-b162-81112ebb664f")

    fix_screenshot_images(report)
    once = report.read_text(encoding="utf-8")
    fix_screenshot_images(report)
    twice = report.read_text(encoding="utf-8")

    assert once == twice
