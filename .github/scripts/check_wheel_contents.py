"""Assert what the wheel carries, in both directions (TestPyPI Release §2).

The wheel shipped no metadata at all for months and nothing noticed. `bpa`
and `pbir` are handed a rules file path and `doctor` reads analyzers.json for
the install URL of a missing tool, so a wheel without them resolves rules to
a path that exists only in a checkout of this repository -- which is exactly
what a `pip install fab-test` consumer does not have.

It survived because a `package-data` glob that matches no file is not a build
error. `agents/*` and `skills/*/*` were declared against directories that do
not exist here and shipped nothing, silently, while the README told readers
to find them after install. So the built artifact is the only honest place to
assert this, and it is asserted positively -- an exclusion list alone cannot
catch a missing file.

tests/test_publish_workflows.py exercises wheel_problems() directly and
asserts every workflow that builds a dist runs this before doing anything
with it.
"""

from __future__ import annotations

import glob
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

# Without these the analyzers cannot run at all outside a checkout.
REQUIRED = [
    "fab_test/metadata/analyzers.json",
    "fab_test/metadata/artifact-map.json",
    "fab_test/metadata/rules/BPARules.json",
    "fab_test/metadata/rules/pbi-inspector-custom-rules.json",
    "fab_test/schemas/fab-test.schema.json",
    "fab_test/scripts/playwright_validation/render_spec.py",
    "fab_test/skill/SKILL.md",
    "fab_test/skill/references/configuration.md",
    "fab_test/skill/references/credentials.md",
    "fab_test/skill/references/flags.md",
    "fab_test/skill/references/operations.md",
    "fab_test/skill/references/reports.md",
    "fab_test/skill/references/source-files.md",
    "fab_test/skill/references/targeting-and-discovery.md",
]

# Repository internals, downloaded tools, and run output. None of it belongs
# in a distribution, and some of it (.env) must never leave this machine.
FORBIDDEN = (
    ".github/",
    ".fabric/",
    "docs/",
    "tests/",
    "TabularEditor/",
    "PBIR-Inspector/",
    "analyzer-results/",  # pre-1.0.0.0 name; kept as a permanent guard
    "fab-test-results/",
    ".venv/",
    ".env",
    "bandit-report",
    "bpa-results",
    "coverage.json",
)


def wheel_problems(names: Iterable[str]) -> list[str]:
    """Return every reason the wheel holding ``names`` must not ship."""
    present = set(names)
    problems = [f"missing from wheel: {r}" for r in REQUIRED if r not in present]
    problems += [
        f"must not ship: {n}" for n in sorted(present) if any(f in n for f in FORBIDDEN)
    ]
    return problems


def main() -> int:
    wheels = sorted(glob.glob("dist/*.whl"))
    if not wheels:
        print("::error::no wheel found in dist/")
        return 1

    failed = False
    for wheel in wheels:
        problems = wheel_problems(zipfile.ZipFile(wheel).namelist())
        for problem in problems:
            print(f"::error::{Path(wheel).name}: {problem}")
        if problems:
            failed = True
        else:
            print(f"{Path(wheel).name}: carries every required file, nothing forbidden")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
