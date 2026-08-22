"""Contract tests for hidden analyzers.

Scope
-----
`pql_lint` is hidden from the advertised CLI surface for now: it does not
appear in `--help`, `fab-test list`, or the default `doctor` report. It
stays fully invocable, because the backward-compatibility constraint in
vision.md says existing commands keep working — hiding is a visibility
change, not a removal.

Always passes on any machine: every check is help text, discovery output,
or a dry run.
"""

import json
import os
import subprocess
import sys

import pytest

from fabric_ci_cd_dataops.scripts.fab_test_registry import (
    ANALYZER_REGISTRY,
    HIDDEN_ANALYZERS,
    visible_analyzers,
)


@pytest.fixture
def artifact_tree(tmp_path):
    (tmp_path / "Sales.SemanticModel").mkdir()
    return tmp_path


def _run_cli(*argv):
    return subprocess.run(
        [sys.executable, "-m", "fabric_ci_cd_dataops.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
        check=False,
    )


# --------------------------------------------------------------------------- #
# The declaration
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_hidden_analyzers_are_a_subset_of_the_registry():
    """A hidden name must be a real analyzer, or the hiding silently does nothing."""
    assert set(ANALYZER_REGISTRY) >= HIDDEN_ANALYZERS


@pytest.mark.fab_test
def test_pql_lint_is_hidden_but_still_registered():
    """Hidden is a visibility state, not a deletion."""
    assert "pql_lint" in HIDDEN_ANALYZERS
    assert "pql_lint" in ANALYZER_REGISTRY


@pytest.mark.fab_test
def test_visible_analyzers_excludes_the_hidden_ones():
    visible = set(visible_analyzers())

    assert "pql_lint" not in visible
    assert {"bpa", "pbir", "pql_test"} <= visible


# --------------------------------------------------------------------------- #
# Hidden from the advertised surface
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_top_level_help_does_not_list_pql_lint_as_a_subcommand():
    """It must not appear as its own entry in the subcommand listing.

    Scoped to the listing rather than the whole of stdout: `fab-test local`
    genuinely runs pql-lint and its help text says so, which is accurate
    and should not be papered over. See the note in the epic about whether
    `local` should keep including it.
    """
    result = _run_cli("--help")

    assert result.returncode == 0, result.stderr
    listing_entries = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("    ") and not line.startswith("     ")
    ]
    assert not any(entry.startswith("pql-lint") for entry in listing_entries), (
        f"pql-lint still listed as a subcommand: {listing_entries}"
    )
    assert any(entry.startswith("bpa") for entry in listing_entries), "sanity check"
    assert "==SUPPRESS==" not in result.stdout


@pytest.mark.fab_test
def test_list_omits_pql_lint(artifact_tree):
    result = _run_cli("list", "--artifact-dir", str(artifact_tree), "--format", "json")

    assert result.returncode == 0, result.stderr
    names = {row["analyzer"] for row in json.loads(result.stdout)["analyzers"]}
    assert "pql-lint" not in names
    assert "bpa" in names


@pytest.mark.fab_test
def test_doctor_omits_pql_lint_by_default():
    result = _run_cli("doctor", "--format", "json")

    assert result.returncode in (0, 1), result.stderr
    names = {row["analyzer"] for row in json.loads(result.stdout)["analyzers"]}
    assert "pql_lint" not in names


# --------------------------------------------------------------------------- #
# Still fully usable
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_pql_lint_still_runs_when_invoked_directly(artifact_tree):
    """Backward compatibility: an existing script calling it keeps working."""
    result = _run_cli(
        "pql-lint", "--artifact-dir", str(artifact_tree), "--dry-run"
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.fab_test
def test_pql_lint_underscore_alias_still_works(artifact_tree):
    result = _run_cli("pql_lint", "--artifact-dir", str(artifact_tree), "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.fab_test
def test_doctor_reports_pql_lint_when_asked_for_explicitly():
    """Hidden from the list, not from a direct question."""
    result = _run_cli("doctor", "--analyzer", "pql_lint", "--format", "json")

    assert result.returncode in (0, 1), result.stderr
    rows = json.loads(result.stdout)["analyzers"]
    assert [r["analyzer"] for r in rows] == ["pql_lint"]


@pytest.mark.fab_test
def test_explain_still_works_for_a_hidden_analyzer(artifact_tree):
    result = _run_cli(
        "explain", "pql_lint", "--artifact-dir", str(artifact_tree), "--format", "json"
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["analyzer"] == "pql_lint"


@pytest.mark.fab_test
def test_its_own_help_still_describes_it(artifact_tree):
    """`fab-test pql-lint --help` must still work for anyone who knows it exists."""
    result = _run_cli("pql-lint", "--help")

    assert result.returncode == 0, result.stderr
    assert "--artifact-dir" in result.stdout


# --------------------------------------------------------------------------- #
# Hidden from the unknown-analyzer error, too
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_unknown_analyzer_error_does_not_leak_hidden_names():
    """argparse's own `invalid choice` names every alias, hidden ones included."""
    result = _run_cli("definitely-not-an-analyzer")

    assert result.returncode == 2
    assert "pql-lint" not in result.stderr
    assert "pql_lint" not in result.stderr
    assert "bpa" in result.stderr


@pytest.mark.fab_test
def test_unknown_analyzer_error_lists_canonical_spellings_only():
    """One spelling per command: the alias list belongs in --help, not here."""
    result = _run_cli("definitely-not-an-analyzer")

    assert "pql-test" in result.stderr
    assert "pql_test" not in result.stderr


@pytest.mark.fab_test
def test_a_near_miss_on_a_hidden_analyzer_still_gets_the_suggestion():
    """Hiding a name from the menu should not refuse a direct question."""
    result = _run_cli("pql-lnt")

    assert result.returncode == 2
    assert "fab-test pql-lint" in result.stderr
