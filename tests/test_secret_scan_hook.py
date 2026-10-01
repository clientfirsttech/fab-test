"""Contract tests for the gitleaks pre-commit hook.

Scope
-----
The hook is the last line of defense between a pasted client secret and a
public commit. These tests guard the ways it could quietly stop protecting
anything: the hook dropped from the config, an unpinned rev that drifts to
whatever gitleaks ships next, or a `.gitleaks.toml` that replaces the default
ruleset instead of extending it (so the allowlist is all that is left).

They read the config files rather than running gitleaks, so they are fast
and always pass on any machine.
"""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def gitleaks_repo() -> dict:
    config = yaml.safe_load(
        (_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    repos = [r for r in config["repos"] if "gitleaks/gitleaks" in r["repo"]]
    assert len(repos) == 1, config["repos"]
    return repos[0]


@pytest.mark.fab_test
def test_pre_commit_is_a_dev_dependency():
    """A fresh clone must be able to install the hook without guessing."""
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(d.startswith("pre-commit") for d in dev), dev


@pytest.mark.fab_test
def test_gitleaks_hook_is_configured(gitleaks_repo):
    assert "gitleaks" in {h["id"] for h in gitleaks_repo["hooks"]}


@pytest.mark.fab_test
def test_gitleaks_rev_is_a_pinned_release_tag(gitleaks_repo):
    """A branch rev would change what the hook enforces without a commit here."""
    assert re.fullmatch(r"v\d+\.\d+\.\d+", gitleaks_repo["rev"]), gitleaks_repo["rev"]


@pytest.mark.fab_test
def test_gitleaks_config_extends_the_default_ruleset():
    """Without useDefault, the file's allowlist would be the whole ruleset."""
    config = tomllib.loads((_ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))

    assert config["extend"]["useDefault"] is True
