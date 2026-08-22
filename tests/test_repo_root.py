"""Contract tests for how the CLI decides what "the repository" is.

Scope
-----
`GITHUB_WORKSPACE` used to win unconditionally, so inside GitHub Actions the
CLI ignored the directory it was invoked from. `cd subdir && fab-test init`
wrote its config to the workspace root instead of `subdir`, silently -- and
ten tests that run the CLI with `cwd=tmp_path` failed the moment CI ran for
the first time, having always passed on developer machines where the
variable is unset.

The rule now: the workspace wins only when the working directory is
genuinely inside it. That keeps what the variable was for -- running from a
subdirectory of the checkout still resolves to the checkout root -- without
letting it hijack a working directory that has nothing to do with it.

Always passes on any machine: the environment is set explicitly rather than
inherited, so these behave the same locally and in CI.

    pytest -m fab_test tests/test_repo_root.py
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._metadata import default_repo_root

_ROOT = Path(__file__).resolve().parent.parent

# The modules that make up the CLI's idea of a repository root. Three copies
# of the same four lines lived here, and fab_test_registry's comment claimed
# it reused fab_test's -- which was an aspiration, not a fact.
_CLI_ROOT_MODULES = (
    "fab_test.py",
    "fab_test_registry.py",
    "_metadata.py",
)


@pytest.mark.fab_test
def test_the_working_directory_is_the_root_when_nothing_says_otherwise(tmp_path, monkeypatch):
    """Outside CI there is no workspace, so the CWD is the whole answer."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)

    assert default_repo_root() == tmp_path.resolve()


@pytest.mark.fab_test
def test_the_workspace_wins_from_a_subdirectory_of_the_checkout(tmp_path, monkeypatch):
    """What the variable was for: `cd src && fab-test bpa` still means the repo.

    Losing this would make discovery depend on which directory a workflow
    step happened to be standing in.
    """
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.chdir(workspace / "src")

    assert default_repo_root() == workspace.resolve()


@pytest.mark.fab_test
def test_the_workspace_wins_when_it_is_the_working_directory(tmp_path, monkeypatch):
    """The ordinary CI case, where the two agree anyway."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.chdir(workspace)

    assert default_repo_root() == workspace.resolve()


@pytest.mark.fab_test
def test_a_working_directory_outside_the_workspace_is_not_hijacked(tmp_path, monkeypatch):
    """The bug. A caller who cd'd elsewhere meant elsewhere.

    This is what made `fab-test init` write to the workspace root during a
    test that had deliberately chdir'd into a temporary directory.
    """
    workspace = tmp_path / "workspace"
    elsewhere = tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.chdir(elsewhere)

    assert default_repo_root() == elsewhere.resolve()


@pytest.mark.fab_test
def test_an_unset_workspace_variable_is_treated_as_absent(tmp_path, monkeypatch):
    """An empty string is not a path; `GITHUB_WORKSPACE=` must not win."""
    monkeypatch.setenv("GITHUB_WORKSPACE", "")
    monkeypatch.chdir(tmp_path)

    assert default_repo_root() == tmp_path.resolve()


@pytest.mark.fab_test
def test_only_one_module_decides_what_the_repository_root_is():
    """Three copies of a rule is three places for it to stop agreeing.

    The duplication is why this bug had to be fixed once per module before
    it was consolidated, and why the fix is asserted structurally here.
    """
    scripts = _ROOT / "src" / "fabric_ci_cd_dataops" / "scripts"
    deciding = [
        name
        for name in _CLI_ROOT_MODULES
        if re.search(r'getenv\(\s*"GITHUB_WORKSPACE"', (scripts / name).read_text(encoding="utf-8"))
    ]

    assert deciding == ["_metadata.py"], deciding


@pytest.mark.fab_test
def test_the_cli_writes_its_config_where_it_was_invoked_even_inside_actions(tmp_path):
    """The end-to-end shape of the CI failure, through the real console script.

    `REPO_ROOT` is a module-level constant, so only a fresh process proves
    this -- which is also why every developer machine passed while CI did not.
    """
    workspace = tmp_path / "workspace"
    invoked_from = tmp_path / "invoked_from"
    workspace.mkdir()
    invoked_from.mkdir()

    result = subprocess.run(
        ["fab-test", "init"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=invoked_from,
        env={**os.environ, "GITHUB_WORKSPACE": str(workspace)},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (invoked_from / "fab-test.yml").exists(), "config went somewhere other than the CWD"
    assert not (workspace / "fab-test.yml").exists(), "config leaked into GITHUB_WORKSPACE"
