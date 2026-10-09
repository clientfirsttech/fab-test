"""Playwright progress lines carry `::notice::`/`::warning::` only in CI (Standalone bug).

`fab-test` hands a wrapper its terminal under `--format text`, so the
GitHub Actions prefix on these lines reached a laptop verbatim -- the same
defect Terse CLI Output fixed for tool-bootstrap notes. Both Playwright
modules now share one `log` that keeps the prefix only where CI renders it.
"""

import pytest

from fab_test.scripts import invoke_playwright
from fab_test.scripts.playwright_validation import discovery

pytestmark = pytest.mark.playwright


@pytest.fixture
def local(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)


@pytest.mark.parametrize("prefix", ["::notice::", "::warning::"])
def test_given_a_laptop_should_print_the_line_without_the_workflow_prefix(local, capsys, prefix):
    discovery.log(f"{prefix}Impact manifest is empty; skipping Playwright validation.")
    assert capsys.readouterr().out == "Impact manifest is empty; skipping Playwright validation.\n"


@pytest.mark.parametrize("variable", ["GITHUB_ACTIONS", "CI"])
def test_given_ci_should_keep_the_workflow_prefix(local, capsys, monkeypatch, variable):
    monkeypatch.setenv(variable, "true")
    discovery.log("::notice::No Playwright test cases generated")
    assert capsys.readouterr().out == "::notice::No Playwright test cases generated\n"


def test_given_a_plain_line_should_print_it_unchanged(local, capsys):
    discovery.log("📐 Matrix: 2 page(s)")
    assert capsys.readouterr().out == "📐 Matrix: 2 page(s)\n"


def test_the_wrapper_and_discovery_share_one_log():
    assert invoke_playwright.log is discovery.log
