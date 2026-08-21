"""Unit tests for the seams opened by the §4-5 refactor.

Scope
-----
These assert on data structures rather than captured stdout. That is the
point of the split: `build_all_summary_rows` returns rows, `_artifact_status`
classifies one outcome, and the `_prepare_*` guards return an exit code or
None — none of which previously existed as anything a test could reach
without running the CLI and parsing its output.

The refactor itself is guarded by the existing suite plus a byte-for-byte
comparison of real `fab-test` output. These cover the new surfaces.
"""

import argparse
import json

import pytest

from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module
from fabric_ci_cd_dataops.scripts._analyzer_envelope import build_envelope
from fabric_ci_cd_dataops.scripts.fab_test_summary import (
    _artifact_status,
    build_all_summary_rows,
)

# --------------------------------------------------------------------------- #
# _artifact_status
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_a_nonzero_exit_code_is_failed_whatever_the_envelope_says():
    """The analyzer crashing outranks whatever it managed to write."""
    assert _artifact_status({"status": "passed"}, code=1, errors=0, warnings=0) == "failed"


@pytest.mark.fab_test
def test_errors_mean_failed_even_on_a_zero_exit():
    """Warnings do not fail a build; errors do, per the exit-code contract."""
    assert _artifact_status({"status": "passed"}, code=0, errors=3, warnings=0) == "failed"


@pytest.mark.fab_test
def test_skipped_survives_when_nothing_failed():
    assert _artifact_status({"status": "skipped"}, code=0, errors=0, warnings=0) == "skipped"


@pytest.mark.fab_test
def test_warnings_alone_are_a_warning_not_a_failure():
    assert _artifact_status(None, code=0, errors=0, warnings=21) == "warning"


@pytest.mark.fab_test
def test_a_clean_run_is_passed():
    assert _artifact_status(None, code=0, errors=0, warnings=0) == "passed"


# --------------------------------------------------------------------------- #
# build_all_summary_rows
# --------------------------------------------------------------------------- #


def _args(artifact_dir, output_dir, **overrides):
    defaults = {
        "artifact_dir": str(artifact_dir),
        "output_dir": str(output_dir),
        "dry_run": False,
        "output_format": "text",
        "artifact": None,
        "target": None,
        "resolved_target": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _write_envelope(output_dir, analyzer, stem, findings=()):
    path = output_dir / analyzer / stem
    path.mkdir(parents=True, exist_ok=True)
    (path / "envelope.json").write_text(
        json.dumps(
            build_envelope(
                analyzer=analyzer,
                artifact_path=stem,
                status="passed",
                findings=list(findings),
            )
        ),
        encoding="utf-8",
    )


@pytest.mark.fab_test
def test_rows_can_be_asserted_without_capturing_stdout(tmp_path):
    """The whole reason for the split."""
    artifacts = tmp_path / "artifacts"
    (artifacts / "Sales.SemanticModel").mkdir(parents=True)
    results = tmp_path / "results"
    _write_envelope(results, "bpa", "Sales", [{"rule": "R", "severity": "warning"}])

    rows = build_all_summary_rows(results, ("bpa",), [0], _args(artifacts, results))

    assert [r["artifact"] for r in rows] == ["Sales"]
    assert rows[0]["status"] == "warning"
    assert rows[0]["warnings"] == 1


@pytest.mark.fab_test
def test_an_analyzer_matching_nothing_gets_a_placeholder_row(tmp_path):
    """`all` still lists the analyzer, so the reader sees it ran and found nothing."""
    artifacts = tmp_path / "artifacts"
    (artifacts / "Sales.SemanticModel").mkdir(parents=True)
    results = tmp_path / "results"

    rows = build_all_summary_rows(results, ("pbir",), [0], _args(artifacts, results))

    assert [r["artifact"] for r in rows] == ["(none)"]
    assert rows[0]["report_path"] is None


@pytest.mark.fab_test
def test_a_dry_run_reports_no_counts(tmp_path):
    """Nothing ran, so any count would be invented."""
    artifacts = tmp_path / "artifacts"
    (artifacts / "Sales.SemanticModel").mkdir(parents=True)
    results = tmp_path / "results"

    rows = build_all_summary_rows(
        results, ("bpa",), [0], _args(artifacts, results, dry_run=True)
    )

    assert rows[0]["status"] == "dry-run"
    assert rows[0]["errors"] == 0
    assert rows[0]["warnings"] == 0


@pytest.mark.fab_test
def test_rows_carry_the_report_path_when_the_envelope_has_one(tmp_path):
    artifacts = tmp_path / "artifacts"
    (artifacts / "Sales.Report").mkdir(parents=True)
    results = tmp_path / "results"
    path = results / "pbir" / "Sales"
    path.mkdir(parents=True)
    (path / "envelope.json").write_text(
        json.dumps(
            build_envelope(
                analyzer="pbir",
                artifact_path="Sales",
                status="passed",
                native_html_output_path_str="results/pbir/Sales/TestRun.html",
            )
        ),
        encoding="utf-8",
    )

    rows = build_all_summary_rows(results, ("pbir",), [0], _args(artifacts, results))

    assert rows[0]["report_path"] == "results/pbir/Sales/TestRun.html"


# --------------------------------------------------------------------------- #
# The main() preparation chain
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_every_prepare_step_is_callable_with_just_args():
    """The chain in main() depends on one uniform signature."""
    for step in fab_test_module._PREPARE_STEPS:
        assert callable(step), step


@pytest.mark.fab_test
def test_prepare_target_rejects_an_unparseable_target(capsys):
    """Exit 2, without invoking the CLI to find out."""
    args = argparse.Namespace(
        analyzer="bpa", target="Sales.SemmanticModel", artifact=None, workspace_id=""
    )

    assert fab_test_module._prepare_target(args) == 2
    assert "SemanticModel" in capsys.readouterr().err


@pytest.mark.fab_test
def test_prepare_target_rejects_a_scope_the_analyzer_cannot_honor(capsys):
    args = argparse.Namespace(
        analyzer="bpa",
        target="Sales Dev.Workspace/Sales.SemanticModel",
        artifact=None,
        workspace_id="",
    )

    assert fab_test_module._prepare_target(args) == 2
    assert "bpa" in capsys.readouterr().err


@pytest.mark.fab_test
def test_prepare_target_passes_a_plain_target_through(monkeypatch):
    """None means continue; the resolved target is left on args for later steps."""
    monkeypatch.setattr(fab_test_module, "_resolve_workspace_target", lambda a: None)
    args = argparse.Namespace(
        analyzer="bpa", target="Sales.SemanticModel", artifact=None, workspace_id=""
    )

    assert fab_test_module._prepare_target(args) is None
    assert args.resolved_target.name == "Sales"


@pytest.mark.fab_test
def test_prepare_paths_rejects_a_missing_artifact_dir(tmp_path, capsys):
    args = argparse.Namespace(
        artifact_dir=str(tmp_path / "absent"),
        output_format="text",
        environment="",
        file_config={},
    )

    assert fab_test_module._prepare_paths(args) == 2
    assert "does not exist" in capsys.readouterr().out
