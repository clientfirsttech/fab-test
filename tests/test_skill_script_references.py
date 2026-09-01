"""Guard that a skill's `scripts/X.py` references point at real files
(Fabric CI/CD Deployment Skill Retirement epic).

`fabric-cicd-deployment/SKILL.md` kept documenting `deploy.py`,
`check_promotion_safety.py`, and `generate_fabric_cicd_config.py` as its
live interface after all three were deleted by the Pipeline Deletion
Dead-Code Audit epic -- caught only by a manual review, not the suite. A
skill explicitly retired is exempt (its whole point is describing tooling
that no longer exists); every other skill's script references must resolve.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _ROOT / "src" / "fab_test" / "scripts"
_SKILLS_DIR = _ROOT / ".github" / "skills"

# Named explicitly rather than by a frontmatter flag nothing else reads yet --
# one retired skill doesn't justify a general "retired" convention (YAGNI).
_RETIRED_SKILLS = {"fabric-cicd-deployment"}

_SCRIPT_REF = re.compile(r"scripts/([A-Za-z0-9_]+\.py)")


def _active_skill_markdown_files() -> list[Path]:
    return [
        md_path
        for md_path in sorted(_SKILLS_DIR.rglob("*.md"))
        if md_path.relative_to(_SKILLS_DIR).parts[0] not in _RETIRED_SKILLS
    ]


@pytest.mark.fab_test
def test_active_skills_only_reference_scripts_that_exist():
    """A skill telling an agent to run `scripts/X.py` must have that file."""
    missing = [
        f"{md_path.relative_to(_ROOT)}: scripts/{match.group(1)}"
        for md_path in _active_skill_markdown_files()
        for match in _SCRIPT_REF.finditer(md_path.read_text(encoding="utf-8"))
        if not (_SCRIPTS_DIR / match.group(1)).exists()
    ]

    assert not missing, "skill doc references a script that does not exist:\n" + "\n".join(missing)
