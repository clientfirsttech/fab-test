"""Post-processing patches for PBIR Inspector's native ``TestRun.html``.

FabInspCLI ships its own HTML report template baked into the CLI release
(``FabInspector.ClientLibrary/Files/html/TestRunTemplate.html`` in
``NatVanG/fab-inspector``), so a bug in it cannot be fixed by anything in
this repo's rules file or Python wrapper -- only by patching the emitted
file after the CLI writes it. Each fix here targets one known-broken
literal marker in that template and is a no-op the moment the marker is
gone (already patched, upstream fixed it, or the template changed), so
these never fail a `pbir-test` run over a cosmetic or vendor-side defect.
"""

from __future__ import annotations

import base64
import contextlib
import json
from pathlib import Path

_BROKEN_FAVICON_LINK = '<link rel="icon" href="../icon/pbiinspector.png">'


def fix_favicon_link(report_path: Path, inspector_path: Path) -> None:
    """Inline TestRun.html's favicon so it survives leaving its install dir.

    FabInspCLI's template points the favicon at ``../icon/pbiinspector.png``,
    relative to where the template lives inside the FabInspCLI install --
    not the output directory where the generated report actually lands
    (``fab-test-results/pbir/...``), so the link 404s once opened from
    there. The icon file still exists next to the inspector binary, so it
    is read once and inlined as a data URI, the same technique the
    template already uses for its logo and page-wireframe images.

    Never raises: a missing report, a missing icon, or a template that no
    longer contains the expected marker all leave the report untouched
    rather than fail the pbir-test run over a cosmetic asset.
    """
    icon_path = inspector_path.parent / "Files" / "icon" / "pbiinspector.png"
    if not report_path.is_file() or not icon_path.is_file():
        return
    try:
        html = report_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    if _BROKEN_FAVICON_LINK not in html:
        return
    data_uri = "data:image/png;base64," + base64.b64encode(icon_path.read_bytes()).decode("ascii")
    html = html.replace(_BROKEN_FAVICON_LINK, f'<link rel="icon" href="{data_uri}">')
    with contextlib.suppress(OSError):
        report_path.write_text(html, encoding="utf-8")


_BROKEN_IMAGE_SRC_MARKER = 'return "PBIInspectorPNG\\\\" + this.Id + ".png"'
_INLINE_IMAGE_LOOKUP = "window.__pbirScreenshots"


def _inline_png_map(folder: Path) -> dict[str, str]:
    """Return ``{file stem: data URI}`` for every PNG in ``folder``.

    A file that cannot be read is skipped rather than failing the whole
    map -- one corrupt screenshot should not cost every other one its fix.
    """
    images: dict[str, str] = {}
    for png in sorted(folder.glob("*.png")):
        try:
            images[png.stem] = "data:image/png;base64," + base64.b64encode(
                png.read_bytes()
            ).decode("ascii")
        except OSError:
            continue
    return images


def fix_screenshot_images(report_path: Path) -> None:
    """Inline TestRun.html's per-object screenshots as base64 data URIs.

    FabInspCLI's own template builds each screenshot's ``src`` as
    ``PBIInspectorPNG\\<Id>.png`` -- a Windows-style relative path that
    404s the moment the report is opened from somewhere that didn't keep
    that exact sibling folder alongside it. The screenshots already ship
    next to the report (``PBIInspectorPNG/``), so they are read once and
    inlined the same way the favicon and the wireframe placeholder
    already are, via a lookup table the template's own ``src`` function
    checks first.

    Never raises: a missing ``PBIInspectorPNG`` folder, a report that no
    longer contains the expected template marker, or a file that cannot
    be read all leave the report untouched -- the same contract
    ``fix_favicon_link`` has. Also a no-op if the fix already ran once:
    the lookup table it injects is itself the marker that it has.
    """
    folder = report_path.parent / "PBIInspectorPNG"
    if not report_path.is_file() or not folder.is_dir():
        return
    try:
        html = report_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    if _BROKEN_IMAGE_SRC_MARKER not in html or _INLINE_IMAGE_LOOKUP in html:
        return
    images = _inline_png_map(folder)
    if not images:
        return
    # </ is escaped so a filename cannot prematurely close the <script> tag.
    payload = json.dumps(images).replace("</", "<\\/")
    lookup_script = f"<script>{_INLINE_IMAGE_LOOKUP} = {payload};</script>"
    fixed_src = (
        f"return ({_INLINE_IMAGE_LOOKUP} && {_INLINE_IMAGE_LOOKUP}[this.Id]) "
        '|| ("PBIInspectorPNG\\\\" + this.Id + ".png")'
    )
    html = html.replace(_BROKEN_IMAGE_SRC_MARKER, fixed_src)
    html = html.replace("</head>", f"{lookup_script}</head>", 1) if "</head>" in html else lookup_script + html
    with contextlib.suppress(OSError):
        report_path.write_text(html, encoding="utf-8")


_BROKEN_LOG_TYPE_CHECK = 'item.LogType === 2 || normalizedLogType === "2"'
_FIXED_LOG_TYPE_CHECK = 'item.LogType === 0 || normalizedLogType === "0"'


def fix_log_type_filter(report_path: Path) -> None:
    """Correct TestRun.html's "Error" Log Type filter, which never matches.

    FabInspCLI's own ``MessageTypeEnum`` is ``Error = 0, Warning = 1,
    Information = 2, ...`` (verified against the ``NatVanG/fab-inspector``
    source), and a rule result's ``LogType`` is only ever ``Error`` or
    ``Warning`` -- ``ConvertRuleLogType`` never returns anything else. But
    the template's own ``matchLogType()`` checks ``item.LogType === 2`` for
    "isError", a value a `TestResult` never carries, so selecting "Error"
    in the filter dropdown always returns zero rows while "Warning"
    (``=== 1``, already correct) works. See the PBIR TestRun.html Log Type
    Filter epic.

    Never raises: a missing report or one that no longer contains the
    expected marker (already patched, or a template version that changed)
    is left untouched -- the same contract ``fix_favicon_link`` and
    ``fix_screenshot_images`` have.
    """
    if not report_path.is_file():
        return
    try:
        html = report_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    if _BROKEN_LOG_TYPE_CHECK not in html:
        return
    html = html.replace(_BROKEN_LOG_TYPE_CHECK, _FIXED_LOG_TYPE_CHECK)
    with contextlib.suppress(OSError):
        report_path.write_text(html, encoding="utf-8")
