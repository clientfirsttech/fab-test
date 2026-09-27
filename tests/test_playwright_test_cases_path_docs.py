"""Guard: every doc naming the Playwright test-cases path nests it under the report.

Scope
-----
`fab-test-results/playwright/<report>/test-cases/<case>/` is the real,
disk-verified layout -- a dataset-targeted or batch run resolves more than
one report, each with its own `test-cases/` directory, so there is no
top-level `fab-test-results/playwright/test-cases/` at all. A flat
`playwright/test-cases/**` glob (found live in `docs/QUICK-VALIDATION.md`,
`docs/examples/github-actions/playwright-live.yml`, README.md, and the
fab-test skill's `references/flags.md`, all copy-pasted from one another)
uploads nothing and links to files that were never included -- caught while
building the example workflow's own upload step against a real workspace
(Playwright CI Guide epic, 2026-09-27).

    pytest -m fab_test tests/test_playwright_test_cases_path_docs.py
"""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

_FLAT_PATTERN = "playwright/test-cases"
_DOCS = {
    "docs/QUICK-VALIDATION.md",
    "docs/examples/github-actions/playwright-live.yml",
    "README.md",
    ".github/skills/fab-test/references/flags.md",
    "src/fab_test/skill/references/flags.md",
}


@pytest.mark.fab_test
@pytest.mark.parametrize("relative_path", sorted(_DOCS))
def test_no_doc_names_the_flat_test_cases_path(relative_path: str) -> None:
    """None of these may say `playwright/test-cases/` -- only
    `playwright/<report>/test-cases/` exists on disk."""
    text = (_ROOT / relative_path).read_text(encoding="utf-8")
    assert _FLAT_PATTERN not in text, (
        f"{relative_path} names the flat 'playwright/test-cases' path, which does not exist -- "
        "every report gets its own test-cases/ directory (playwright/<report>/test-cases/)."
    )


@pytest.mark.fab_test
def test_the_example_workflow_uploads_the_nested_path() -> None:
    """The one place this actually has to be *correct*, not just absent:
    the upload step's glob must match the real nested layout."""
    workflow = (_ROOT / "docs/examples/github-actions/playwright-live.yml").read_text(encoding="utf-8")
    assert "fab-test-results/playwright/**/test-cases/**" in workflow
