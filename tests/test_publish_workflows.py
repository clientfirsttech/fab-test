"""Policy tests for the publish workflows (TestPyPI Release §4).

Scope
-----
Publishing is the one action this repository cannot take back: an index
refuses a second upload of a version, so a wrong file reaches everyone who
installs that release forever.

Two hazards these tests exist for. The tag filter was
`v[0-9]+.[0-9]+.[0-9]+*` -- the trailing glob matches `v1.0.0.0.dev1`, so
the first rehearsal tag would have gone to production PyPI. And the `pypi`
environment named project `fabric-ci-cd-dataops`, which is not the
distribution this repository builds.

The guards themselves live in `.github/scripts/` as importable functions
rather than inline `run:` blocks, so their logic is tested here rather than
discovered during a release.

    pytest -m fab_test tests/test_publish_workflows.py
"""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _ROOT / ".github" / "workflows"
_SCRIPTS = _ROOT / ".github" / "scripts"

_PRODUCTION = "publish.yml"
_REHEARSAL = "publish-testpypi.yml"


def _workflow(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _load_script(filename: str):
    """Import a release guard from .github/scripts, which is not a package."""
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _steps(workflow: dict) -> list[dict]:
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def _step_index(workflow: dict, needle: str) -> int:
    """Return the position of the first step mentioning ``needle``, or -1."""
    for i, step in enumerate(_steps(workflow)):
        if needle in str(step.get("run", "")) or needle in str(step.get("uses", "")):
            return i
    return -1


def _triggers(workflow: dict) -> dict:
    """Return the `on:` block. PyYAML reads a bare `on` key as True."""
    return workflow.get("on", workflow.get(True))


# --------------------------------------------------------------------------
# Where each workflow publishes
# --------------------------------------------------------------------------


@pytest.mark.fab_test
def test_the_rehearsal_workflow_exists_and_targets_testpypi():
    """A release has to be rehearsable somewhere that is not production."""
    workflow = _workflow(_REHEARSAL)
    urls = [
        step.get("with", {}).get("repository-url", "")
        for step in _steps(workflow)
        if "pypi-publish" in str(step.get("uses", ""))
    ]

    assert urls, "no pypa/gh-action-pypi-publish step found"
    for url in urls:
        assert "test.pypi.org" in url, url


@pytest.mark.fab_test
def test_the_rehearsal_workflow_runs_without_a_tag():
    """A release must be rehearsable without moving a tag to try again."""
    triggers = _triggers(_workflow(_REHEARSAL))

    assert "workflow_dispatch" in triggers, sorted(triggers)


@pytest.mark.fab_test
def test_the_rehearsal_workflow_tolerates_an_already_published_version():
    """TestPyPI keeps every rehearsal, so re-running one must not fail the job."""
    workflow = _workflow(_REHEARSAL)
    publish = [s for s in _steps(workflow) if "pypi-publish" in str(s.get("uses", ""))]

    assert publish, "no publish step found"
    for step in publish:
        assert step.get("with", {}).get("skip-existing") is True, step.get("with")


@pytest.mark.fab_test
def test_production_publishes_only_to_pypi():
    """The production workflow must never point at a rehearsal index."""
    for step in _steps(_workflow(_PRODUCTION)):
        url = step.get("with", {}).get("repository-url", "")
        if url:
            assert "test.pypi.org" not in url, url


@pytest.mark.fab_test
def test_production_environment_names_the_distribution_this_repo_builds():
    """Trusted publishing resolves by distribution name, not repository name."""
    environments = [job.get("environment") for job in _workflow(_PRODUCTION)["jobs"].values()]
    urls = [env.get("url", "") for env in environments if isinstance(env, dict)]

    assert urls, "no environment url declared"
    for url in urls:
        assert url.rstrip("/").endswith("/cft-fab-test"), url


@pytest.mark.fab_test
def test_no_production_tag_pattern_ends_in_a_glob():
    """The original bug, stated as a rule.

    `v[0-9]+.[0-9]+.[0-9]+*` looks like it means "a three-part version" and
    actually means "a three-part version followed by anything" -- which is
    every pre-release spelling there is.
    """
    patterns = _triggers(_workflow(_PRODUCTION))["push"]["tags"]

    assert patterns, "production workflow has no tag filter"
    for pattern in patterns:
        assert not pattern.endswith("*"), f"{pattern} matches every pre-release suffix"


@pytest.mark.fab_test
def test_production_accepts_this_project_s_release_shape():
    """A four-component version is this project's scheme, not a typo.

    1.0.0.0.dev1 leads to 1.0.0.0, so a filter that only accepted three
    components would never fire for the release it exists to publish.
    """
    patterns = _triggers(_workflow(_PRODUCTION))["push"]["tags"]

    assert any(pattern.count(".") == 3 for pattern in patterns), patterns


@pytest.mark.fab_test
def test_production_refuses_a_dev_release_before_it_uploads():
    """Order matters: a guard that runs after the upload guards nothing."""
    workflow = _workflow(_PRODUCTION)
    guard = _step_index(workflow, "check_release_target.py")
    publish = _step_index(workflow, "pypi-publish")

    assert guard >= 0, "production workflow does not run the release guard"
    assert publish >= 0, "production workflow has no publish step"
    assert guard < publish, f"guard at step {guard} runs after publish at {publish}"


@pytest.mark.fab_test
@pytest.mark.parametrize("workflow_name", [_PRODUCTION, _REHEARSAL])
def test_metadata_is_checked_before_anything_is_uploaded(workflow_name):
    """`twine check --strict` after the upload reports on a spent version.

    An index refuses a second upload of a version, so a README that fails to
    render is not fixable in place -- the release has to be burned.
    """
    workflow = _workflow(workflow_name)
    check = _step_index(workflow, "twine check")
    publish = _step_index(workflow, "pypi-publish")

    assert check >= 0, f"{workflow_name} does not run twine check"
    assert check < publish, f"twine check at {check} runs after publish at {publish}"


@pytest.mark.fab_test
@pytest.mark.parametrize("workflow_name", [_PRODUCTION, _REHEARSAL, "build.yml"])
def test_every_workflow_that_builds_a_dist_checks_what_it_built(workflow_name):
    """The wheel shipped no metadata for months because nothing looked inside it."""
    workflow = _workflow(workflow_name)
    builds = _step_index(workflow, "python -m build")
    checks = _step_index(workflow, "check_wheel_contents.py")

    assert builds >= 0, f"{workflow_name} does not build a dist"
    assert checks > builds, f"{workflow_name} builds at {builds} but checks at {checks}"


# --------------------------------------------------------------------------
# The guards themselves
# --------------------------------------------------------------------------


@pytest.mark.fab_test
@pytest.mark.parametrize("version", ["1.0.0.0.dev1", "1.8.1.dev3", "1.8.1b1.dev1", "2.0.0rc1.dev2"])
def test_a_dev_release_is_refused_for_production(version):
    """A dev release is a rehearsal build, including a dev build of a beta."""
    guard = _load_script("check_release_target.py")

    problem = guard.release_problem(version, tag=f"v{version}")

    assert problem is not None
    assert "dev release" in problem.lower(), problem


@pytest.mark.fab_test
@pytest.mark.parametrize("version", ["1.8.1b1", "2.0.0a1", "1.0.1rc1", "1.0.0.0b2"])
def test_a_public_prerelease_is_allowed_for_production(version):
    """Alpha, beta, and rc go to PyPI, where only `pip install --pre` sees them."""
    guard = _load_script("check_release_target.py")

    assert guard.release_problem(version, tag=f"v{version}") is None


def _tag_matches(pattern: str, tag: str) -> bool:
    """Match ``tag`` against a GitHub Actions tag filter pattern.

    Only the syntax these workflows use: `*` (anything but `/`), `+` (one or
    more of the preceding character or class), and `[...]` classes; every
    other character is literal -- including `.`.
    """
    regex, i = "", 0
    while i < len(pattern):
        char = pattern[i]
        if char == "[":
            end = pattern.index("]", i)
            regex += pattern[i : end + 1]
            i = end + 1
            continue
        regex += {"*": "[^/]*", "+": "+"}.get(char, re.escape(char))
        i += 1
    return re.fullmatch(regex, tag) is not None


@pytest.mark.fab_test
@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v1.8.1", _PRODUCTION),
        ("v1.0.0.0", _PRODUCTION),
        ("v1.8.1b1", _PRODUCTION),
        ("v2.0.0a3", _PRODUCTION),
        ("v1.8.1rc2", _PRODUCTION),
        ("v1.0.0.0b1", _PRODUCTION),
        ("v1.0.0.0.dev1", _REHEARSAL),
        ("v1.8.1.dev4", _REHEARSAL),
        ("v1.8.1b1.dev1", _REHEARSAL),
    ],
)
def test_every_tag_shape_reaches_exactly_one_index(tag, expected):
    """One tag, one index: a tag both workflows fire on publishes twice."""
    firing = [
        name
        for name in (_PRODUCTION, _REHEARSAL)
        if any(_tag_matches(p, tag) for p in _triggers(_workflow(name))["push"]["tags"])
    ]

    assert firing == [expected], f"{tag} fires {firing}"


