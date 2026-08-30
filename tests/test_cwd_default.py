"""The default discovery root is the working directory (Discover From CWD §4).

Scope
-----
`--artifact-dir` used to default to `.fabric/artifacts`, this repository's
CI layout rather than anything Power BI Desktop or Fabric produces. The
first command a new user typed failed against a directory they had never
heard of, while `fab-test local` started at the working directory and
found things — two answers to one question.

The backward-compatibility line is asserted here, not assumed: every
artifact found under the old default is still found under the new one,
because `.fabric/artifacts` sits inside the working directory.

Always passes on any machine.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Invoke the CLI as a user does, in ``cwd``.

    Through a subprocess on purpose: the default is read from the working
    directory at import, so an in-process call would see the test runner's.
    """
    env = {**os.environ, "PYTHONPATH": str(_ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    env.pop("GITHUB_WORKSPACE", None)
    return subprocess.run(
        [sys.executable, "-m", "fabric_ci_cd_dataops.scripts.fab_test", *args],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


@pytest.fixture
def project(tmp_path):
    """A directory with artifacts and no `.fabric/` anywhere in sight."""
    for name in ("Sales.SemanticModel", "Sales.Report"):
        (tmp_path / "deployed" / name / "definition").mkdir(parents=True)
    return tmp_path


# --------------------------------------------------------------------------- #
# The new default
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
@pytest.mark.parametrize("analyzer", ["bpa", "pbir"])
def test_an_analyzer_discovers_from_the_working_directory(project, analyzer):
    """The command that used to exit 2 against an unheard-of path."""
    result = _run([analyzer, "--dry-run"], cwd=project)

    assert result.returncode == 0, result.stderr
    assert "Sales." in result.stdout


@pytest.mark.fab_test
def test_all_discovers_from_the_working_directory(project):
    result = _run(["all", "--dry-run"], cwd=project)

    assert result.returncode == 0, result.stderr
    assert "Sales" in result.stdout


@pytest.mark.fab_test
def test_local_and_a_single_analyzer_look_in_the_same_place(project):
    """One answer to "where are my artifacts?", not two."""
    single = _run(["bpa", "--dry-run"], cwd=project)
    every = _run(["local", "--dry-run"], cwd=project)

    assert single.returncode == 0 and every.returncode == 0


@pytest.mark.fab_test
def test_list_counts_artifacts_from_the_working_directory(project):
    result = _run(["list", "--format", "json"], cwd=project)

    assert result.returncode == 0, result.stderr
    assert '"matched_artifacts": 1' in result.stdout


@pytest.mark.fab_test
def test_explain_resolves_an_artifact_from_the_working_directory(project):
    result = _run(["explain", "bpa"], cwd=project)

    assert result.returncode == 0, result.stderr
    assert "Sales.SemanticModel" in result.stdout


# --------------------------------------------------------------------------- #
# What must not change
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_the_existing_fabric_layout_is_still_found():
    """The backward-compatibility line. `.fabric/artifacts` is inside the
    working directory, so widening the default cannot lose it."""
    result = _run(["bpa", "--dry-run"], cwd=_ROOT)

    assert result.returncode == 0, result.stderr
    assert "SampleModel-PQLAssert.SemanticModel" in result.stdout


@pytest.mark.fab_test
def test_an_explicit_artifact_dir_still_wins(project):
    """A CI job passing the flag sees no change at all."""
    result = _run(["bpa", "--artifact-dir", str(project / "deployed"), "--dry-run"], cwd=_ROOT)

    assert result.returncode == 0, result.stderr
    assert "Sales.SemanticModel" in result.stdout
    assert "SampleModel-PQLAssert" not in result.stdout


@pytest.mark.fab_test
def test_an_explicit_artifact_dir_that_does_not_exist_still_exits_2(project):
    """An absent default is not an error; an explicit wrong path is."""
    result = _run(["bpa", "--artifact-dir", str(project / "absent")], cwd=project)

    assert result.returncode == 2
    assert "--artifact-dir does not exist" in (result.stdout + result.stderr)


@pytest.mark.fab_test
def test_the_config_key_still_overrides_the_default(project):
    """`artifact_dir` in pyproject.toml keeps its place in the precedence
    chain — the new default sits below it, not in front of it."""
    (project / "deployed" / "Ignored.SemanticModel").mkdir()
    (project / "pyproject.toml").write_text(
        "[tool.fab-test]\nartifact_dir = 'deployed/Sales.SemanticModel'\n",
        encoding="utf-8",
    )

    result = _run(["bpa", "--dry-run"], cwd=project)

    assert result.returncode == 0, result.stderr
    assert "Ignored" not in result.stdout


# --------------------------------------------------------------------------- #
# Documentation for all three callers (Discover From CWD §6)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
@pytest.mark.parametrize(
    "doc",
    ["README.md", "docs/QUICK-VALIDATION.md", ".github/skills/fab-test/SKILL.md"],
)
def test_each_caller_is_told_discovery_starts_at_the_working_directory(doc):
    """Human, pipeline, and agent read three different files. A behavior
    change documented in one of them has been documented for one third of
    the audience."""
    text = (_ROOT / doc).read_text(encoding="utf-8")

    assert "working directory" in text


@pytest.mark.fab_test
def test_the_human_is_told_an_existing_layout_still_works():
    """The migration question a reader with `.fabric/artifacts` will ask
    first, answered without them having to infer it."""
    text = (_ROOT / "README.md").read_text(encoding="utf-8")

    assert "nothing you do needs to" in text


@pytest.mark.fab_test
def test_the_pipeline_author_is_told_to_pin_artifact_dir():
    """A default that follows the working directory is right at a prompt
    and wrong in a build."""
    text = (_ROOT / "docs" / "QUICK-VALIDATION.md").read_text(encoding="utf-8")

    assert "explicit in CI" in text


@pytest.mark.fab_test
def test_the_agent_skill_documents_the_type_source_and_the_exclusions():
    """An agent that does not know what is pruned cannot explain why an
    artifact inside a worktree was not analyzed.

    fab-test Skill Componentization split this fact out of SKILL.md into
    references/*.md, so "the skill documents X" means the whole directory.
    """
    skill_dir = _ROOT / ".github" / "skills" / "fab-test"
    text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in [skill_dir / "SKILL.md", *sorted((skill_dir / "references").glob("*.md"))]
    )

    assert "artifact-map.json" in text
    assert "node_modules" in text
    assert "packaged" in text.lower()


@pytest.mark.fab_test
def test_no_doc_still_claims_artifact_dir_defaults_to_the_fabric_layout():
    """The stale claim that sent a new user to a directory they had never
    heard of."""
    for doc in ("README.md", "docs/QUICK-VALIDATION.md", ".github/skills/fab-test/SKILL.md"):
        text = (_ROOT / doc).read_text(encoding="utf-8")
        assert "default: .fabric/artifacts" not in text, doc
        assert "| `.fabric/artifacts`" not in text, doc
