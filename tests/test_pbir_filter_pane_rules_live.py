"""The filter-pane rules name exactly the right visuals, measured with PBIR Inspector.

`tests/test_pbir_visual_filter_rules.py` only checks the rule JSON contains
certain strings, which is how both rules shipped wrong in every report: they
flagged every visual (a boolean test against an expected `[]`), an override
expecting `true` passed every visual, and the "filter pane disabled"
exemption never applied (PBIR Inspector Filter Pane Rules epic). These run
the real tool on `ThinReport`, whose five visuals cover the permutations:

    2524...  one filter, locked but not hidden
    4230...  four filters, neither hidden nor locked
    7a1f...  no filters
    ae85...  one filter, hidden but not locked
    df89...  one filter, neither
"""

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.pbir]

ROOT = Path(__file__).resolve().parents[1]
THIN = ROOT / "fabric-artifacts" / "ThinReport.Report"
VISIBLE = "NO_VISUAL_LEVEL_FILTERS_VISIBLE_IN_FILTER_PANEL"
UNLOCKED = "NO_VISUAL_LEVEL_FILTERS_UNLOCKED_IN_FILTER_PANEL"
NOT_HIDDEN = {"2524761709751832a270", "42303637da18cab42c69", "df89a190bca70b12b743"}
NOT_LOCKED = {"42303637da18cab42c69", "ae854917b1805e46dc69", "df89a190bca70b12b743"}


@pytest.fixture(scope="module")
def inspector() -> None:
    from fab_test.scripts.fab_test_registry import resolve_tool

    try:
        resolve_tool("pbir", argparse.Namespace())
    except (RuntimeError, OSError) as exc:  # UnsupportedPlatformError is a RuntimeError
        pytest.skip(f"PBIR Inspector unavailable: {exc}")


def _copy_report(tmp_path: Path, name: str) -> Path:
    report = tmp_path / f"{name}.Report"
    shutil.copytree(THIN, report)
    return report


def _edit_json(path: Path, change) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _flagged(report: Path, tmp_path: Path) -> dict[str, set[str]]:
    """Run `fab-test pbir` and return, per filter-pane rule, the visuals it named.

    Reads either result shape: one result per visual (flagged when it fails)
    or one per report whose actual value lists the offending visual names.
    """
    out = tmp_path / f"out-{report.stem}"
    subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "pbir", str(report), "--output-dir", str(out)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "GITHUB_ACTIONS": "", "CI": ""},
        check=False,
    )
    [native] = list(out.glob("pbir/*/native.json/*.json"))
    flagged: dict[str, set[str]] = {VISIBLE: set(), UNLOCKED: set()}
    for result in json.loads(native.read_text(encoding="utf-8-sig"))["Results"]:
        rule = result["RuleId"]
        if rule not in flagged or result["Pass"]:
            continue
        parts = Path(result["ItemPath"].replace("\\", "/")).parts
        if "visuals" in parts:
            flagged[rule].add(parts[parts.index("visuals") + 1])
        else:
            flagged[rule].update(result["Actual"] or [])
    return flagged


def test_given_the_filter_pane_visible_should_name_exactly_the_offending_visuals(inspector, tmp_path):
    flagged = _flagged(_copy_report(tmp_path, "PaneOn"), tmp_path)
    assert flagged[VISIBLE] == NOT_HIDDEN
    assert flagged[UNLOCKED] == NOT_LOCKED


def test_given_the_filter_pane_disabled_should_name_no_visual(inspector, tmp_path):
    report = _copy_report(tmp_path, "PaneOff")
    _edit_json(
        report / "definition" / "report.json",
        lambda data: data.setdefault("objects", {}).update(
            {"outspacePane": [{"properties": {"visible": {"expr": {"Literal": {"Value": "false"}}}}}]}
        ),
    )
    assert _flagged(report, tmp_path) == {VISIBLE: set(), UNLOCKED: set()}


def test_given_visible_unlocked_page_and_report_filters_should_flag_only_visual_filters(inspector, tmp_path):
    report = _copy_report(tmp_path, "ConsumerFilters")
    [visual] = report.glob("definition/pages/*/visuals/df89a190bca70b12b743/visual.json")
    consumer_filter = copy.deepcopy(json.loads(visual.read_text(encoding="utf-8"))["filterConfig"]["filters"][0])
    consumer_filter.update(isHiddenInViewMode=False, isLockedInViewMode=False)
    add = lambda data: data.setdefault("filterConfig", {}).setdefault("filters", []).append(consumer_filter)  # noqa: E731
    [page] = report.glob("definition/pages/*/page.json")
    _edit_json(page, add)
    _edit_json(report / "definition" / "report.json", add)
    flagged = _flagged(report, tmp_path)
    assert flagged[VISIBLE] == NOT_HIDDEN
    assert flagged[UNLOCKED] == NOT_LOCKED
