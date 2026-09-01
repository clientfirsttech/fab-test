"""pyproject.toml pins pql-test once; four documents restate that pin in prose.

Nothing fails today if a bump updates the pin and misses one of them, so the
version quietly disagrees with itself across README.md, docs/RELEASE.md,
.github/skills/fab-test/SKILL.md, and .github/workflows/publish-testpypi.yml.
See the Tool Version Currency epic's "Stop the pin from being duplicated"
task.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT_TOML = _ROOT / "pyproject.toml"

# Each pattern's single capture group is the version it claims is the pin.
# Two shapes appear in the wild: the literal requirement (`pql-test==X`,
# read the same way in README.md, docs/RELEASE.md, and SKILL.md) and the
# workflow comment's "vs the X we require" phrasing -- both name the pin,
# neither names the stale TestPyPI number sitting next to it in the same
# sentence.
_PIN_CLAIM_PATTERNS = (
    re.compile(r"pql-test==([0-9][\w.]*)"),
    re.compile(r"the ([0-9][\w.]*) we require"),
)

_DOCUMENTED_CALLERS = (
    Path("README.md"),
    Path("docs/RELEASE.md"),
    Path(".github/skills/fab-test/SKILL.md"),
    Path(".github/workflows/publish-testpypi.yml"),
)


def _pinned_pql_test_version() -> str:
    data = tomllib.loads(_PYPROJECT_TOML.read_text(encoding="utf-8"))
    prefix = "pql-test=="
    for dep in data["project"]["dependencies"]:
        if dep.startswith(prefix):
            return dep[len(prefix):]
    raise AssertionError("pyproject.toml no longer pins pql-test")


def _claimed_versions(relative_path: Path) -> list[tuple[Path, int, str]]:
    text = (_ROOT / relative_path).read_text(encoding="utf-8")
    found = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern in _PIN_CLAIM_PATTERNS:
            found.extend((relative_path, line_no, match.group(1)) for match in pattern.finditer(line))
    return found


def test_every_documented_caller_names_the_same_pql_test_pin():
    """A stale mention should name itself, not just fail a lone assertion."""
    pinned = _pinned_pql_test_version()

    disagreements = []
    for relative_path in _DOCUMENTED_CALLERS:
        claims = _claimed_versions(relative_path)
        assert claims, f"{relative_path} no longer mentions the pql-test pin at all"
        for path, line_no, claimed in claims:
            if claimed != pinned:
                disagreements.append(f"{path}:{line_no} says {claimed}, pyproject.toml pins {pinned}")

    assert disagreements == [], "\n".join(disagreements)
