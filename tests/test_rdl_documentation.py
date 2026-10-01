"""Documentation for all three callers (RDL Static Analysis epic,
Documentation task) -- mirrors tests/test_a11y_documentation.py: human,
pipeline, and agent read three different files, so a fact missing from
one of them has been documented for only two-thirds of the audience.

    pytest -m fab_test tests/test_rdl_documentation.py
"""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_README = _ROOT / "README.md"
_QUICK_VALIDATION = _ROOT / "docs" / "QUICK-VALIDATION.md"
_SKILL = _ROOT / ".github" / "skills" / "fab-test" / "SKILL.md"
_SKILL_DIR = _SKILL.parent


def _skill_text() -> str:
    """The whole agent skill's content, not just its main file -- fab-test
    Skill Componentization split reference-heavy sections into
    references/*.md, so "does the skill document X" means the whole directory.
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
def test_every_caller_knows_rdl_exists(doc: tuple[str, str]):
    _name, text = doc
    assert "fab-test rdl" in text


@pytest.mark.fab_test
@pytest.mark.parametrize("doc", _caller_docs(), ids=lambda d: d[0])
def test_every_caller_is_told_no_external_tool_is_needed(doc: tuple[str, str]):
    """The one thing that distinguishes rdl from bpa/pbir/a11y."""
    _name, text = doc
    assert "no external tool" in text.lower()


@pytest.mark.fab_test
def test_the_human_finds_a_worked_example():
    text = _README.read_text(encoding="utf-8")
    assert "fab-test rdl" in text


@pytest.mark.fab_test
def test_the_pipeline_author_finds_a_copy_pasteable_snippet():
    text = _QUICK_VALIDATION.read_text(encoding="utf-8")
    assert "fab-test rdl --format json" in text
    assert "High" in text


@pytest.mark.fab_test
def test_the_agent_skill_documents_the_subcommand_and_rule_count():
    """An agent needs the rule count and the rules-path override before it
    can act on an rdl envelope or tune the catalog."""
    text = _skill_text()
    assert "fab-test rdl" in text
    assert "Tier A" in text
    assert "docs/RDL-RULES.md" in text
    assert "--rdl-rules-path" in text


@pytest.mark.fab_test
def test_the_agent_skill_explains_the_lay03_sub01_merge():
    """The one shared-finding behavior an agent parsing findings needs to
    know about before it double-counts a subreport-in-tablix gap."""
    text = _skill_text()
    assert "LAY-03/SUB-01" in text


@pytest.mark.fab_test
def test_the_agent_skill_documents_the_rule_overlay():
    text = _skill_text()
    assert "rules.rdl" in text


@pytest.mark.fab_test
def test_the_agent_skill_shows_rdl_in_the_fab_test_all_default_list():
    text = _skill_text()
    assert '"rdl"' in text


def test_the_rule_reference_is_generated_from_the_catalog():
    """docs/RDL-RULES.md is generated; a hand edit or a catalog change
    without regenerating fails here (python tools/generate_rdl_rules_doc.py)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen", _ROOT / "tools" / "generate_rdl_rules_doc.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (_ROOT / "docs" / "RDL-RULES.md").read_text(encoding="utf-8") == gen.render()


def test_the_human_readme_points_at_the_rule_reference():
    assert "docs/RDL-RULES.md" in _README.read_text(encoding="utf-8")


def test_every_catalog_rule_has_a_source_link_except_the_untraced_sources():
    """DS-07 (DMC blog) and LAY-01 (DataTaal guide) cite sources with no
    known URL; they still need the Microsoft/MSSQLTips link they have."""
    import json

    rules = json.loads(
        (_ROOT / "src" / "fab_test" / "metadata" / "rules" / "rdl-rules.json").read_text(encoding="utf-8")
    )["rules"]
    for rule in rules:
        assert rule.get("source_urls"), rule["id"]
        assert all(u.startswith("https://") for u in rule["source_urls"]), rule["id"]


def test_the_rule_reference_explains_how_to_read_a_finding():
    text = (_ROOT / "docs" / "RDL-RULES.md").read_text(encoding="utf-8")
    assert "Reading a finding" in text
    assert "Outer › Inner" in text


@pytest.mark.fab_test
def test_the_agent_skill_explains_finding_paths_and_per_hit_rows():
    text = _skill_text()
    assert "Dataset › Field" in text
    assert "one `test_results` row per hit" in text
