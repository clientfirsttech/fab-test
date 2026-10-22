"""ACC-06: text contrast, the WCAG 2 ratio between a text run's color and the
background it is drawn on (the nearest container with an opaque
BackgroundColor, else the page's white).

Registered in ``_rdl_lint.CHECKS``. Colors set by an expression, and named
colors outside the table below, can't be judged statically and are skipped.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from ._rdl_common import Finding, _location, _parents

# The .NET named colors Report Builder's palette offers most often.
_NAMED_COLORS = {
    "black": "000000", "white": "FFFFFF", "gray": "808080", "grey": "808080", "dimgray": "696969",
    "dimgrey": "696969", "darkgray": "A9A9A9", "darkgrey": "A9A9A9", "silver": "C0C0C0",
    "lightgray": "D3D3D3", "lightgrey": "D3D3D3", "gainsboro": "DCDCDC", "whitesmoke": "F5F5F5",
    "red": "FF0000", "darkred": "8B0000", "maroon": "800000", "green": "008000", "darkgreen": "006400",
    "blue": "0000FF", "darkblue": "00008B", "navy": "000080", "steelblue": "4682B4",
    "cornflowerblue": "6495ED", "lightblue": "ADD8E6", "lightsteelblue": "B0C4DE", "yellow": "FFFF00",
    "lightyellow": "FFFFE0", "orange": "FFA500", "darkorange": "FF8C00", "purple": "800080",
    "khaki": "F0E68C", "beige": "F5F5DC", "tan": "D2B48C", "teal": "008080",
}
_HEX = re.compile(r"^#(?:[0-9A-Fa-f]{2})?([0-9A-Fa-f]{6})$")
_FONT_SIZE = re.compile(r"(?i)^\s*([\d.]+)\s*pt\s*$")

_DEFAULT_MIN_CONTRAST = 4.5
_DEFAULT_MIN_CONTRAST_LARGE = 3.0  # WCAG large text: 18pt, or 14pt bold


def _rgb(value: str | None) -> str | None:
    """Six hex digits for a literal color, or None for an expression, Transparent, or an unknown name."""
    value = (value or "").strip()
    if not value or value.startswith("="):
        return None
    match = _HEX.match(value)
    return match.group(1).upper() if match else _NAMED_COLORS.get(value.lower())


def _luminance(rgb: str) -> float:
    channels = []
    for i in (0, 2, 4):
        c = int(rgb[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _background(parents: dict[ET.Element, ET.Element], textbox: ET.Element) -> str | None:
    """The nearest opaque background; None when the nearest one is an expression or unknown."""
    node: ET.Element | None = textbox
    while node is not None:
        value = (node.findtext("Style/BackgroundColor") or "").strip()
        if value and value.lower() != "transparent":
            return _rgb(value)
        node = parents.get(node)
    return "FFFFFF"


def _is_large(run: ET.Element) -> bool:
    size = _FONT_SIZE.match(run.findtext("Style/FontSize") or "")
    points = float(size.group(1)) if size else 10.0
    bold = (run.findtext("Style/FontWeight") or "").strip().lower() in ("bold", "bolder", "extrabold", "heavy")
    return points >= 18 or (bold and points >= 14)


def _check_acc06_text_contrast(root: ET.Element, _namespace: str, rule: dict[str, Any]) -> list[Finding]:
    minimum = rule.get("min_contrast", _DEFAULT_MIN_CONTRAST)
    minimum_large = rule.get("min_contrast_large", _DEFAULT_MIN_CONTRAST_LARGE)
    parents = _parents(root)
    findings: list[Finding] = []
    for textbox in root.iter("Textbox"):
        background = _background(parents, textbox)
        if background is None:
            continue
        box_color = textbox.findtext("Style/Color") or "Black"
        for run in textbox.iter("TextRun"):
            foreground = _rgb(run.findtext("Style/Color") or box_color)
            if foreground is None:
                continue
            ratio = _ratio(foreground, background)
            required = min(minimum, minimum_large) if _is_large(run) else minimum
            if ratio < required:
                findings.append({
                    "object": _location(parents, textbox),
                    "message": (
                        f"text #{foreground} on #{background} is {ratio:.1f}:1, below {required:g}:1 -- "
                        "darken the text or lighten the background"
                    ),
                })
                break
    return findings
