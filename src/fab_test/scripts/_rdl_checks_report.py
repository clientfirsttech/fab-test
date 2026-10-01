"""RDL checks for parameters, layout, subreports and accessibility (PRM, LAY, SUB, ACC).

One function per rule ID, registered in ``_rdl_lint.CHECKS``. See
plan/rdl-rule-set.md for what each rule ID checks.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from ._rdl_common import (
    Finding,
    _location,
    _parents,
    _size_in_inches,
    _snippet,
)


# --------------------------------------------------------------------------- #
# Parameter rules (PRM-01, PRM-03, PRM-04, PRM-05)
# --------------------------------------------------------------------------- #


def _check_prm01_default_value(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    return [
        {
            "object": parameter.get("Name") or "?",
            "message": "no DefaultValue -- the report won't run on open without a manual selection",
        }
        for parameter in root.findall(".//ReportParameters/ReportParameter")
        if parameter.find("DefaultValue") is None
    ]


_DEFAULT_PRM03_MAX_PARAMETERS = 5


# Matches a parameter named after a single date part -- "Year"/"Month"/"Day"
# as a whole word, so "Yearly" or "PayDay" don't count.
_DATE_PART_NAME = re.compile(r"(?i)\b(year|month|day)\b")


def _check_prm03_parameter_count(root: ET.Element, _namespace: str, rule: dict[str, Any]) -> list[Finding]:
    max_parameters = rule.get("max_parameters", _DEFAULT_PRM03_MAX_PARAMETERS)
    parameters = root.findall(".//ReportParameters/ReportParameter")
    names = [parameter.get("Name") or "" for parameter in parameters]
    findings: list[Finding] = []

    # Fires regardless of the total count -- three narrow date-part
    # parameters are the anti-pattern this rule names explicitly, not a
    # symptom of the report simply having "too many" parameters.
    date_part_names = [name for name in names if _DATE_PART_NAME.search(name)]
    date_parts_seen = {match.lower() for name in date_part_names for match in _DATE_PART_NAME.findall(name)}
    if len(date_parts_seen) >= 2:
        findings.append({
            "object": ", ".join(date_part_names),
            "message": "separate Year/Month/Day parameters should usually be one DateTime picker",
        })

    if len(parameters) > max_parameters:
        findings.append({
            "object": f"{len(parameters)} parameters",
            "message": (
                f"{len(parameters)} parameters is over the {max_parameters}-parameter "
                "threshold -- keep the parameter count low"
            ),
        })
    return findings


def _check_prm04_multivalue_nullable(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for parameter in root.findall(".//ReportParameters/ReportParameter"):
        multi_value = (parameter.findtext("MultiValue") or "").strip().lower() == "true"
        nullable = (parameter.findtext("Nullable") or "").strip().lower() == "true"
        if multi_value and nullable:
            findings.append({
                "object": parameter.get("Name") or "?",
                "message": "MultiValue=true with Nullable=true isn't supported -- MultiValue + AllowBlank is fine",
            })
    return findings


_PARAMETER_REFERENCE = re.compile(r"Parameters!(\w+)\.(?:Value|Label)")


def _check_prm05_show_parameter_values(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parameters = root.findall(".//ReportParameters/ReportParameter")
    if not parameters:
        return []
    displayed: set[str] = set()
    for element in root.iter():
        text = (element.text or "").strip()
        if not text.startswith("="):
            continue
        displayed.update(_PARAMETER_REFERENCE.findall(text))
    return [
        {
            "object": name,
            "message": (
                f"parameter '{name}' isn't shown anywhere on the report "
                f"(Parameters!{name}.Value or .Label) -- exported copies won't be self-explanatory"
            ),
        }
        for name in (parameter.get("Name") or "" for parameter in parameters)
        if name and name not in displayed
    ]


# --------------------------------------------------------------------------- #
# Layout and subreport rules (LAY-01 .. LAY-06, SUB-01, SUB-02)
# --------------------------------------------------------------------------- #

# RDL's own schema default when Page/PageWidth is omitted (Letter width).
_DEFAULT_PAGE_WIDTH_INCHES = 8.5


def _check_lay01_body_fits_page(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    report_section = root.find(".//ReportSection")
    if report_section is None:
        return []
    body_width = _size_in_inches(report_section.findtext("Width"))
    if body_width is None:
        return []
    page = report_section.find("Page")
    left_margin = _size_in_inches(page.findtext("LeftMargin")) if page is not None else None
    right_margin = _size_in_inches(page.findtext("RightMargin")) if page is not None else None
    page_width = _size_in_inches(page.findtext("PageWidth")) if page is not None else None
    total = body_width + (left_margin or 0.0) + (right_margin or 0.0)
    effective_page_width = page_width if page_width is not None else _DEFAULT_PAGE_WIDTH_INCHES
    if total > effective_page_width:
        return [{
            "object": "ReportSection",
            "message": (
                f"body width + margins ({total:.2f}in) exceeds the page width "
                f"({effective_page_width:.2f}in) -- PDF/print will add blank overflow pages"
            ),
        }]
    return []


def _check_lay02_avoid_total_pages(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for element in root.iter():
        text = (element.text or "").strip()
        if text.startswith("=") and "Globals!TotalPages" in text:
            findings.append({
                "object": _location(parents, element),
                "message": f"{_snippet(text)}: Globals!TotalPages slows PDF and image rendering",
            })
    return findings


def _check_lay03_sub01_subreport_in_tablix(
    root: ET.Element, _namespace: str, _rule: dict[str, Any]
) -> list[Finding]:
    """Registered only under LAY-03's catalog entry -- SUB-01 detects the
    exact same thing, so this produces one finding per offending
    Subreport, tagged with both IDs, rather than being dispatched twice.
    """
    parents = _parents(root)
    return [
        {
            "rule": "LAY-03/SUB-01",
            "object": _location(parents, subreport),
            "message": (
                "Subreport nested inside a Tablix runs once per row -- use a "
                "nested data region, or a drillthrough link when rows are many"
            ),
        }
        for tablix in root.iter("Tablix")
        for subreport in tablix.iter("Subreport")
    ]


def _check_lay04_interactive_sort(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    return [
        {
            "object": _location(parents, textbox),
            "message": "UserSort on a textbox enables interactive sort -- use only when actually wanted",
        }
        for textbox in root.iter("Textbox")
        if textbox.find("UserSort") is not None
    ]


def _check_lay05_large_reports_page_breaks(
    root: ET.Element, _namespace: str, _rule: dict[str, Any]
) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for tablix in root.iter("Tablix"):
        groups = list(tablix.iter("Group"))
        if not groups:
            continue
        has_page_break = any(group.find("PageBreak/BreakLocation") is not None for group in groups)
        if not has_page_break:
            findings.append({
                "object": _location(parents, tablix),
                "message": (
                    "no Group/PageBreak/BreakLocation configured -- nothing shows "
                    "until the whole report renders on a large dataset"
                ),
            })
    return findings


def _check_lay06_avoid_embedded_images(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    embedded_message = (
        "EmbeddedImages/EmbeddedImage bloats the file and is hard to update -- prefer External or Database"
    )
    inline_message = "Image/Source=Embedded bloats the file and is hard to update -- prefer External or Database"
    findings: list[Finding] = [
        {"object": embedded.get("Name") or "?", "message": embedded_message}
        for embedded in root.findall(".//EmbeddedImages/EmbeddedImage")
    ]
    parents = _parents(root)
    findings.extend(
        {"object": _location(parents, image), "message": inline_message}
        for image in root.iter("Image")
        if (image.findtext("Source") or "").strip().lower() == "embedded"
    )
    return findings


_DEFAULT_SUB02_MAX_SUBREPORTS = 49  # "50 or more" fails; 49 is the highest passing count


def _check_sub02_subreport_count(root: ET.Element, _namespace: str, rule: dict[str, Any]) -> list[Finding]:
    max_subreports = rule.get("max_subreports", _DEFAULT_SUB02_MAX_SUBREPORTS)
    count = len(root.findall(".//Subreport"))
    if count > max_subreports:
        return [{
            "object": f"{count} subreports",
            "message": f"{count} Subreport elements -- 50 or more fail to render in the service",
        }]
    return []


# --------------------------------------------------------------------------- #
# Accessibility rules (ACC-01, ACC-02, ACC-03, ACC-08)
# --------------------------------------------------------------------------- #

# Tablix is excluded here even though it's a report item like the rest --
# ACC-03 already covers a missing Tablix/ToolTip specifically, and a
# Tablix with none should be one finding (ACC-03), not two.
_ALT_TEXT_ELEMENTS = ("Image", "Chart", "GaugePanel", "Map")


def _check_acc01_alt_text(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    return [
        {
            "object": _location(parents, element),
            "message": f"{tag} has no ToolTip -- screen readers get nothing in the service or Accessible PDF",
        }
        for tag in _ALT_TEXT_ELEMENTS
        for element in root.iter(tag)
        if not (element.findtext("ToolTip") or "").strip()
    ]


_PLACEHOLDER_CHART_NAME = re.compile(r"(?i)^chart\d*$")


def _check_acc02_chart_alt_text_quality(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for chart in root.iter("Chart"):
        tooltip = (chart.findtext("ToolTip") or "").strip()
        if not tooltip:
            continue  # missing entirely is ACC-01's concern, not ACC-02's
        if tooltip.startswith("="):
            continue  # an expression's wording can't be judged statically
        name = chart.get("Name") or ""
        if tooltip == name or _PLACEHOLDER_CHART_NAME.match(tooltip):
            findings.append({
                "object": _location(parents, chart),
                "message": f"ToolTip '{tooltip}' looks like a placeholder, not a description of what the chart shows",
            })
    return findings


def _check_acc03_table_caption(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    return [
        {
            "object": _location(parents, tablix),
            "message": "Tablix has no ToolTip -- add a caption summarising what the table conveys",
        }
        for tablix in root.iter("Tablix")
        if not (tablix.findtext("ToolTip") or "").strip()
    ]


def _check_acc08_html_link_alt_text(root: ET.Element, _namespace: str, _rule: dict[str, Any]) -> list[Finding]:
    parents = _parents(root)
    findings: list[Finding] = []
    for textbox in root.iter("Textbox"):
        has_html_run = any(
            (run.findtext("MarkupType") or "").strip().lower() == "html" for run in textbox.iter("TextRun")
        )
        if not has_html_run:
            continue
        if not (textbox.findtext("ToolTip") or "").strip():
            findings.append({
                "object": _location(parents, textbox),
                "message": "renders an HTML TextRun (a hyperlink) but has no ToolTip",
            })
    return findings
