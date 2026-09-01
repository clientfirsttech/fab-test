"""Contract test for the PBIR Inspector favicon fix (HTML Report Format §1).

FabInspCLI's ``TestRun.html`` ships a favicon link
(``<link rel="icon" href="../icon/pbiinspector.png">``) that is relative to
the *template's* install location, not the output directory the report
lands in under ``fab-test-results/``, so it 404s when the report is
actually opened. The fix inlines the icon as a base64 data URI using the
icon file that already ships next to the inspector binary -- no new asset
directory to copy, and no change to the vendored template itself.

Always passes on any machine: no PBIR Inspector binary is invoked.
"""

from pathlib import Path

import pytest

from fab_test.scripts.invoke_pbir_inspector import fix_favicon_link

_BROKEN_LINK = '<link rel="icon" href="../icon/pbiinspector.png">'


def _write_report(tmp_path: Path, body: str = _BROKEN_LINK) -> Path:
    report = tmp_path / "TestRun.html"
    report.write_text(f"<html><head>{body}</head><body></body></html>", encoding="utf-8")
    return report


def _write_icon(tmp_path: Path) -> Path:
    inspector_dir = tmp_path / "FabInspCLI"
    icon_dir = inspector_dir / "Files" / "icon"
    icon_dir.mkdir(parents=True)
    icon_path = icon_dir / "pbiinspector.png"
    icon_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-icon-bytes")
    return inspector_dir / "fab-inspector"


@pytest.mark.pbir
def test_broken_relative_favicon_link_is_replaced_with_a_data_uri(tmp_path):
    report = _write_report(tmp_path)
    inspector_path = _write_icon(tmp_path)

    fix_favicon_link(report, inspector_path)

    html = report.read_text(encoding="utf-8")
    assert "../icon/pbiinspector.png" not in html
    assert '<link rel="icon" href="data:image/png;base64,' in html


@pytest.mark.pbir
def test_data_uri_decodes_back_to_the_original_icon_bytes(tmp_path):
    import base64
    import re

    report = _write_report(tmp_path)
    inspector_path = _write_icon(tmp_path)
    icon_bytes = (inspector_path.parent / "Files" / "icon" / "pbiinspector.png").read_bytes()

    fix_favicon_link(report, inspector_path)

    html = report.read_text(encoding="utf-8")
    match = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
    assert match, html
    assert base64.b64decode(match.group(1)) == icon_bytes


@pytest.mark.pbir
def test_missing_icon_file_leaves_the_report_unchanged(tmp_path):
    """Given a future FabInspCLI drops or relocates the icon, should not crash."""
    report = _write_report(tmp_path)
    inspector_path = tmp_path / "FabInspCLI" / "fab-inspector"

    fix_favicon_link(report, inspector_path)

    assert report.read_text(encoding="utf-8") == (
        f"<html><head>{_BROKEN_LINK}</head><body></body></html>"
    )


@pytest.mark.pbir
def test_missing_report_file_does_not_raise(tmp_path):
    inspector_path = _write_icon(tmp_path)

    fix_favicon_link(tmp_path / "does-not-exist.html", inspector_path)


@pytest.mark.pbir
def test_report_without_the_expected_favicon_marker_is_left_untouched(tmp_path):
    """A future template change should degrade gracefully, not crash the run."""
    report = _write_report(tmp_path, body="<title>x</title>")
    inspector_path = _write_icon(tmp_path)

    fix_favicon_link(report, inspector_path)

    assert report.read_text(encoding="utf-8") == "<html><head><title>x</title></head><body></body></html>"