@pytest.mark.fab_test
def test_a_prerelease_is_not_marked_the_latest_github_release():
    """A beta that becomes "Latest release" is what the Releases page recommends."""
    release = [s for s in _steps(_workflow(_PRODUCTION)) if "action-gh-release" in str(s.get("uses", ""))]

    assert release, "no GitHub Release step found"
    assert "prerelease" in str(release[0].get("with", {}).get("prerelease", "")), release[0]


@pytest.mark.fab_test
def test_a_tag_that_disagrees_with_the_built_version_is_refused():
    """A stale tag publishes a version nobody reviewed under a name nobody expects."""
    guard = _load_script("check_release_target.py")

    problem = guard.release_problem("1.0.1", tag="v1.0.0")

    assert problem is not None
    assert "1.0.0" in problem and "1.0.1" in problem, problem


@pytest.mark.fab_test
def test_a_final_release_whose_tag_matches_is_allowed():
    """The one case that should publish."""
    guard = _load_script("check_release_target.py")

    assert guard.release_problem("1.0.1", tag="v1.0.1") is None


@pytest.mark.fab_test
def test_a_final_release_is_allowed_when_there_is_no_tag():
    """A dispatch-driven production run has no tag to compare against."""
    guard = _load_script("check_release_target.py")

    assert guard.release_problem("1.0.1", tag="") is None


