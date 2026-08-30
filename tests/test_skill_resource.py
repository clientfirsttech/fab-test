"""Contract tests for the packaged fab-test skill resource.

`.github/skills/fab-test/SKILL.md` is hand-authored and synced to the CLI
only by the `document` skill's discipline -- nothing stops a `pip install`d
fab-test from running a version its own skill file was never updated for.
These tests guard the two halves of the fix: the packaged copy under
`src/fabric_ci_cd_dataops/skill/` never drifts from the authored source, and
its frontmatter names the version it was packaged with so a hand-copy
outside this repo still shows its age. See the fab-test Skill Distribution
epic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fabric_ci_cd_dataops import __version__
from fabric_ci_cd_dataops.scripts._metadata import (
    PACKAGED_ORIGIN,
    PACKAGED_SKILL,
    resolve_skill_md,
)

_ROOT = Path(__file__).resolve().parent.parent
_AUTHORED_SKILL = _ROOT / ".github" / "skills" / "fab-test" / "SKILL.md"

pytestmark = pytest.mark.fab_test


def test_packaged_skill_matches_the_authored_source():
    """The packaged copy is never allowed to drift from what was authored."""
    assert PACKAGED_SKILL.read_text(encoding="utf-8") == _AUTHORED_SKILL.read_text(
        encoding="utf-8"
    )


def test_skill_description_names_the_current_version():
    """A hand-copy outside this repo should still show its own age."""
    frontmatter = _AUTHORED_SKILL.read_text(encoding="utf-8").split("---")[1]
    description = next(
        line for line in frontmatter.splitlines() if line.startswith("description:")
    )
    assert re.search(re.escape(__version__), description), (
        f"description does not name the current version {__version__}: {description}"
    )


def test_resolve_skill_md_falls_back_to_packaged_with_no_override(tmp_path):
    resolved = resolve_skill_md(tmp_path)

    assert resolved.path == PACKAGED_SKILL
    assert resolved.origin == PACKAGED_ORIGIN


def test_resolve_skill_md_prefers_a_github_skills_override(tmp_path):
    override = tmp_path / ".github" / "skills" / "fab-test" / "SKILL.md"
    override.parent.mkdir(parents=True)
    override.write_text("local copy", encoding="utf-8")

    resolved = resolve_skill_md(tmp_path)

    assert resolved.path == override
    assert resolved.origin == ".github/skills/fab-test/SKILL.md"


def test_resolve_skill_md_prefers_fab_test_skill_over_github_skills(tmp_path):
    fab_test_override = tmp_path / ".fab-test" / "skill" / "SKILL.md"
    fab_test_override.parent.mkdir(parents=True)
    fab_test_override.write_text("fab-test dir copy", encoding="utf-8")

    github_override = tmp_path / ".github" / "skills" / "fab-test" / "SKILL.md"
    github_override.parent.mkdir(parents=True)
    github_override.write_text("github dir copy", encoding="utf-8")

    resolved = resolve_skill_md(tmp_path)

    assert resolved.path == fab_test_override
    assert resolved.origin == ".fab-test/skill/SKILL.md"
