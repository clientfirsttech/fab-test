"""A ratchet on file-level size budgets (Test Module Split epic, task 4).

Scope
-----
[aidd-module-budgets](../.github/skills/aidd-module-budgets/SKILL.md) set
file-level budgets that nothing in this repo measured before this epic:
source modules soft 400 / hard 800, test modules soft 500 / hard 900.
`tests/test_fab_test.py` crossed the hard test budget at 4,383 lines before
anyone noticed, one epic section at a time -- the same shape
`test_complexity_budget.py` already solved for complexity findings: a
non-gating report in `build.yml` for the soft budget, and a hard failure
here for anything that would make the next file unreviewable the same way.

A file already over its hard budget when this ratchet was written is not
silently re-permitted by a raised number -- it is named here, with the date
and the reason it isn't being split in this commit, so grepping this file
tells you every file this repo has already agreed to carry debt on.
"""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

SOURCE_SOFT = 400
SOURCE_HARD = 800
TEST_SOFT = 500
TEST_HARD = 900

# path (relative to repo root) -> (line count when exempted, reason).
# The recorded count is the ceiling: growing past it needs a new entry (or a
# split), not a silent pass. Shrinking well below it is slack -- the
# exemption should be tightened or dropped, matching
# test_the_ceiling_is_not_left_slack_after_a_cleanup in
# test_complexity_budget.py.
EXEMPTIONS: dict[str, tuple[int, str]] = {
    "src/fabric_ci_cd_dataops/scripts/fab_test.py": (
        2875,
        (
            "2026-08-23: the CLI entry point outgrew the hard budget years before "
            "this ratchet existed. Its tests were split first (Test Module Split "
            "epic) because a source split is only reviewable once its tests "
            "aren't one 4,383-line file too -- see "
            "tasks/fab-test-module-split-epic.md for the follow-up epic filed "
            "to split it. 2026-08-24: +8 lines adding the `playwright` "
            "subcommand's --pages/--roles discovery flags (Playwright Test "
            "Matrix Discovery epic)."
        ),
    ),
    "src/fabric_ci_cd_dataops/scripts/fab_test_summary.py": (
        812,
        (
            "2026-08-23: 12 lines over hard, from unrelated feature work landing "
            "since this file was last at 793; not yet worth a forced split for "
            "12 lines. Revisit if it keeps growing."
        ),
    ),
    "src/fabric_ci_cd_dataops/scripts/fab_test_registry.py": (
        817,
        (
            "2026-08-23: 11 lines over hard, same story as fab_test_summary.py -- "
            "small drift from other epics, not yet worth a forced split. "
            "2026-08-24: +6 lines forwarding --pages/--roles to "
            "invoke_playwright (Playwright Test Matrix Discovery epic)."
        ),
    ),
}

# How much headroom an exemption may carry before it should be tightened.
_EXEMPTION_SLACK_MARGIN = 40


def _budgets_for(path: Path) -> tuple[int, int]:
    """Return (soft, hard) for a file, based on which tree it lives under."""
    relative = path.relative_to(_ROOT).as_posix()
    if relative.startswith("tests/"):
        return TEST_SOFT, TEST_HARD
    return SOURCE_SOFT, SOURCE_HARD


@pytest.fixture(scope="module")
def _line_counts() -> dict[str, int]:
    """Line count for every tracked .py file, keyed by repo-relative posix path."""
    counts = {}
    for tree in ("src", "tests"):
        for path in (_ROOT / tree).rglob("*.py"):
            relative = path.relative_to(_ROOT).as_posix()
            counts[relative] = len(path.read_text(encoding="utf-8").splitlines())
    return counts


@pytest.mark.fab_test
def test_no_unexempted_file_exceeds_its_hard_budget(_line_counts):
    """Any file over its hard budget must be named in EXEMPTIONS, on purpose."""
    offenders = []
    for relative, count in _line_counts.items():
        if relative in EXEMPTIONS:
            continue
        _soft, hard = _budgets_for(_ROOT / relative)
        if count > hard:
            offenders.append(f"{relative}: {count} lines (hard budget {hard})")

    assert not offenders, (
        "file(s) exceed their hard budget with no exemption on record:\n"
        + "\n".join(offenders)
        + "\nSplit the file, or add a named, dated EXEMPTIONS entry with a reason."
    )


@pytest.mark.fab_test
def test_exempted_files_have_not_grown_past_their_recorded_size(_line_counts):
    """An exemption is a ceiling, not a blank check -- growing past it needs a new one."""
    grown = []
    for relative, (ceiling, _reason) in EXEMPTIONS.items():
        count = _line_counts.get(relative)
        assert count is not None, f"exempted file no longer exists: {relative}"
        if count > ceiling:
            grown.append(f"{relative}: {count} lines (exemption recorded at {ceiling})")

    assert not grown, (
        "exempted file(s) grew past their recorded ceiling:\n"
        + "\n".join(grown)
        + "\nUpdate the EXEMPTIONS entry with the new count and a reason for the growth."
    )


@pytest.mark.fab_test
def test_an_exemption_is_not_left_with_slack_after_a_cleanup(_line_counts):
    """A ceiling far above the real size stops being a ratchet.

    Mirrors test_the_ceiling_is_not_left_slack_after_a_cleanup in
    test_complexity_budget.py: a cleanup that shrinks an exempted file should
    be followed by tightening (or dropping) its exemption, not left to quietly
    carry stale headroom forever.
    """
    slack = []
    for relative, (ceiling, _reason) in EXEMPTIONS.items():
        count = _line_counts.get(relative, ceiling)
        if ceiling - count > _EXEMPTION_SLACK_MARGIN:
            slack.append(
                f"{relative}: exemption recorded at {ceiling} but file is now "
                f"{count} lines -- tighten the exemption to {count}"
            )

    assert not slack, "\n".join(slack)


@pytest.mark.fab_test
def test_every_exemption_still_needs_one(_line_counts):
    """An exemption for a file that no longer exceeds its hard budget is dead weight."""
    unnecessary = []
    for relative in EXEMPTIONS:
        count = _line_counts.get(relative)
        if count is None:
            continue
        _soft, hard = _budgets_for(_ROOT / relative)
        if count <= hard:
            unnecessary.append(f"{relative}: {count} lines is within the {hard} hard budget")

    assert not unnecessary, (
        "exemption(s) are no longer needed -- remove them from EXEMPTIONS:\n"
        + "\n".join(unnecessary)
    )
