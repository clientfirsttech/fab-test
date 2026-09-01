"""Empty discovery diagnostics: naming what an empty scan pruned.

Scope
-----
An empty artifact scan distinguishing "nothing here" from "checkouts were
pruned on purpose" -- naming and capping the skipped checkouts, carrying
them (and a remediation hint) in the JSON payload, and leaving the
in-repository and explicit-path cases unchanged and quiet.

    pytest -m fab_test
"""
import json
import subprocess
from pathlib import Path

import pytest

from fab_test.scripts.fab_test import _run_analyzer
from tests.conftest import _RunAnalyzerArgs

# --------------------------------------------------------------------------- #
# Empty discovery explains itself
# --------------------------------------------------------------------------- #


def _sibling_checkout(parent: Path, name: str) -> Path:
    """A directory the scan will refuse to walk into, as a real repo would be."""
    checkout = parent / name
    (checkout / ".git").mkdir(parents=True)
    return checkout


@pytest.mark.fab_test
def test_empty_result_does_not_claim_a_pbip_would_have_helped(tmp_path, capsys):
    """Given an empty scan, the message should name the folder suffix it
    searched for and not offer a .pbip as an alternative route to being
    found -- it stopped being one when discovery went suffix-based.
    """
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    args = _RunAnalyzerArgs(artifact_dir, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")

    assert ".pbip" not in capsys.readouterr().out


@pytest.mark.fab_test
def test_empty_result_reports_the_checkouts_it_skipped(tmp_path, capsys):
    """Given a root holding only git checkouts, the scan finds nothing by
    design, so the message should say how many it skipped rather than
    report an absence the caller can neither see nor act on.
    """
    _sibling_checkout(tmp_path, "project-a")
    _sibling_checkout(tmp_path, "project-b")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")
    out = capsys.readouterr().out

    assert "2 git checkouts" in out
    assert "--artifact-dir" in out


@pytest.mark.fab_test
def test_the_skipped_checkouts_are_named_so_the_remedy_is_pasteable(tmp_path, capsys):
    """Given skipped checkouts, naming them turns the hint into a command."""
    checkout = _sibling_checkout(tmp_path, "project-a")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")

    assert str(checkout) in capsys.readouterr().out


@pytest.mark.fab_test
def test_only_the_first_few_skipped_checkouts_are_named(tmp_path, capsys):
    """Given many skipped checkouts, a warning should stay a warning --
    listing every repository on a developer's machine is not a remedy.
    """
    for index in range(9):
        _sibling_checkout(tmp_path, f"project-{index}")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")
    out = capsys.readouterr().out

    assert "9 git checkouts" in out
    assert sum(f"project-{i}" in out for i in range(9)) == 3


@pytest.mark.fab_test
def test_an_empty_repository_gains_no_checkout_note(tmp_path, capsys):
    """Given nothing was pruned, the in-repo case must not get noisier to
    serve the out-of-repo one.
    """
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    args = _RunAnalyzerArgs(artifact_dir, tmp_path / "out", output_format="text")
    _run_analyzer("bpa", args, tmp_path / "out")
    out = capsys.readouterr().out

    assert "checkout" not in out
    assert "--artifact-dir" not in out


@pytest.mark.fab_test
def test_a_path_target_gains_no_checkout_note(tmp_path, capsys):
    """Given the caller named a location, reporting what a scan elsewhere
    pruned answers a question they did not ask.
    """
    _sibling_checkout(tmp_path, "project-a")
    missing = tmp_path / "Nowhere.SemanticModel"

    args = _RunAnalyzerArgs(
        tmp_path, tmp_path / "out", artifact=str(missing), output_format="text"
    )
    _run_analyzer("bpa", args, tmp_path / "out")

    assert "checkout" not in capsys.readouterr().out


@pytest.mark.fab_test
def test_skipped_checkouts_reach_the_json_payload(tmp_path, capsys):
    """Given an agent caller, an empty `artifacts` list reads the same
    whether the repository was empty or every candidate was pruned, so the
    payload should carry the distinction and a remediation it can act on.
    """
    checkout = _sibling_checkout(tmp_path, "project-a")

    args = _RunAnalyzerArgs(tmp_path, tmp_path / "out", output_format="json")
    _run_analyzer("bpa", args, tmp_path / "out")
    summary = json.loads(capsys.readouterr().out)

    assert summary["artifacts"] == []
    assert summary["skipped_checkouts"] == [str(checkout)]
    assert "--artifact-dir" in summary["remediation"]


@pytest.mark.fab_test
def test_an_empty_payload_carries_no_remediation_key(tmp_path, capsys):
    """Given nothing was pruned, there is nothing to remediate."""
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    args = _RunAnalyzerArgs(artifact_dir, tmp_path / "out", output_format="json")
    _run_analyzer("bpa", args, tmp_path / "out")
    summary = json.loads(capsys.readouterr().out)

    assert summary["skipped_checkouts"] == []
    assert "remediation" not in summary


@pytest.mark.fab_test
def test_main_artifact_dir_missing_message_narrated_by_format(tmp_path):
    """main()'s --artifact-dir-missing message follows --format routing too."""
    missing = tmp_path / "does-not-exist"

    result = subprocess.run(
        ["fab-test", "bpa", "--artifact-dir", str(missing), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "does not exist" in result.stderr


