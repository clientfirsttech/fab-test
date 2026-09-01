"""Documentation for all three callers (PBIR Accessibility Integration epic,
Documentation for Three Callers task) -- mirrors the pattern
tests/test_cwd_default.py already established for a cross-cutting change:
human, pipeline, and agent read three different files, so a fact missing
from one of them has been documented for only two-thirds of the audience.

    pytest -m fab_test tests/test_a11y_documentation.py
"""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_README = _ROOT / "README.md"
_QUICK_VALIDATION = _ROOT / "docs" / "QUICK-VALIDATION.md"
_SKILL = _ROOT / ".github" / "skills" / "fab-test" / "SKILL.md"
_SKILL_DIR = _SKILL.parent


def _skill_text() -> str:
    """The whole agent skill's content, not just its main file.

    fab-test Skill Componentization split SKILL.md's reference-heavy
    sections into references/*.md -- a fact an agent needs may now live in
    either, so "does the skill document X" means the whole directory.
    """
    parts = [_SKILL.read_text(encoding="utf-8")]
    parts.extend(p.read_text(encoding="utf-8") for p in sorted((_SKILL_DIR / "references").glob("*.md")))
    return "\n".join(parts)


def _caller_docs() -> list[tuple[str, str]]:
    return [
        ("README.md", _README.read_text(encoding="utf-8")),
        ("QUICK-VALIDATION.md", _QUICK_VALIDATION.read_text(encoding="utf-8")),
        ("SKILL.md", _skill_text()),
    ]


@pytest.mark.fab_test
@pytest.mark.parametrize("doc", _caller_docs(), ids=lambda d: d[0])
def test_every_caller_knows_a11y_exists(doc: tuple[str, str]):
    _name, text = doc
    assert "a11y" in text


@pytest.mark.fab_test
@pytest.mark.parametrize("doc", _caller_docs(), ids=lambda d: d[0])
def test_every_caller_is_told_about_the_node_prerequisite(doc: tuple[str, str]):
    """The one thing a11y needs that no other analyzer does."""
    _name, text = doc
    assert "Node.js" in text or "node.js" in text.lower()


@pytest.mark.fab_test
def test_the_human_finds_a_worked_example():
    text = _README.read_text(encoding="utf-8")
    assert "fab-test a11y" in text


@pytest.mark.fab_test
def test_the_pipeline_author_finds_a_node_setup_snippet():
    text = _QUICK_VALIDATION.read_text(encoding="utf-8")
    assert "setup-node" in text
    assert "fab-test a11y" in text


@pytest.mark.fab_test
def test_the_agent_skill_documents_the_subcommand_and_envelope_shape():
    """An agent parsing an a11y envelope needs to know the extra keys exist
    and what the exit-code/status distinction means before it can act on one."""
    text = _skill_text()
    assert "fab-test a11y" in text
    assert "category" in text and "visual" in text
    assert "PBIR_A11Y_PATH" in text


@pytest.mark.fab_test
def test_the_agent_skill_explains_the_fab_test_all_opt_in():
    text = _skill_text()
    assert "fab_test_all" in text
