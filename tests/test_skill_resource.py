"""Contract tests for the packaged fab-test skill resource.

`.github/skills/fab-test/` (a main `SKILL.md` plus `references/*.md`,
fab-test Skill Componentization epic) is hand-authored and synced to the
CLI only by the `document` skill's discipline -- nothing stops a `pip
install`d fab-test from running a version its own skill files were never
updated for. These tests guard the two halves of the fix: the packaged
copy under `src/fabric_ci_cd_dataops/skill/` never drifts from the
authored source, file for file, and the main file's frontmatter names the
version it was packaged with so a hand-copy outside this repo still shows
its age. See the fab-test Skill Distribution and Skill Componentization
epics.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fabric_ci_cd_dataops import __version__
from fabric_ci_cd_dataops.scripts._metadata import (
    PACKAGED_ORIGIN,
    PACKAGED_SKILL_DIR,
    resolve_skill_dir,
)

_ROOT = Path(__file__).resolve().parent.parent
_AUTHORED_SKILL_DIR = _ROOT / ".github" / "skills" / "fab-test"
_AUTHORED_SKILL_MD = _AUTHORED_SKILL_DIR / "SKILL.md"

pytestmark = pytest.mark.fab_test


def _component_relative_paths(root: Path) -> list[Path]:
    paths = [Path("SKILL.md")]
    references_dir = root / "references"
    if references_dir.is_dir():
        paths.extend(sorted(p.relative_to(root) for p in references_dir.glob("*.md")))
    return paths


@pytest.mark.parametrize("relative", _component_relative_paths(_AUTHORED_SKILL_DIR), ids=str)
def test_packaged_skill_component_matches_the_authored_source(relative):
    """No packaged component -- main file or reference -- is ever allowed to drift."""
    authored = (_AUTHORED_SKILL_DIR / relative).read_text(encoding="utf-8")
    packaged = (PACKAGED_SKILL_DIR / relative).read_text(encoding="utf-8")
    assert packaged == authored


def test_packaged_skill_has_no_extra_or_missing_components():
    authored = {str(p) for p in _component_relative_paths(_AUTHORED_SKILL_DIR)}
    packaged = {str(p) for p in _component_relative_paths(PACKAGED_SKILL_DIR)}
    assert packaged == authored


def test_skill_description_names_the_current_version():
    """A hand-copy outside this repo should still show its own age."""
    frontmatter = _AUTHORED_SKILL_MD.read_text(encoding="utf-8").split("---")[1]
    description = next(
        line for line in frontmatter.splitlines() if line.startswith("description:")
    )
    assert re.search(re.escape(__version__), description), (
        f"description does not name the current version {__version__}: {description}"
    )


def test_skill_main_file_keeps_its_required_sudolang_constructs():
    """A durable guard against the skill drifting back to a monolithic prose
    file -- fab-test Skill SudoLang epic. Checks for the presence of the
    constructs, not their exact content, so authoring can still evolve."""
    content = _AUTHORED_SKILL_MD.read_text(encoding="utf-8")
    assert "Constraints {" in content, "main SKILL.md lost its SudoLang Constraints block"
    assert re.search(r"^\w+ \{$", content, re.MULTILINE), (
        "main SKILL.md lost its SudoLang Interface-shaped type block"
    )


def test_resolve_skill_dir_falls_back_to_packaged_with_no_override(tmp_path):
    resolved = resolve_skill_dir(tmp_path)

    assert resolved.path == PACKAGED_SKILL_DIR
    assert resolved.origin == PACKAGED_ORIGIN


def test_resolve_skill_dir_prefers_a_github_skills_override(tmp_path):
    override_dir = tmp_path / ".github" / "skills" / "fab-test"
    override_dir.mkdir(parents=True)
    (override_dir / "SKILL.md").write_text("local copy", encoding="utf-8")

    resolved = resolve_skill_dir(tmp_path)

    assert resolved.path == override_dir
    assert resolved.origin == ".github/skills/fab-test"


def test_resolve_skill_dir_prefers_fab_test_skill_over_github_skills(tmp_path):
    fab_test_dir = tmp_path / ".fab-test" / "skill"
    fab_test_dir.mkdir(parents=True)
    (fab_test_dir / "SKILL.md").write_text("fab-test dir copy", encoding="utf-8")

    github_dir = tmp_path / ".github" / "skills" / "fab-test"
    github_dir.mkdir(parents=True)
    (github_dir / "SKILL.md").write_text("github dir copy", encoding="utf-8")

    resolved = resolve_skill_dir(tmp_path)

    assert resolved.path == fab_test_dir
    assert resolved.origin == ".fab-test/skill"


def test_resolve_skill_dir_ignores_an_override_dir_with_no_skill_md(tmp_path):
    empty_override = tmp_path / ".github" / "skills" / "fab-test"
    empty_override.mkdir(parents=True)
    (empty_override / "references").mkdir()

    resolved = resolve_skill_dir(tmp_path)

    assert resolved.path == PACKAGED_SKILL_DIR
    assert resolved.origin == PACKAGED_ORIGIN
