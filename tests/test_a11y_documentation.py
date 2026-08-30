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


@pytest.mark.fab_test
@pytest.mark.parametrize("doc", [_README, _QUICK_VALIDATION, _SKILL], ids=lambda p: p.name)
def test_every_caller_knows_a11y_exists(doc: Path):
    text = doc.read_text(encoding="utf-8")
    assert "a11y" in text


@pytest.mark.fab_test
@pytest.mark.parametrize("doc", [_README, _QUICK_VALIDATION, _SKILL], ids=lambda p: p.name)
def test_every_caller_is_told_about_the_node_prerequisite(doc: Path):
    """The one thing a11y needs that no other analyzer does."""
    text = doc.read_text(encoding="utf-8")
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
    text = _SKILL.read_text(encoding="utf-8")
    assert "fab-test a11y" in text
    assert "category" in text and "visual" in text
    assert "PBIR_A11Y_PATH" in text


@pytest.mark.fab_test
def test_the_agent_skill_explains_the_fab_test_all_opt_in():
    text = _SKILL.read_text(encoding="utf-8")
    assert "fab_test_all" in text