@pytest.mark.fab_test
def test_a_wheel_missing_required_metadata_is_refused():
    """The exact failure that shipped: a wheel with code and no rulesets."""
    checker = _load_script("check_wheel_contents.py")
    names = [n for n in checker.REQUIRED if "rules" not in n]

    problems = checker.wheel_problems(names)

    assert any("BPARules.json" in p for p in problems), problems


@pytest.mark.fab_test
def test_a_wheel_carrying_repository_internals_is_refused():
    """Tests, docs, and downloaded tools have no business in a wheel."""
    checker = _load_script("check_wheel_contents.py")

    problems = checker.wheel_problems([*checker.REQUIRED, "tests/test_fab_test.py"])

    assert any("tests/" in p for p in problems), problems


@pytest.mark.fab_test
def test_a_wheel_with_everything_required_and_nothing_forbidden_passes():
    """The shape the build actually produces."""
    checker = _load_script("check_wheel_contents.py")
    names = [*checker.REQUIRED, "fab_test/scripts/fab_test.py"]

    assert checker.wheel_problems(names) == []


@pytest.mark.fab_test
def test_the_wheel_carries_the_playwright_render_spec() -> None:
    """The exact failure this closes: a wheel missing the spec `invoke_playwright.py`
    points pytest at fails every real Playwright run outside a checkout
    (Playwright CI Guide epic, Render Spec Packaging task)."""
    checker = _load_script("check_wheel_contents.py")

    assert any("render_spec.py" in r for r in checker.REQUIRED), checker.REQUIRED

    names = [n for n in checker.REQUIRED if "render_spec.py" not in n]
    problems = checker.wheel_problems(names)

    assert any("render_spec.py" in p for p in problems), problems
