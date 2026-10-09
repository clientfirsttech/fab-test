"""`--format json` writes exactly one JSON document to stdout, `all` and `local` included.

Found 2026-09-29 and still true on 1.9.0b10: each analyzer printed its own
`{"analyzer": ..., "artifacts": [...]}` document and then `all`/`local`
printed their aggregate after it, so `json.load` failed with "Extra data".
The fab-test skill promises one document; under `all`/`local` it is the
aggregate.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts.fab_test_summary import _print_summary

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("command", ["all", "local"])
def test_given_an_aggregate_command_should_leave_the_document_to_the_aggregate(capsys, command):
    code = _print_summary("rdl", [("Sales", 1)], output_format="json", args=argparse.Namespace(analyzer=command))
    assert code == 1
    assert capsys.readouterr().out == ""


def test_given_a_single_analyzer_should_still_print_its_own_document(capsys):
    _print_summary("rdl", [("Sales", 0)], output_format="json", args=argparse.Namespace(analyzer="rdl"))
    assert json.loads(capsys.readouterr().out)["analyzer"] == "rdl"


@pytest.mark.parametrize("command", ["all", "local"])
def test_given_format_json_should_write_one_parseable_document(tmp_path, command):
    shutil.copy(ROOT / "fabric-artifacts" / "PaginatedExample-BrokenRDL.rdl", tmp_path / "Sample.rdl")
    result = subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", command, "--format", "json", "--output-dir", "out"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "FABRIC_WORKSPACE_ID": ""},
        check=False,
    )
    document = json.loads(result.stdout)  # raises "Extra data" on a second document
    if command == "all":
        rows = [row for row in document["artifacts"] if row["analyzer"] == "rdl"]
    else:  # local keeps each analyzer's per-artifact rows inside its one document
        rows = next(entry for entry in document["results"] if entry["analyzer"] == "rdl")["artifacts"]
    assert [row["artifact"] for row in rows] == ["Sample"], result.stdout[:500]


def test_given_ci_annotations_should_go_to_stderr_never_stdout(capsys, monkeypatch):
    """Found running these tests under GITHUB_ACTIONS: a `::warning::` line preceded the document."""
    from fab_test.scripts._analyzer_annotations import emit_workflow_annotations

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    emit_workflow_annotations({"analyzer": "rdl", "findings": [{"rule": "ACC-03", "severity": "warning"}]})
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith("::warning::[rdl] ACC-03")


@pytest.mark.parametrize("ci", ["true", ""])
def test_given_a_tool_bootstrap_note_should_go_to_stderr_never_stdout(capsys, monkeypatch, ci):
    from fab_test.scripts._analyzer_tool_bootstrap import _notice

    monkeypatch.setenv("GITHUB_ACTIONS", ci)
    monkeypatch.setenv("CI", ci)
    _notice("downloading Tabular Editor")
    out, err = capsys.readouterr()
    assert out == ""
    assert "downloading Tabular Editor" in err
