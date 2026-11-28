"""Guard that the AIDD agent's command table mirrors the router's
(Polite Software Review epic, Skill Guards).

`.github/skills/aidd-workflow/SKILL.md` is the authority for which skills a
command loads; `.github/agents/aidd.agent.md` copies its table and says "if the
two ever disagree, the workflow skill wins -- and fix this table". Nothing
checked that, and by 2026-11-17 the copy had dropped `aidd-python` from two
commands. A row is matched by its first trigger phrase, since each table words
the rest of the triggers its own way.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_ROUTER = _ROOT / ".github" / "skills" / "aidd-workflow" / "SKILL.md"
_AGENT = _ROOT / ".github" / "agents" / "aidd.agent.md"

_SKILL_NAME = re.compile(r"`([a-z0-9-]+)`")


def _command_table(text: str, heading: str) -> dict[str, list[str]]:
    """First trigger phrase -> sorted skill names, from the table under heading."""
    rows: dict[str, list[str]] = {}
    for line in text.split(heading, 1)[1].splitlines()[1:]:
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if set(cells[0]) <= set("-: ") or cells[0].lower() == "user says":
            continue
        trigger = cells[0].replace("*", "").split(",")[0].strip().lower()
        rows[trigger] = sorted(_SKILL_NAME.findall(cells[1]))
    return rows


@pytest.mark.fab_test
def test_command_table_reads_trigger_and_skills():
    text = (
        "## Command Map\n\n| User says | Skills | Notes |\n|---|---|---|\n"
        "| **review**, code review | `aidd-review`, `aidd-please` | x |\n"
        "| help | `aidd-please` | y |\n\nAfter the table.\n| not | `a-row` |\n"
    )

    assert _command_table(text, "## Command Map") == {
        "review": ["aidd-please", "aidd-review"],
        "help": ["aidd-please"],
    }


def _section(text: str, heading: str) -> str:
    """The text under heading, up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    body = text.split(heading, 1)[1]
    return re.split(rf"\n#{{1,{len(level)}}} ", body, maxsplit=1)[0]


def _project_skills() -> set[str]:
    """Skill names in the router's Project-Specific Skills table, first column only."""
    rows = _section(_ROUTER.read_text(encoding="utf-8"), "## Project-Specific Skills").splitlines()
    return {match for line in rows if line.startswith("| `")
            for match in _SKILL_NAME.findall(line.split("|")[1])}


@pytest.mark.fab_test
def test_router_lists_polite_http_and_loads_it_for_http_work():
    router = _ROUTER.read_text(encoding="utf-8")

    assert "aidd-polite-http" in _project_skills()
    assert "load aidd-polite-http" in _section(router, "## Pre-Flight")


@pytest.mark.fab_test
def test_every_project_skill_exists_and_the_agent_lists_it():
    agent_skills = set(_SKILL_NAME.findall(_section(_AGENT.read_text(encoding="utf-8"), "## Skill Locations")))
    project = _project_skills()

    assert project, "found no Project-Specific Skills rows in aidd-workflow"
    assert sorted(s for s in project if not (_ROOT / ".github" / "skills" / s / "SKILL.md").is_file()) == []
    assert sorted(project - agent_skills) == []


@pytest.mark.fab_test
def test_agent_command_table_mirrors_the_router():
    router = _command_table(_ROUTER.read_text(encoding="utf-8"), "## Command Map")
    agent = _command_table(_AGENT.read_text(encoding="utf-8"), "## Available Commands")

    assert router, "found no Command Map rows in aidd-workflow"
    assert agent == router
