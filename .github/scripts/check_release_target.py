"""Refuse to publish the wrong thing to production PyPI (TestPyPI Release §4).

A publish cannot be undone: PyPI refuses a second upload of a version, so a
wrong file is the file everyone installs, forever. Two mistakes this catches.

A dev release reaching production. The tag filter used to be
`v[0-9]+.[0-9]+.[0-9]+*`, whose trailing glob matches `v1.0.0.0.dev1` --
the first rehearsal tag would have gone to PyPI. Tightening the glob is not
enough on its own, because the version that matters is the one in the built
wheel, not the one someone typed into a tag. This reads the wheel.

Alpha, beta, and release-candidate versions (`1.8.1b1`) are allowed: PyPI
hides them from a bare `pip install` and serves them to `--pre`, which is
what a public beta needs. A dev release (`.devN`, including `1.8.1b1.dev1`)
is a rehearsal build and never belongs on the production index.

A tag that disagrees with the wheel. `v1.0.0` on a tree that builds 1.0.1
publishes a version nobody reviewed under a name nobody expects, and the
release notes describe the wrong commit range.

Dev releases belong on TestPyPI: see .github/workflows/publish-testpypi.yml.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

from packaging.utils import parse_wheel_filename
from packaging.version import Version


def release_problem(version: str, tag: str) -> str | None:
    """Return why ``version`` must not be published under ``tag``, or None.

    ``tag`` is the git tag the run was triggered by, or empty for a run with
    no tag (a manual dispatch), where there is nothing to disagree with.
    """
    if Version(version).is_devrelease:
        return (
            f"{version} is a dev release; publish it to TestPyPI instead "
            "(.github/workflows/publish-testpypi.yml)"
        )
    if tag and tag != f"v{version}":
        return f"tag {tag} does not match the built version {version} (expected v{version})"
    return None


def built_version(dist_dir: Path) -> str:
    """Return the version of the wheel in ``dist_dir``.

    Read from the wheel rather than the source tree: the artifact about to be
    uploaded is the only version that matters here.
    """
    wheels = sorted(glob.glob(str(dist_dir / "*.whl")))
    if not wheels:
        raise FileNotFoundError(f"no wheel found in {dist_dir}")
    if len(wheels) > 1:
        raise RuntimeError(f"expected one wheel in {dist_dir}, found {len(wheels)}: {wheels}")
    _, version, _, _ = parse_wheel_filename(Path(wheels[0]).name)
    return str(version)


def main() -> int:
    version = built_version(Path("dist"))
    # The rehearsal workflow needs the same answer to pin its verification
    # install, and asking twice in two ways is how the two drift apart.
    # Prints the bare version and nothing else, for command substitution.
    if "--print-version" in sys.argv[1:]:
        print(version)
        return 0
    # For the GitHub Release's `prerelease` flag: lowercase, so the workflow
    # can compare it to the string 'true'.
    if "--print-prerelease" in sys.argv[1:]:
        print(str(Version(version).is_prerelease).lower())
        return 0

    tag = os.environ.get("GITHUB_REF_NAME", "") if os.environ.get("GITHUB_REF_TYPE") == "tag" else ""
    problem = release_problem(version, tag)
    if problem:
        print(f"::error::{problem}")
        return 1
    print(f"publishing {version} to production PyPI" + (f" from tag {tag}" if tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
