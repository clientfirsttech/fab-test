"""Contract tests for per-analyzer scope rejection (Artifact Targeting and Auth §4).

Scope
-----
The grammar is parsed universally; whether a given analyzer can *honor* a
scope is decided here, once, from `ANALYZER_SCOPES`. Refusing at this
layer rather than in the parser is what lets the message name the
analyzer and the forms that would work, instead of rejecting a target
that is perfectly valid for the analyzer standing next to it.

Always passes on any machine: no analyzer subprocess is ever reached.
"""

import json
import os
import subprocess
import sys

import pytest

from fabric_ci_cd_dataops.scripts._target import parse_target
from fabric_ci_cd_dataops.scripts.fab_test_registry import (
    ANALYZER_REGISTRY,
    ANALYZER_SCOPES,
    unsupported_scope_error,
)

_WORKSPACE_TARGET = "Sales Dev.Workspace/Sales.SemanticModel"


@pytest.fixture
def artifact_tree(tmp_path):
    for folder in ("Sales.SemanticModel", "Sales.Report"):
        (tmp_path / folder).mkdir()
    return tmp_path


def _run_cli(*argv, env=None):
    return subprocess.run(
        [sys.executable, "-m", "fabric_ci_cd_dataops.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
        check=False,
    )


# --------------------------------------------------------------------------- #
# The declaration itself
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_every_registered_analyzer_declares_its_scopes():
    """A new analyzer cannot silently inherit "accepts everything"."""
    assert set(ANALYZER_SCOPES) == set(ANALYZER_REGISTRY)


@pytest.mark.fab_test
def test_every_analyzer_accepts_the_path_scope():
    """Reading an artifact off disk is the one thing they all do."""
    for name, scopes in ANALYZER_SCOPES.items():
        assert "path" in scopes, f"{name} rejects the path scope"


@pytest.mark.fab_test
def test_only_api_backed_analyzers_accept_a_workspace():
    """A file-reading analyzer would have to export the item first, a non-goal."""
    accepting = {name for name, scopes in ANALYZER_SCOPES.items() if "workspace" in scopes}

    assert accepting == {"pql_test", "playwright", "playwright-impact", "dependencies"}


# --------------------------------------------------------------------------- #
# unsupported_scope_error
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_no_target_is_never_a_scope_error():
    """The default invocation has no target to reject."""
    assert unsupported_scope_error("bpa", None) is None


@pytest.mark.fab_test
def test_path_target_is_accepted_everywhere():
    for name in ANALYZER_SCOPES:
        assert unsupported_scope_error(name, parse_target("Sales.SemanticModel")) is None


@pytest.mark.fab_test
def test_workspace_target_is_refused_for_a_file_reading_analyzer():
    """The message names the analyzer and the forms that do work."""
    message = unsupported_scope_error("bpa", parse_target(_WORKSPACE_TARGET))

    assert message is not None
    assert "bpa" in message
    assert "local/NAME" in message
    assert "./src/Sales.SemanticModel" in message


@pytest.mark.fab_test
def test_desktop_target_is_accepted_by_file_reading_analyzers():
    """local/Sales is just a name to bpa: the artifact is on disk either way.

    Without this, `fab-test all local/Sales` -- the natural local-dev
    invocation -- would fail on every analyzer except pql_test.
    """
    assert unsupported_scope_error("bpa", parse_target("local/Sales")) is None
    assert unsupported_scope_error("pql_lint", parse_target("local/Sales")) is None


@pytest.mark.fab_test
def test_desktop_target_is_refused_by_playwright():
    """Playwright drives a rendered report in the service; Desktop is not that."""
    assert unsupported_scope_error("playwright", parse_target("local/Sales")) is not None


# --------------------------------------------------------------------------- #
# CLI behavior
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_cli_refuses_a_workspace_target_for_bpa(artifact_tree):
    """Exit 2, and no analyzer subprocess or envelope."""
    output_dir = artifact_tree / "results"
    result = _run_cli(
        "bpa",
        _WORKSPACE_TARGET,
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        str(output_dir),
    )

    assert result.returncode == 2
    assert "bpa" in result.stderr
    assert not output_dir.exists(), "a refused scope must not write results"


@pytest.mark.fab_test
def test_cli_all_skips_unsupported_analyzers_rather_than_failing(artifact_tree):
    """`all local/Sales` still runs the file readers, and says what it skipped."""
    result = _run_cli(
        "all",
        "local/Sales",
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
    )

    # pql_test is the only default analyzer that binds to Desktop, and a
    # dry run never reaches the running-instance preflight.
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.fab_test
def test_list_reports_the_accepted_scopes(artifact_tree):
    """An agent can discover what a target may look like without reading source."""
    result = _run_cli("list", "--artifact-dir", str(artifact_tree), "--format", "json")

    assert result.returncode == 0, result.stderr
    rows = {r["analyzer"]: r for r in json.loads(result.stdout)["analyzers"]}
    assert "workspace" in rows["pql-test"]["scopes"]
    assert "workspace" not in rows["bpa"]["scopes"]


# --------------------------------------------------------------------------- #
# Refusing an unhandled artifact type (Discover From CWD §5)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_a_type_the_analyzer_does_not_read_names_both_halves():
    """Was "unknown artifact type 'Notebook'" — a type the repository's own
    map declares. Then, once it parsed, "no *.SemanticModel artifacts found",
    which describes the directory rather than the mistake."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import unsupported_type_error

    message = unsupported_type_error("bpa", parse_target("Sales.Notebook"))

    assert message is not None
    assert "SemanticModel" in message
    assert "Notebook" in message
    assert "unknown" not in message.lower()


@pytest.mark.fab_test
def test_a_type_another_analyzer_reads_names_that_analyzer():
    """The next question is always "then what do I run?"."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import unsupported_type_error

    message = unsupported_type_error("bpa", parse_target("Sales.Report"))

    assert message is not None
    assert "pbir" in message


@pytest.mark.fab_test
def test_a_type_no_analyzer_reads_says_so_plainly():
    """Rather than naming a flag or an analyzer that would not help."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import unsupported_type_error

    message = unsupported_type_error("bpa", parse_target("Sales.Lakehouse"))

    assert message is not None
    assert "no fab-test analyzer reads" in message


@pytest.mark.fab_test
def test_a_hidden_analyzer_is_not_suggested():
    """pql_lint is off the advertised surface; a refusal must not readvertise it."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import unsupported_type_error

    message = unsupported_type_error("pbir", parse_target("Sales.SemanticModel"))

    assert message is not None
    assert "pql_lint" not in message


@pytest.mark.fab_test
def test_the_matching_type_is_not_refused():
    from fabric_ci_cd_dataops.scripts.fab_test_registry import unsupported_type_error

    assert unsupported_type_error("bpa", parse_target("Sales.SemanticModel")) is None


@pytest.mark.fab_test
def test_a_target_with_no_type_is_not_refused():
    """`Sales` leaves the type to the analyzer's glob, which is the point."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import unsupported_type_error

    assert unsupported_type_error("bpa", parse_target("Sales")) is None


@pytest.mark.fab_test
def test_a_repository_scoped_analyzer_refuses_no_type():
    """It runs against the repository, so an artifact type is not something
    it could be given the wrong one of."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import unsupported_type_error

    assert unsupported_type_error("dependencies", parse_target("Sales.Notebook")) is None


@pytest.mark.fab_test
def test_list_shows_which_suffix_each_analyzer_handles():
    """So the answer is discoverable before the error, not only after it."""
    from fabric_ci_cd_dataops.scripts.fab_test_registry import (
        ANALYZER_REGISTRY,
        visible_analyzers,
    )

    globs = {name: ANALYZER_REGISTRY[name][0] for name in visible_analyzers()}

    assert globs["bpa"] == "*.SemanticModel"
    assert globs["pbir"] == "*.Report"
