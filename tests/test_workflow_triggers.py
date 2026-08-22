"""Policy tests for what CI this repository runs (TestPyPI Release, CI noise).

Scope
-----
This repository publishes the `fab-test` CLI. It used to also carry the
Fabric artifact pipeline it grew out of -- an orchestrator, a change
detector, an artifact runner, a testbed, telemetry, governance and security
scanning: nine workflows and 101 KB of YAML, every one of them reachable
only by `workflow_call` from the orchestrator.

They fired on the first `dev` -> `main` pull request and failed for want of
a `.fabric/artifacts` layout and service-principal credentials this
repository has no reason to hold, burying the one result that mattered --
whether the package builds and its tests pass. vision.md already named
deployment a non-goal, and the reference implementation is a separate
repository, so they were deleted rather than gated.

What is left is what a package repository needs: build, publish, rehearse,
and the setup GitHub Copilot's agent reads.

    pytest -m fab_test tests/test_workflow_triggers.py
"""

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _ROOT / ".github" / "workflows"

# Every workflow this repository should have. An addition is a deliberate
# decision, so it belongs in a diff rather than arriving unnoticed.
_EXPECTED_WORKFLOWS = {
    "build.yml",
    "publish.yml",
    "publish-testpypi.yml",
    "copilot-setup-steps.yml",
}

_SELF_STARTING_TRIGGERS = ("push", "pull_request", "pull_request_target", "schedule")


def _triggers(name: str) -> dict:
    """Return a workflow's `on:` block. PyYAML reads a bare `on` key as True."""
    data = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    return data.get("on", data.get(True)) or {}


def _steps(name: str) -> list[dict]:
    data = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    return [step for job in data["jobs"].values() for step in job.get("steps", [])]


@pytest.mark.fab_test
def test_the_repository_carries_only_the_package_workflows():
    """The Fabric pipeline belongs to the reference implementation, not here.

    Asserted as a set rather than as absences, so a workflow arriving back
    fails just as loudly as one going missing.
    """
    present = {path.name for path in _WORKFLOWS.glob("*.yml")}

    assert present == _EXPECTED_WORKFLOWS, present


@pytest.mark.fab_test
@pytest.mark.parametrize("name", sorted(_EXPECTED_WORKFLOWS))
def test_no_local_reference_dangles(name):
    """A `uses: ./...` naming a deleted file fails only when the job runs.

    Nine workflows and five composite actions were removed at once; this is
    what catches the reference that was missed.
    """
    data = yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))
    local = [
        job["uses"].split("@")[0]
        for job in data["jobs"].values()
        if str(job.get("uses", "")).startswith("./")
    ]
    local += [
        str(step["uses"]).split("@")[0]
        for step in _steps(name)
        if str(step.get("uses", "")).startswith("./")
    ]
    missing = [ref for ref in local if not (_ROOT / ref.lstrip("./")).exists()]

    assert missing == [], missing


@pytest.mark.fab_test
def test_the_scripts_the_workflows_call_exist():
    """The release guards live in .github/scripts and are invoked by path."""
    for name in sorted(_EXPECTED_WORKFLOWS):
        for step in _steps(name):
            for token in str(step.get("run", "")).split():
                if token.startswith(".github/scripts/"):
                    assert (_ROOT / token).exists(), f"{name} calls missing {token}"


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
