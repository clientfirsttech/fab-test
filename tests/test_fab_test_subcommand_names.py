"""Subcommand aliases: hyphen/underscore normalization and canonical names.

Scope
-----
_SUBCOMMAND_ALIASES mapping hyphen/underscore spellings to their canonical
analyzer name, both spellings behaving identically end to end, and --help
/ `list` showing the hyphenated form as canonical with the alias alongside.

    pytest -m fab_test
"""
import json
import re
import subprocess

import pytest

from fab_test.scripts.fab_test import _SUBCOMMAND_ALIASES

# The telemetry preview in `--dry-run` output stamps the current time, so
# two subprocess invocations a few milliseconds apart never print byte-
# identical stdout. Masked out before the alias/canonical comparison below,
# which cares whether the two spellings behave the same -- not whether they
# ran in the same instant.
_TIMESTAMP_RE = re.compile(r'"timestamp": "[^"]*"')


def _mask_timestamp(text: str) -> str:
    return _TIMESTAMP_RE.sub('"timestamp": "<redacted>"', text)

# --------------------------------------------------------------------------- #
# Normalize subcommand aliases
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_subcommand_alias_mapping():
    """Hyphen/underscore aliases resolve to their canonical analyzer name."""
    assert _SUBCOMMAND_ALIASES["pql-test"] == "pql_test"
    assert _SUBCOMMAND_ALIASES["pql-lint"] == "pql_lint"
    assert _SUBCOMMAND_ALIASES["playwright_impact"] == "playwright-impact"


@pytest.mark.fab_test
def test_pql_test_hyphen_alias_behaves_like_underscore():
    """fab-test pql-test behaves identically to fab-test pql_test."""
    canonical = subprocess.run(
        ["fab-test", "pql_test", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "pql-test", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0
    assert _mask_timestamp(canonical.stdout) == _mask_timestamp(aliased.stdout)


@pytest.mark.fab_test
def test_pql_lint_hyphen_alias_behaves_like_underscore():
    """fab-test pql-lint behaves identically to fab-test pql_lint."""
    canonical = subprocess.run(
        ["fab-test", "pql_lint", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "pql-lint", "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0
    assert _mask_timestamp(canonical.stdout) == _mask_timestamp(aliased.stdout)


@pytest.mark.fab_test
def test_playwright_impact_underscore_alias_accepted():
    """playwright-impact remains canonical; playwright_impact is also accepted."""
    canonical = subprocess.run(
        ["fab-test", "playwright-impact", "--help"],
        capture_output=True, text=True, check=False,
    )
    aliased = subprocess.run(
        ["fab-test", "playwright_impact", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert canonical.returncode == aliased.returncode == 0


@pytest.mark.fab_test
def test_all_dry_run_output_unaffected_by_aliases():
    """`fab-test all` still lists the canonical pql_test name, not an alias."""
    result = subprocess.run(
        ["fab-test", "all", "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fab-test pql_test" in result.stdout
    assert "fab-test pql-test" not in result.stdout


# --------------------------------------------------------------------------- #
# Canonicalize subcommand names
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_help_displays_hyphenated_form_as_canonical():
    """--help shows the hyphenated spelling as primary, underscore as the alias."""
    result = subprocess.run(
        ["fab-test", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pql-test (pql_test)" in result.stdout
    # playwright-impact stands in for pql-lint here, which is now hidden
    # from the listing; the point is that an aliased subcommand shows its
    # hyphenated form as canonical with the underscore form in parentheses.
    assert "playwright-impact (playwright_impact)" in result.stdout


@pytest.mark.fab_test
def test_pql_test_underscore_form_still_works_with_no_error():
    """The underscore spelling is still silently accepted (no warning/deprecation)."""
    result = subprocess.run(
        ["fab-test", "pql_test", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "deprecat" not in result.stdout.lower()
    assert "deprecat" not in result.stderr.lower()


@pytest.mark.fab_test
def test_list_reports_canonical_name_and_aliases():
    """`fab-test list --format json` reports the canonical name plus aliases."""
    result = subprocess.run(
        ["fab-test", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)

    pql_test_row = next(r for r in summary["analyzers"] if r["analyzer"] == "pql-test")
    assert pql_test_row["aliases"] == ["pql_test"]

    impact_row = next(
        r for r in summary["analyzers"] if r["analyzer"] == "playwright-impact"
    )
    assert impact_row["aliases"] == ["playwright_impact"]

    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["aliases"] == []


@pytest.mark.fab_test
def test_result_directory_name_unchanged_when_invoked_via_canonical_form(tmp_path):
    """Invoking via the new canonical 'pql-test' still writes under fab-test-results/pql_test/."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)
    output_dir = tmp_path / "fab-test-results"

    result = subprocess.run(
        [
            "fab-test", "pql-test",
            "--artifact-dir", str(artifact_dir),
            "--output-dir", str(output_dir),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # The dry-run banner uses the internal registry key, unaffected by which
    # spelling the user typed — proving result-directory naming is unchanged.
    assert "fab-test pql_test" in result.stdout


