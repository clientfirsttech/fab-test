"""Documentation for all three callers for the data-agent analyzer."""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_README = _ROOT / "README.md"
_QUICK_VALIDATION = _ROOT / "docs" / "QUICK-VALIDATION.md"
_SKILL = _ROOT / ".github" / "skills" / "fab-test" / "SKILL.md"
_SKILL_DIR = _SKILL.parent


def _skill_text() -> str:
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
def test_every_caller_knows_data_agent_exists(doc: tuple[str, str]):
    _name, text = doc
    assert "data-agent" in text


@pytest.mark.fab_test
@pytest.mark.parametrize("doc", _caller_docs(), ids=lambda d: d[0])
def test_every_caller_is_told_the_tests_live_in_dataagent_folders(doc: tuple[str, str]):
    _name, text = doc
    assert ".DataAgent" in text
    assert "promptfooconfig.yaml" in text


@pytest.mark.fab_test
def test_the_human_docs_show_init_and_workspace_examples():
    readme = _README.read_text(encoding="utf-8")
    quick = _QUICK_VALIDATION.read_text(encoding="utf-8")
    assert "fab-test data-agent init" in readme
    assert "fab-test data-agent --workspace" in readme
    assert "fab-test data-agent --workspace" in quick


@pytest.mark.fab_test
def test_the_skill_documents_alias_credentials_and_the_threshold():
    text = _skill_text()
    assert "agent" in text
    assert "FABRIC_TENANT_ID" in text
    assert "FABRIC_CLIENT_ID" in text
    assert "FABRIC_CLIENT_SECRET" in text
    assert "more than 5" in text or "5 agents" in text
