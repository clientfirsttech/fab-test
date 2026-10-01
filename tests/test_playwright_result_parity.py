"""The expected pass/fail of every dev-environment case, and its offline contract.

The reference implementation (``pbi-dataops-visual-error-testing``) was run
against the dev workspace and its outcomes are the expected answers:

- interactive reports: the ``expected_status`` column of each golden CSV
  under ``tests/fixtures/playwright-parity/`` (rebuilt from the reference's
  interactive JUnit run, whose file was later overwritten);
- paginated reports: ``tests/fixtures/playwright-test-results/paginated-results.xml``,
  the reference's JUnit output, joined to the ``Paginated*.json`` goldens by
  the ``test_case`` GUID each test name carries.

``expectations()`` is what the live comparison
(``test_playwright_result_parity_live.py``) checks fab-test against. The tests
here keep it honest with no network: every golden parses, every expectation
joins to exactly one generated-case golden, and the totals cannot quietly
shrink.
"""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.playwright

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "playwright-parity"
PAGINATED_RESULTS = (
    Path(__file__).parent / "fixtures" / "playwright-test-results" / "paginated-results.xml"
)

#: The size of the golden set. A golden that silently loses rows proves less
#: than it claims, so a change to either number has to be deliberate.
INTERACTIVE_CASES = 26
PAGINATED_CASES = 6

_GUID = re.compile(r"test ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) - ")


@dataclass(frozen=True)
class Expectation:
    """One case's expected outcome, keyed the way fab-test's test_results rows are."""

    report_name: str
    page_name: str
    bookmark_name: str
    role: str
    parameters: tuple[tuple[str, str], ...]
    expected_status: str

    @property
    def key(self) -> tuple:
        return (self.report_name, self.page_name, self.bookmark_name, self.role, self.parameters)


def parameters_key(parameters: list[dict[str, str]]) -> tuple[tuple[str, str], ...]:
    """A parameter set as an order-free, comparable key."""
    return tuple(sorted((entry["name"], str(entry["value"])) for entry in parameters))


def _junit_render_outcomes(path: Path) -> dict[str, str]:
    """Map each "for visual errors" test's GUID to ``pass``/``fail``.

    The reference's token-accessibility tests are out of scope and skipped.
    """
    outcomes: dict[str, str] = {}
    for testcase in ET.parse(path).getroot().iter("testcase"):
        name = testcase.get("name", "")
        if "for visual errors" not in name:
            continue
        match = _GUID.search(name)
        assert match, f"{path.name}: no test_case GUID in '{name[:80]}'"
        outcomes[match.group(1)] = "fail" if testcase.find("failure") is not None else "pass"
    return outcomes


def _interactive_expectations() -> list[Expectation]:
    expectations = []
    for csv_path in sorted(FIXTURE_DIR.glob("*.csv")):
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for line, row in enumerate(csv.DictReader(fh), start=2):
                status = row.get("expected_status", "")
                assert status in {"pass", "fail"}, (
                    f"{csv_path.name} line {line}: expected_status must be pass or fail, "
                    f"got '{status}'"
                )
                expectations.append(
                    Expectation(
                        report_name=row["report_name"],
                        page_name=row["page_name"],
                        bookmark_name=row.get("bookmark_name") or "",
                        role=row.get("role") or "",
                        parameters=(),
                        expected_status=status,
                    )
                )
    return expectations


def _paginated_expectations() -> list[Expectation]:
    outcomes = _junit_render_outcomes(PAGINATED_RESULTS)
    expectations = []
    seen: set[str] = set()
    for json_path in sorted(FIXTURE_DIR.glob("Paginated*.json")):
        with open(json_path, encoding="utf-8-sig") as fh:
            for case in json.load(fh):
                guid = case["test_case"]
                assert guid in outcomes, (
                    f"{json_path.name}: case {guid} has no outcome in {PAGINATED_RESULTS.name}"
                )
                seen.add(guid)
                expectations.append(
                    Expectation(
                        report_name=case["report_name"],
                        page_name="",
                        bookmark_name="",
                        role=case.get("role") or "",
                        parameters=parameters_key(case.get("report_parameters") or []),
                        expected_status=outcomes[guid],
                    )
                )
    orphans = set(outcomes) - seen
    assert not orphans, (
        f"{PAGINATED_RESULTS.name} has outcomes for cases no Paginated*.json golden "
        f"lists: {sorted(orphans)}"
    )
    return expectations


def expectations() -> list[Expectation]:
    """Every dev-environment case's expected outcome, interactive then paginated."""
    return _interactive_expectations() + _paginated_expectations()


def test_every_interactive_golden_row_states_its_expected_outcome() -> None:
    """Given the interactive goldens, should hold one pass/fail per generated case."""
    assert len(_interactive_expectations()) == INTERACTIVE_CASES


def test_every_paginated_outcome_joins_to_exactly_one_golden_case() -> None:
    """Given the reference's paginated JUnit run, should join every render
    outcome to one Paginated*.json case, and every case to one outcome."""
    assert len(_paginated_expectations()) == PAGINATED_CASES


def test_no_two_expectations_share_a_key() -> None:
    """Two cases the live comparison could not tell apart would let one mask
    the other's result."""
    keys = [expectation.key for expectation in expectations()]
    assert len(keys) == len(set(keys))


def test_the_goldens_expect_the_failures_the_dev_environment_was_built_to_show() -> None:
    """The dev reports were built to break in specific places; a golden that
    expects no failures could not catch a renderer that never fails."""
    failing = {e.key for e in expectations() if e.expected_status == "fail"}
    assert failing == {
        ("Not Working Visuals", "Page 1", "", "", ()),
        ("Report with Bookmarks - Broken Visuals", "Page A", "Bookmark 3", "", ()),
        ("RLSTest-WithBookmarks", "Page 2", "Show Broken", "Team A", ()),
        ("RLSTest-WithBookmarks", "Page 2", "Show Broken", "Team B", ()),
        ("PaginatedExample-BrokenRDL", "", "", "", ()),
        (
            "PaginatedExample-WithMultiFilter",
            "",
            "",
            "",
            (("ReportParameter1", "2"), ("ReportParameter1", "4")),
        ),
    }
