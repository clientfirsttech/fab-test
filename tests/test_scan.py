"""Contract tests for suffix-based recursive discovery (Discover From CWD §3).

Scope
-----
An artifact is identified by its folder suffix, at any depth, whether or
not a `.pbip` sits beside it. Scanning from the working directory makes
the exclusion list load-bearing: measured on this repository, a naive
recursive scan returns eight artifacts where three are real, the rest
being copies inside nested worktrees.

Always passes on any machine.
"""

import time
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts._scan import EXCLUDED_DIR_NAMES, find_artifact_dirs, scan

SUFFIXES = (".SemanticModel", ".Report")


def _artifact(parent: Path, name: str) -> Path:
    """Create an artifact folder with the contents a real one has."""
    folder = parent / name
    (folder / "definition").mkdir(parents=True)
    (folder / "definition" / "model.tmdl").write_text("model", encoding="utf-8")
    return folder


# --------------------------------------------------------------------------- #
# What counts as an artifact
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_an_artifact_is_found_at_any_depth(tmp_path):
    """Top-level-only globbing is what hid deployed/ artifacts."""
    deep = _artifact(tmp_path / "deployed" / "prod", "Sales.SemanticModel")

    assert find_artifact_dirs(tmp_path, SUFFIXES) == [deep]


@pytest.mark.fab_test
def test_an_artifact_without_a_pbip_is_found(tmp_path):
    """The shape of artifacts committed for CI; previously invisible."""
    folder = _artifact(tmp_path, "Sales.SemanticModel")

    assert find_artifact_dirs(tmp_path, SUFFIXES) == [folder]


@pytest.mark.fab_test
def test_a_folder_with_no_known_suffix_is_not_an_artifact(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "Sales").mkdir()

    assert find_artifact_dirs(tmp_path, SUFFIXES) == []


@pytest.mark.fab_test
def test_a_matched_artifact_is_not_descended_into(tmp_path):
    """A subfolder of an artifact is its contents, not another artifact."""
    folder = _artifact(tmp_path, "Sales.SemanticModel")
    (folder / "Nested.Report").mkdir()

    assert find_artifact_dirs(tmp_path, SUFFIXES) == [folder]


@pytest.mark.fab_test
def test_results_are_sorted_and_deduplicated(tmp_path):
    second = _artifact(tmp_path, "Alpha.Report")
    first = _artifact(tmp_path, "Zulu.SemanticModel")

    assert find_artifact_dirs(tmp_path, SUFFIXES) == [second, first]


# --------------------------------------------------------------------------- #
# What is pruned
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_a_nested_git_checkout_is_skipped(tmp_path):
    """Five of the eight a naive scan finds here are worktree copies."""
    real = _artifact(tmp_path, "Sales.SemanticModel")
    worktree = tmp_path / ".claude" / "worktrees" / "feature"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../../..", encoding="utf-8")
    _artifact(worktree, "Sales.SemanticModel")

    assert find_artifact_dirs(tmp_path, SUFFIXES) == [real]


@pytest.mark.fab_test
def test_the_roots_own_git_directory_does_not_disqualify_it(tmp_path):
    """Otherwise scanning any repository from its root returns nothing."""
    (tmp_path / ".git").mkdir()
    folder = _artifact(tmp_path, "Sales.SemanticModel")

    assert find_artifact_dirs(tmp_path, SUFFIXES) == [folder]


@pytest.mark.fab_test
@pytest.mark.parametrize("excluded", sorted(EXCLUDED_DIR_NAMES - {".git"}))
def test_excluded_directories_are_not_scanned(tmp_path, excluded):
    _artifact(tmp_path / excluded, "Vendored.SemanticModel")

    assert find_artifact_dirs(tmp_path, SUFFIXES) == []


@pytest.mark.fab_test
def test_the_output_directory_is_pruned_when_the_caller_says_so(tmp_path):
    """Analyzer results land in folders named after the artifacts that
    produced them; rediscovering those would compound every run."""
    results = tmp_path / "analyzer-results"
    _artifact(results / "bpa", "Sales.SemanticModel")
    real = _artifact(tmp_path, "Sales.SemanticModel")

    found = find_artifact_dirs(tmp_path, SUFFIXES, excluded_paths=[results])

    assert found == [real]


@pytest.mark.fab_test
def test_a_missing_root_yields_nothing_rather_than_raising(tmp_path):
    assert find_artifact_dirs(tmp_path / "absent", SUFFIXES) == []


@pytest.mark.fab_test
def test_a_file_as_root_yields_nothing(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    assert find_artifact_dirs(target, SUFFIXES) == []


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_scanning_this_repository_stays_fast():
    """Every subcommand now pays this on startup. If it is not well under a
    second on a real repository, an exclusion is missing."""
    root = Path(__file__).resolve().parent.parent

    start = time.perf_counter()
    found = find_artifact_dirs(root, SUFFIXES, excluded_paths=[root / "analyzer-results"])
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"{elapsed:.2f}s to scan {len(found)} artifacts"


# --------------------------------------------------------------------------- #
# What the scan pruned (Empty Discovery Diagnostics §1)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_scan_reports_the_nested_checkouts_it_pruned(tmp_path):
    """An empty result is otherwise indistinguishable from an empty repository."""
    checkout = tmp_path / "sibling-project"
    (checkout / ".git").mkdir(parents=True)
    _artifact(checkout, "Sales.SemanticModel")

    result = scan(tmp_path, SUFFIXES)

    assert result.artifacts == []
    assert result.skipped_checkouts == [checkout]


@pytest.mark.fab_test
def test_scan_reports_checkouts_even_when_artifacts_were_found(tmp_path):
    """`list` and `--dry-run` narrate a partial scan, not only an empty one."""
    visible = _artifact(tmp_path, "Visible.Report")
    checkout = tmp_path / "vendored"
    (checkout / ".git").mkdir(parents=True)

    result = scan(tmp_path, SUFFIXES)

    assert result.artifacts == [visible]
    assert result.skipped_checkouts == [checkout]


@pytest.mark.fab_test
def test_the_roots_own_git_directory_is_not_a_pruned_checkout(tmp_path):
    """Otherwise every in-repo scan would claim it skipped something."""
    (tmp_path / ".git").mkdir()
    _artifact(tmp_path, "Sales.SemanticModel")

    assert scan(tmp_path, SUFFIXES).skipped_checkouts == []


@pytest.mark.fab_test
@pytest.mark.parametrize("excluded", sorted(EXCLUDED_DIR_NAMES - {".git"}))
def test_excluded_directories_are_not_reported_as_checkouts(tmp_path, excluded):
    """A caller can act on a skipped repository; it cannot act on .venv."""
    (tmp_path / excluded).mkdir()

    assert scan(tmp_path, SUFFIXES).skipped_checkouts == []


@pytest.mark.fab_test
def test_pruned_checkouts_are_sorted_and_deduplicated(tmp_path):
    """The paths are shown to a human, so their order must be stable."""
    for name in ("zeta", "alpha"):
        (tmp_path / name / ".git").mkdir(parents=True)

    result = scan(tmp_path, SUFFIXES)

    assert result.skipped_checkouts == [tmp_path / "alpha", tmp_path / "zeta"]


@pytest.mark.fab_test
def test_find_artifact_dirs_still_returns_a_plain_list(tmp_path):
    """Two modules call it; this epic changes what is said, not what is found."""
    folder = _artifact(tmp_path, "Sales.SemanticModel")

    assert find_artifact_dirs(tmp_path, SUFFIXES) == [folder]
