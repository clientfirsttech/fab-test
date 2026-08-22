"""Policy tests for which workflows run themselves (TestPyPI Release, CI noise).

Scope
-----
This repository publishes the `fab-test` CLI. It also carries the Fabric
artifact pipeline it grew out of -- an orchestrator, a change detector, an
artifact runner, a testbed -- which need a `.fabric/artifacts` layout, a
workspace, and service-principal credentials that a CLI package repository
has no reason to hold.

Those workflows fired on the first `dev` -> `main` pull request and failed,
burying the one result that mattered: whether the package builds and its
tests pass. They stay in the repository and stay invocable, but nothing here
starts them on its own.

`copilot-setup-steps.yml` is checked separately: it is the file GitHub
Copilot's agent reads to pre-install dependencies, and it arrived from a
JS/TS template -- `npm ci` with no package.json in the tree, two script
paths that do not exist, and Python 3.11 against a `>=3.12` project.

    pytest -m fab_test tests/test_workflow_triggers.py
"""

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _ROOT / ".github" / "workflows"

# The Fabric artifact pipeline. Deployment and artifact analysis belong to the
# reference implementation; this repository only builds and publishes the CLI.
_PIPELINE_WORKFLOWS = (
    "orchestrator.yml",
    "detect-changes.yml",
    "artifact-runner.yml",
    "testbed.yml",
    "dynamic-validation.yml",
    "dynamic-visual-validation.yml",
    "ai-governance.yml",
    "security-scan.yml",
    "reusable-telemetry.yml",
)

# Everything that should run itself, and nothing else.
_EXPECTED_SELF_STARTING = {"build.yml", "publish.yml", "publish-testpypi.yml", "copilot-setup-steps.yml"}

_SELF_STARTING_TRIGGERS = ("push", "pull_request", "pull_request_target", "schedule")


def _triggers(name: str) -> dict:
    """Return a workflow's `on:` block. PyYAML reads a bare `on` key as True."""
    data = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    return data.get("on", data.get(True)) or {}


def _steps(name: str) -> list[dict]:
    data = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    return [step for job in data["jobs"].values() for step in job.get("steps", [])]


@pytest.mark.fab_test
@pytest.mark.parametrize("name", _PIPELINE_WORKFLOWS)
def test_no_pipeline_workflow_starts_itself(name):
    """A red check nobody can act on trains people to ignore red checks."""
    self_starting = [t for t in _SELF_STARTING_TRIGGERS if t in _triggers(name)]

    assert self_starting == [], f"{name} runs automatically on {self_starting}"


@pytest.mark.fab_test
@pytest.mark.parametrize("name", _PIPELINE_WORKFLOWS)
def test_every_pipeline_workflow_is_still_reachable(name):
    """Gated, not disabled. Removing the trigger must not orphan the workflow."""
    triggers = _triggers(name)

    assert {"workflow_dispatch", "workflow_call"} & set(triggers), sorted(triggers)


@pytest.mark.fab_test
def test_only_the_package_workflows_run_themselves():
    """Catches a new self-starting workflow, not just the ones known today."""
    self_starting = {
        path.name
        for path in _WORKFLOWS.glob("*.yml")
        if any(t in _triggers(path.name) for t in _SELF_STARTING_TRIGGERS)
    }

    assert self_starting == _EXPECTED_SELF_STARTING, self_starting


# --------------------------------------------------------------------------
# The Copilot setup steps have to actually work on this project
# --------------------------------------------------------------------------


@pytest.mark.fab_test
def test_copilot_setup_does_not_install_a_javascript_project():
    """`npm ci` needs a package-lock.json; this repository has no package.json.

    The step failed on every run, which is worse than absent -- Copilot's
    agent starts from a setup that errored.
    """
    runs = " ".join(str(step.get("run", "")) for step in _steps("copilot-setup-steps.yml"))
    uses = " ".join(str(step.get("uses", "")) for step in _steps("copilot-setup-steps.yml"))

    assert "npm" not in runs, runs
    assert "bun" not in runs.lower() and "setup-bun" not in uses, uses
    assert "setup-node" not in uses, uses


@pytest.mark.fab_test
def test_copilot_setup_installs_this_project():
    """Its whole purpose is having the dependencies ready before the agent starts."""
    runs = " ".join(str(step.get("run", "")) for step in _steps("copilot-setup-steps.yml"))

    assert "pip install" in runs and "[dev]" in runs, runs


@pytest.mark.fab_test
def test_copilot_setup_uses_a_python_this_project_supports():
    """pyproject requires >=3.12; the workflow asked for 3.11."""
    versions = [
        str(step.get("with", {}).get("python-version", ""))
        for step in _steps("copilot-setup-steps.yml")
        if "setup-python" in str(step.get("uses", ""))
    ]

    assert versions, "no setup-python step"
    for version in versions:
        assert tuple(int(p) for p in version.split(".")) >= (3, 12), version


@pytest.mark.fab_test
def test_every_path_the_copilot_setup_checks_exists():
    """It verified two scripts under a top-level `scripts/` that does not exist.

    A baseline check that names a missing file does not verify a baseline;
    it just fails.
    """
    runs = "\n".join(str(step.get("run", "")) for step in _steps("copilot-setup-steps.yml"))
    referenced = [
        token
        for line in runs.splitlines()
        for token in line.split()
        if ("/" in token or token.endswith(".md")) and not token.startswith("-")
    ]
    missing = sorted({t for t in referenced if t.count(".") and not (_ROOT / t).exists()})

    assert missing == [], missing


@pytest.mark.fab_test
def test_the_copilot_job_keeps_the_name_copilot_requires():
    """Renaming the job silently stops Copilot from picking it up."""
    data = yaml.safe_load((_WORKFLOWS / "copilot-setup-steps.yml").read_text(encoding="utf-8"))

    assert "copilot-setup-steps" in data["jobs"], sorted(data["jobs"])


@pytest.mark.fab_test
def test_python_version_matches_what_the_other_workflows_pin():
    """Copilot's agent and CI should not disagree about the interpreter."""
    def pinned(name: str) -> set[str]:
        return {
            str(step.get("with", {}).get("python-version", ""))
            for step in _steps(name)
            if "setup-python" in str(step.get("uses", ""))
        }

    assert pinned("copilot-setup-steps.yml") <= pinned("build.yml") | {""}, (
        pinned("copilot-setup-steps.yml"),
        pinned("build.yml"),
    )
