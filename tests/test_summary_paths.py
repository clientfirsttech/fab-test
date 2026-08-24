"""Contract tests for result paths in the `fab-test all` summary.

Scope
-----
The aggregate summary truncated absolute envelope paths to 50 characters,
which cut off the analyzer and artifact segments -- the informative half --
and left a string no terminal could turn into a link and no reader could
copy.

Text output now shows the path relative to the working directory, in full:
terminals resolve a relative path against their own cwd, so it stays
clickable while fitting the table. JSON output keeps absolute paths, which
is what a pipeline consuming the manifest wants.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.fab_test_summary import _display_path


@pytest.fixture
def artifact_tree(tmp_path):
    (tmp_path / "Sales.SemanticModel").mkdir()
    return tmp_path


def _run_cli(*argv, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "fabric_ci_cd_dataops.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=os.environ.copy(),
        check=False,
    )


@pytest.mark.fab_test
def test_path_under_the_working_directory_is_shown_relative(tmp_path, monkeypatch):
    """The common case: short enough to fit, complete enough to click."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "fab-test-results" / "bpa" / "Sales" / "envelope.json"

    assert _display_path(target) == str(Path("fab-test-results/bpa/Sales/envelope.json"))


@pytest.mark.fab_test
def test_a_relative_input_is_still_resolved_and_shortened(tmp_path, monkeypatch):
    """--output-dir is often already relative; the result must not double up."""
    monkeypatch.chdir(tmp_path)

    assert _display_path("fab-test-results/bpa/Sales/envelope.json") == str(
        Path("fab-test-results/bpa/Sales/envelope.json")
    )


@pytest.mark.fab_test
def test_path_outside_the_working_directory_stays_absolute(tmp_path, monkeypatch):
    """No ../../ chains: they are longer than the absolute path and harder to read."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    elsewhere = tmp_path / "elsewhere" / "envelope.json"
    monkeypatch.chdir(workdir)

    assert _display_path(elsewhere) == str(elsewhere.resolve())
    assert ".." not in _display_path(elsewhere)


@pytest.mark.fab_test
def test_summary_shows_the_whole_path_with_no_ellipsis(artifact_tree):
    """End to end: the segment that identifies the analyzer must survive."""
    result = _run_cli(
        "all",
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        "fab-test-results",
        "--dry-run",
        cwd=str(artifact_tree),
    )

    assert result.returncode == 0, result.stderr
    assert "envelope.json" in result.stdout, "path was cut short of its filename"
    assert "..." not in result.stdout


@pytest.mark.fab_test
def test_json_output_keeps_absolute_paths(artifact_tree):
    """A pipeline reading the JSON wants an unambiguous path, not a cwd-relative one."""
    result = _run_cli(
        "all",
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        str(artifact_tree / "fab-test-results"),
        "--dry-run",
        "--format",
        "json",
        cwd=str(artifact_tree),
    )

    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)["artifacts"]
    paths = [r["output_path"] for r in rows if r["output_path"]]
    assert paths, "expected at least one result path"
    for path in paths:
        assert Path(path).is_absolute()
