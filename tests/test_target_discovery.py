"""Contract tests for target-driven discovery (Artifact Targeting and Auth §2).

Scope
-----
Wires the §1 parser into artifact selection. `discover_artifacts` now takes
a `ResolvedTarget` rather than a bare stem, so a type-qualified target
(`Sales.SemanticModel`) selects by type instead of by accident, and the
`local/` scheme states the Desktop binding rather than leaving it implied
by the absence of `--workspace-id`.

Only the two scopes needing no network are wired here; workspace
resolution is §3. Always passes on any machine: the Desktop paths are
exercised through a stubbed instance probe, never a real session.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts._target import TargetError, parse_target, select_target
from fab_test.scripts.fab_test import RESULTS_ROOT
from fab_test.scripts.fab_test_registry import discover_artifacts


@pytest.fixture
def artifact_tree(tmp_path):
    """A repository root holding one model and one report of the same name."""
    for folder in ("Sales.SemanticModel", "Sales.Report", "Other.SemanticModel"):
        (tmp_path / folder).mkdir()
    return tmp_path


def _run_cli(*argv, cwd=None, env=None):
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=merged,
        check=False,
    )


# --------------------------------------------------------------------------- #
# discover_artifacts
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_no_target_discovers_everything_matching_the_glob(artifact_tree):
    """The default path is unchanged: no target means discover as before."""
    found = discover_artifacts(artifact_tree, "*.SemanticModel", None)

    assert {p.name for p in found} == {"Sales.SemanticModel", "Other.SemanticModel"}


@pytest.mark.fab_test
def test_bare_name_target_filters_by_stem(artifact_tree):
    """A bare name behaves like the old --artifact STEM."""
    found = discover_artifacts(artifact_tree, "*.SemanticModel", parse_target("Sales"))

    assert [p.name for p in found] == ["Sales.SemanticModel"]


@pytest.mark.fab_test
def test_typed_target_selects_only_that_type(artifact_tree):
    """Sales.SemanticModel must not select Sales.Report, even for a Report glob."""
    target = parse_target("Sales.SemanticModel")

    assert discover_artifacts(artifact_tree, "*.Report", target) == []
    assert [p.name for p in discover_artifacts(artifact_tree, "*.SemanticModel", target)] == [
        "Sales.SemanticModel"
    ]


@pytest.mark.fab_test
def test_path_target_selects_exactly_that_artifact(artifact_tree):
    """An explicit path is used directly rather than filtered out of discovery."""
    target = parse_target(str(artifact_tree / "Sales.SemanticModel"))

    found = discover_artifacts(artifact_tree, "*.SemanticModel", target)

    assert [p.name for p in found] == ["Sales.SemanticModel"]


@pytest.mark.fab_test
def test_path_target_outside_the_artifact_dir_is_honored(tmp_path, artifact_tree):
    """A path target names a location, so it is not confined to --artifact-dir."""
    elsewhere = tmp_path / "elsewhere" / "Remote.SemanticModel"
    elsewhere.mkdir(parents=True)

    found = discover_artifacts(artifact_tree, "*.SemanticModel", parse_target(str(elsewhere)))

    assert [p.name for p in found] == ["Remote.SemanticModel"]


@pytest.mark.fab_test
def test_path_target_that_does_not_exist_finds_nothing(artifact_tree):
    """A misspelled path yields no artifacts rather than silently discovering others."""
    target = parse_target(str(artifact_tree / "Missing.SemanticModel"))

    assert discover_artifacts(artifact_tree, "*.SemanticModel", target) == []


@pytest.mark.fab_test
def test_desktop_target_filters_by_name_like_a_stem(artifact_tree):
    """local/Sales still needs the on-disk artifact; the scope only changes binding."""
    found = discover_artifacts(artifact_tree, "*.SemanticModel", parse_target("local/Sales"))

    assert [p.name for p in found] == ["Sales.SemanticModel"]


# --------------------------------------------------------------------------- #
# discover_artifacts -- flat-file globs (a paginated report is NAME.rdl, not
# a folder with a Fabric type suffix)
# --------------------------------------------------------------------------- #


@pytest.fixture
def rdl_tree(tmp_path):
    """A repository root holding one .rdl file and one unrelated .Report folder."""
    (tmp_path / "Sales.rdl").write_text("<Report />", encoding="utf-8")
    (tmp_path / "Sales.Report").mkdir()
    return tmp_path


@pytest.mark.fab_test
def test_no_target_discovers_every_rdl_file(rdl_tree):
    """The flat-file path mirrors the folder path: no target, no filtering."""
    found = discover_artifacts(rdl_tree, "*.rdl", None)

    assert [p.name for p in found] == ["Sales.rdl"]


@pytest.mark.fab_test
def test_bare_name_target_selects_the_matching_rdl_file(rdl_tree):
    """A bare name filters a flat file by stem the same way it filters a folder."""
    found = discover_artifacts(rdl_tree, "*.rdl", parse_target("Sales"))

    assert [p.name for p in found] == ["Sales.rdl"]


@pytest.mark.fab_test
def test_rdl_typed_target_selects_the_file(rdl_tree):
    """Sales.rdl -- the explicit NAME.Type form -- selects that one file."""
    found = discover_artifacts(rdl_tree, "*.rdl", parse_target("Sales.rdl"))

    assert [p.name for p in found] == ["Sales.rdl"]


@pytest.mark.fab_test
def test_a_folder_typed_target_selects_nothing_for_the_rdl_glob(rdl_tree):
    """Sales.Report names a different shape of artifact entirely; rdl reads
    flat files only."""
    found = discover_artifacts(rdl_tree, "*.rdl", parse_target("Sales.Report"))

    assert found == []


@pytest.mark.fab_test
def test_path_target_selects_exactly_that_rdl_file(rdl_tree):
    """An explicit path to a flat file is used directly, mirroring the folder case."""
    target = parse_target(str(rdl_tree / "Sales.rdl"))

    found = discover_artifacts(rdl_tree, "*.rdl", target)

    assert [p.name for p in found] == ["Sales.rdl"]


@pytest.mark.fab_test
def test_path_target_naming_a_folder_does_not_match_the_rdl_glob(rdl_tree):
    """A path target's own shape must still agree with the glob's shape --
    pointing at a folder for a flat-file analyzer matches nothing."""
    target = parse_target(str(rdl_tree / "Sales.Report"))

    assert discover_artifacts(rdl_tree, "*.rdl", target) == []


@pytest.mark.fab_test
def test_the_rdl_run_output_directory_is_not_rediscovered(tmp_path):
    """Mirrors the folder-analyzer case: results land in a folder named
    after the artifact, which must not itself be rediscovered as one."""
    real = tmp_path / "Sales.rdl"
    real.write_text("<Report />", encoding="utf-8")
    results = tmp_path / "fab-test-results" / "rdl"
    results.mkdir(parents=True)
    (results / "Sales.rdl").write_text("stale", encoding="utf-8")

    found = discover_artifacts(tmp_path, "*.rdl", None, output_dir=tmp_path / "fab-test-results")

    assert found == [real.resolve()]


@pytest.mark.fab_test
def test_folder_based_discovery_is_unchanged_by_flat_file_support(artifact_tree):
    """The existing *.SemanticModel/*.Report path must behave exactly as
    before -- flat-file support is an addition, not a rewrite."""
    found = discover_artifacts(artifact_tree, "*.SemanticModel", None)

    assert {p.name for p in found} == {"Sales.SemanticModel", "Other.SemanticModel"}


# --------------------------------------------------------------------------- #
# select_target
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_select_target_returns_none_when_neither_is_given():
    """No target at all is the common case and stays untyped."""
    assert select_target(None, None) is None


@pytest.mark.fab_test
def test_select_target_accepts_the_legacy_artifact_flag():
    """--artifact routes through the same parser, so it gains type awareness."""
    target = select_target(None, "Sales.SemanticModel")

    assert target.name == "Sales"
    assert target.type == "SemanticModel"


@pytest.mark.fab_test
def test_select_target_rejects_both_at_once():
    """Two ways to say the same thing is a caller error, not a precedence puzzle."""
    with pytest.raises(TargetError) as excinfo:
        select_target("Sales", "Other")

    assert "--artifact" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_cli_positional_target_limits_the_dry_run(artifact_tree):
    """fab-test bpa <path> --dry-run plans only that artifact."""
    result = _run_cli(
        "bpa",
        str(artifact_tree / "Sales.SemanticModel"),
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [Path(a).name for a in payload["artifacts"]] == ["Sales.SemanticModel"]


@pytest.mark.fab_test
def test_cli_typed_target_under_all_selects_one_type(artifact_tree):
    """`all Sales.SemanticModel` plans the model and never the report.

    The negative half carries the weight: the per-analyzer dry-run plans
    print full artifact names, so `Sales.Report` appearing anywhere means
    pbir was handed an artifact the type filter should have excluded.
    Confirmed by mutation — disabling the type check in `discover_artifacts`
    makes this fail.
    """
    result = _run_cli(
        "all",
        "Sales.SemanticModel",
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "Sales.SemanticModel" in result.stdout
    assert "Sales.Report" not in result.stdout


@pytest.mark.fab_test
def test_all_aggregate_summary_honors_the_target(artifact_tree):
    """The summary must reflect what ran, not re-discover everything.

    `_print_all_summary` runs its own discovery pass, so it needs the same
    target the analyzers got. Without it, the summary lists rows for
    artifacts that were never analyzed.
    """
    result = _run_cli(
        "all",
        "Sales.SemanticModel",
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    stems = {row["artifact"] for row in payload["artifacts"]}
    assert "Other" not in stems, "summary discovered artifacts the target excluded"


@pytest.mark.fab_test
def test_all_with_the_legacy_artifact_flag_does_not_crash(artifact_tree):
    """Regression: `all --artifact X` passed a raw string where a target was due.

    `discover_artifacts` began taking a ResolvedTarget, but this call site
    still handed it `args.artifact`, so the deprecated flag raised
    AttributeError instead of filtering.
    """
    result = _run_cli(
        "all",
        "--artifact",
        "Sales",
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.fab_test
def test_cli_rejects_a_positional_target_and_artifact_flag_together(artifact_tree):
    """Exit 2, naming both, rather than silently preferring one."""
    result = _run_cli(
        "bpa",
        "Sales",
        "--artifact",
        "Other",
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
    )

    assert result.returncode == 2
    assert "--artifact" in result.stderr


@pytest.mark.fab_test
def test_cli_unparseable_target_exits_2(artifact_tree):
    """A malformed target is an argument error: exit 2, no analyzer invoked."""
    result = _run_cli(
        "bpa",
        "Sales.SemmanticModel",
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
    )

    assert result.returncode == 2
    assert "SemanticModel" in result.stderr


@pytest.mark.fab_test
def test_cli_desktop_target_without_an_instance_exits_127(artifact_tree):
    """local/Sales with nothing running is a missing prerequisite, not a rule failure."""
    result = _run_cli(
        "pql-test",
        "local/Sales",
        "--artifact-dir",
        str(artifact_tree),
        env={"LOCALAPPDATA": str(artifact_tree / "no-desktop-here")},
    )

    # Narration goes to stdout in text mode (stderr is reserved for --format
    # json), matching how the existing missing-tool preflight reports.
    #
    # Asserts the diagnosis, not just the word "Desktop": that appears in the
    # remediation line too, so a bare substring check passed even when the
    # failure message itself changed. Found by mutating the message.
    output = result.stdout + result.stderr
    assert result.returncode == 127, output
    assert "no running Power BI Desktop instance has" in output
    assert "Sales.SemanticModel" in output, "the message must name the artifact"
    assert "drop the 'local/' prefix" in output, "and offer the way out"


# --------------------------------------------------------------------------- #
# Suffix-based recursive discovery (Discover From CWD §3)
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_an_artifact_without_a_pbip_is_discovered(tmp_path):
    """The shape of artifacts committed for CI rather than opened in
    Desktop. Top-level globbing plus `.pbip` pairing made these invisible."""
    folder = tmp_path / "deployed" / "prod" / "Sales.SemanticModel"
    folder.mkdir(parents=True)

    assert discover_artifacts(tmp_path, "*.SemanticModel", None) == [folder.resolve()]


@pytest.mark.fab_test
def test_pbip_pairing_still_enriches_a_discovered_artifact(tmp_path):
    """Pairing stopped deciding whether an artifact exists. It must not have
    stopped supplying the `[from X.pbip]` note and the Desktop binding."""
    from fab_test.scripts.fab_test_registry import discover_pbip_sources

    model = tmp_path / "Sales.SemanticModel"
    model.mkdir()
    (tmp_path / "Sales.pbip").write_text(
        json.dumps({"version": "1.0", "artifacts": [{"report": {"path": "Sales.Report"}}]}),
        encoding="utf-8",
    )
    (tmp_path / "Sales.Report").mkdir()

    assert discover_pbip_sources(tmp_path)


@pytest.mark.fab_test
def test_the_run_output_directory_is_not_rediscovered(tmp_path):
    """Results are written to folders named after the artifacts that
    produced them, so an unpruned scan compounds every run."""
    real = tmp_path / "Sales.SemanticModel"
    real.mkdir()
    results = tmp_path / "fab-test-results" / "bpa"
    (results / "Sales.SemanticModel").mkdir(parents=True)

    found = discover_artifacts(
        tmp_path, "*.SemanticModel", None, output_dir=tmp_path / "fab-test-results"
    )

    assert found == [real.resolve()]


@pytest.mark.fab_test
def test_a_nested_checkout_does_not_multiply_this_repository():
    """Measured before the change: a naive recursive scan of this repository
    returns 8 artifacts, 5 of them worktree copies of the other 3."""
    root = Path(__file__).resolve().parent.parent
    found = discover_artifacts(root, "*.SemanticModel", None, output_dir=RESULTS_ROOT)

    assert [p.name for p in found] == [
        "Not Working Visuals.SemanticModel",
        "Report with Bookmarks - Broken Visuals.SemanticModel",
        "SampleModel-PQLAssert.SemanticModel",
        "ThinReport.SemanticModel",
    ]
