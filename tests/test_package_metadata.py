"""Contract tests for the distribution's own metadata (TestPyPI Release §6).

Scope
-----
The project page is the first thing a reader sees, and every URL on it was
wrong: `[project.urls]` pointed at `kerski/fabric-ci-cd-dataops` while the
repository is `kerski/fab-test`, and twelve of sixteen README links were
repository-relative, so they resolved against the index host and 404'd.

Trusted publishing and the project page both key off this metadata, so a
mistake here is not cosmetic -- it is the difference between a publish that
authenticates and one that does not.

Reads `pyproject.toml` and `README.md`, so it is fast and always passes on
any machine.

    pytest -m fab_test tests/test_package_metadata.py
"""

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_REPOSITORY = "kerski/fab-test"
_STALE_REPOSITORY = "kerski/fabric-ci-cd-dataops"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readme() -> str:
    return (_ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.fab_test
def test_no_project_url_points_at_the_old_repository_name(pyproject):
    """Every link on the project page has to actually resolve."""
    urls = pyproject["project"]["urls"]

    stale = {name: url for name, url in urls.items() if _STALE_REPOSITORY in url}
    assert not stale, stale


@pytest.mark.fab_test
def test_the_repository_url_names_this_repository(pyproject):
    """Trusted publishing is configured against owner/repo; they must agree."""
    assert _REPOSITORY in pyproject["project"]["urls"]["Repository"]


@pytest.mark.fab_test
def test_the_license_is_an_spdx_expression(pyproject):
    """setuptools>=77 deprecates the `{ text = ... }` table form.

    A deprecation that only warns at build time is one nobody sees until it
    becomes an error mid-release.
    """
    license_field = pyproject["project"]["license"]

    assert isinstance(license_field, str), f"expected an SPDX string, got {type(license_field).__name__}"
    assert license_field == "MIT", license_field


@pytest.mark.fab_test
def test_no_license_classifier_duplicates_the_license_field(pyproject):
    """PEP 639 retires the `License ::` classifiers in favour of the expression.

    Declaring both is what makes the build warn.
    """
    classifiers = pyproject["project"]["classifiers"]

    assert not [c for c in classifiers if c.startswith("License ::")], classifiers


@pytest.mark.fab_test
def test_the_build_backend_supports_the_license_expression(pyproject):
    """An SPDX expression on setuptools<77 is a build error, not a warning."""
    requires = pyproject["build-system"]["requires"]

    setuptools_pin = next((r for r in requires if r.startswith("setuptools")), None)
    assert setuptools_pin is not None, requires
    minimum = int(re.search(r">=(\d+)", setuptools_pin).group(1))
    assert minimum >= 77, setuptools_pin


@pytest.mark.fab_test
def test_every_readme_link_resolves_off_the_project_page(readme):
    """README is the long description; relative links resolve against the index.

    On PyPI a `docs/QUICKSTART-LOCAL.md` href becomes
    `https://pypi.org/project/fab-test/docs/QUICKSTART-LOCAL.md`, which is a
    404 for the reader most likely to be following it -- someone who just
    found the package and has no checkout.
    """
    links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", readme)
    relative = [href for href in links if not href.startswith(("http://", "https://", "#"))]

    assert relative == [], relative


@pytest.mark.fab_test
def test_the_readme_does_not_link_the_old_repository_name(readme):
    """A renamed repository redirects today and stops redirecting eventually."""
    assert _STALE_REPOSITORY not in readme


@pytest.mark.fab_test
def test_every_project_url_naming_a_repository_file_names_one_that_exists(pyproject):
    """A /blob/main/ URL is a promise about a path in this repository.

    Changelog pointed at `activity-log.md`, which does not exist -- a 404 on
    the project page, reachable in one click from the sidebar, and invisible
    to anyone who never left the checkout.
    """
    prefix = f"https://github.com/{_REPOSITORY}/blob/main/"
    missing = {
        name: url[len(prefix) :]
        for name, url in pyproject["project"]["urls"].items()
        if url.startswith(prefix) and not (_ROOT / url[len(prefix) :]).exists()
    }

    assert not missing, missing


@pytest.mark.fab_test
def test_every_readme_link_into_this_repository_names_something_that_exists(readme):
    """Absolute links can rot too; making them absolute did not make them true."""
    prefix = f"https://github.com/{_REPOSITORY}/"
    missing = []
    for href in re.findall(r"\[[^\]]*\]\(([^)]+)\)", readme):
        if not href.startswith(prefix):
            continue
        rest = href[len(prefix) :]
        for kind in ("blob/main/", "tree/main/"):
            if rest.startswith(kind):
                target = rest[len(kind) :].split("#")[0]
                if target and not (_ROOT / target).exists():
                    missing.append(target)

    assert missing == [], missing
