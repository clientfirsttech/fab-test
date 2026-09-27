"""Guard: the Playwright demo/example workflows and the guide agree with each other.

Scope
-----
Two workflows exist for `fab-test playwright` against a real workspace:
`playwright-demo.yml` (in this repository, behind a protected `fabric-demo`
Environment) and `docs/examples/github-actions/playwright-live.yml` (a
copy-ready example for a consumer's own repository). Both are hand-authored
YAML that can drift from each other, from `docs/PLAYWRIGHT-CI.md`, and from
`tests/test_workflow_triggers.py`'s own no-service-principal policy without
anything failing until someone actually runs one (Playwright CI Guide
epic).

    pytest -m fab_test tests/test_playwright_workflows_drift.py
"""

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_DEMO = _ROOT / ".github" / "workflows" / "playwright-demo.yml"
_EXAMPLE = _ROOT / "docs" / "examples" / "github-actions" / "playwright-live.yml"
_GUIDE = _ROOT / "docs" / "PLAYWRIGHT-CI.md"

# The three names both workflows and the guide must agree the service
# principal is read from -- a rename in one place that isn't caught here
# breaks the reader's first run, not the build.
_CREDENTIAL_VARS = ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(data: dict) -> dict:
    """PyYAML reads a bare `on` key as the boolean True."""
    return data.get("on", data.get(True)) or {}


def _steps(data: dict) -> list[dict]:
    return [step for job in data["jobs"].values() for step in job.get("steps", [])]


def _step_text(step: dict) -> str:
    return "\n".join(str(step.get(key, "")) for key in ("run", "uses"))


@pytest.mark.fab_test
@pytest.mark.parametrize("path", [_DEMO, _EXAMPLE], ids=["demo", "example"])
def test_the_browser_installs_before_any_fab_test_step(path: Path) -> None:
    """`playwright install` with no browser binary yet fails every case at
    fixture setup -- it must run before the first step that invokes fab-test.

    Not required when the job's container image already bundles the
    browsers (see playwright.dev/python/docs/docker)."""
    data = _load(path)
    ((_job_id, job),) = data["jobs"].items()
    if "playwright" in str(job.get("container", "")):
        return

    steps = _steps(data)
    browser_index = next(i for i, s in enumerate(steps) if "playwright install" in _step_text(s))
    fab_test_index = next(
        i
        for i, s in enumerate(steps)
        if "fab-test doctor" in _step_text(s) or "fab-test playwright" in _step_text(s)
    )

    assert browser_index < fab_test_index, [s.get("name") for s in steps]


@pytest.mark.fab_test
@pytest.mark.parametrize("path", [_DEMO, _EXAMPLE], ids=["demo", "example"])
def test_the_upload_step_runs_even_when_the_run_step_failed(path: Path) -> None:
    """The failed run is the one you most want to read -- upload must not
    depend on the run step having succeeded."""
    steps = _steps(_load(path))
    upload_steps = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]

    assert upload_steps, "no upload-artifact step found"
    for step in upload_steps:
        assert step.get("if") == "always()", step.get("name")


@pytest.mark.fab_test
@pytest.mark.parametrize("path", [_DEMO, _EXAMPLE], ids=["demo", "example"])
def test_no_secret_value_is_inlined(path: Path) -> None:
    """Every credential must be a `${{ secrets.* }}` reference, never a literal."""
    text = path.read_text(encoding="utf-8")
    for var in _CREDENTIAL_VARS:
        assert f"secrets.{var}" in text, f"{path.name} never references secrets.{var}"


@pytest.mark.fab_test
def test_the_guide_and_both_workflows_name_the_same_credential_variables() -> None:
    """A renamed variable in one place must break this test, not a reader's
    first run against a workspace they can't reach yet."""
    guide_text = _GUIDE.read_text(encoding="utf-8")
    demo_text = _DEMO.read_text(encoding="utf-8")
    example_text = _EXAMPLE.read_text(encoding="utf-8")

    for var in _CREDENTIAL_VARS:
        assert var in guide_text, f"docs/PLAYWRIGHT-CI.md never mentions {var}"
        assert var in demo_text, f"playwright-demo.yml never reads {var}"
        assert var in example_text, f"playwright-live.yml never reads {var}"


@pytest.mark.fab_test
def test_the_demo_workflow_only_triggers_by_hand() -> None:
    """A later edit adding `push`/`pull_request` here would silently expose
    this repository's one credential-carrying workflow to fork PRs."""
    triggers = _triggers(_load(_DEMO))

    assert set(triggers) == {"workflow_dispatch"}, triggers


@pytest.mark.fab_test
def test_the_demo_workflow_names_a_protected_environment() -> None:
    """`environment:` is what scopes the secrets and (if configured) gates
    the run on required reviewers -- a job with none of that is not protected."""
    data = _load(_DEMO)
    ((_job_id, job),) = data["jobs"].items()

    assert job.get("environment"), "playwright-demo.yml's job names no environment"
