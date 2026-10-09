"""Contract tests for `fab-test list` and `fab-test explain`
(CLI Agent Ergonomics §9 and §10).

Scope
-----
`list` lets a caller discover capability from the tool instead of the docs.
`explain` shows the resolved command for one analyzer without running it.
Both always pass on any machine — dry, read-only introspection.

    pytest -m fab_test tests/test_list_explain.py -k list
    pytest -m fab_test tests/test_list_explain.py -k explain
"""

import json
import subprocess

import pytest

from fab_test.scripts.fab_test_registry import visible_analyzers


@pytest.mark.fab_test
def test_list_text_shows_every_analyzer_with_glob_and_tool():
    """fab-test list (text) names every analyzer, its glob, and required tool."""
    result = subprocess.run(
        ["fab-test", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for name in visible_analyzers():
        assert name in result.stdout, f"{name} missing from list output"
    assert "Tabular Editor" in result.stdout
    assert "*.SemanticModel" in result.stdout


@pytest.mark.fab_test
def test_list_json_format_is_one_document():
    """--format json emits one document covering every *visible* analyzer."""
    result = subprocess.run(
        ["fab-test", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert len(summary["analyzers"]) == len(visible_analyzers())
    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["glob"] == "*.SemanticModel"
    assert bpa_row["required_tool"] == "Tabular Editor"
    assert "matched_artifacts" in bpa_row


@pytest.mark.fab_test
def test_list_matched_artifact_count_reflects_real_artifacts(tmp_path):
    """matched_artifacts counts real matches under --artifact-dir."""
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "ModelOne.SemanticModel").mkdir(parents=True)
    (artifact_dir / "ModelTwo.SemanticModel").mkdir(parents=True)

    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(artifact_dir), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["matched_artifacts"] == 2


@pytest.mark.fab_test
def test_list_empty_artifact_dir_exits_zero_with_zero_counts(tmp_path):
    """An artifact-less directory reports zero matches for glob-based analyzers
    and still exits 0.
    """
    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(artifact_dir), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    bpa_row = next(r for r in summary["analyzers"] if r["analyzer"] == "bpa")
    assert bpa_row["matched_artifacts"] == 0


@pytest.mark.fab_test
def test_list_repository_scoped_analyzers_have_no_glob():
    """dependencies runs once against the repo, not a glob match."""
    result = subprocess.run(
        ["fab-test", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    deps_row = next(r for r in summary["analyzers"] if r["analyzer"] == "dependencies")
    assert deps_row["glob"] is None
    assert deps_row["matched_artifacts"] == 1


# --------------------------------------------------------------------------- #
# fab-test explain
# --------------------------------------------------------------------------- #


class _ExplainArgs:
    def __init__(self, analyzer_name, artifact_dir, output_dir, output_format="json"):
        self.analyzer_name = analyzer_name
        self.artifact_dir = str(artifact_dir)
        self.output_dir = str(output_dir)
        self.artifact = None
        self.output_format = output_format


@pytest.mark.fab_test
def test_explain_bpa_never_spawns_a_subprocess(tmp_path, monkeypatch):
    """explain builds the resolved command but never executes it."""
    from fab_test.scripts import fab_test_admin

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)

    def _fail_if_called(*_a, **_k):
        raise AssertionError("explain must never spawn a subprocess")

    monkeypatch.setattr(fab_test_admin.subprocess, "run", _fail_if_called)

    args = _ExplainArgs("bpa", artifact_dir, tmp_path / "results")
    code = fab_test_admin._explain_analyzer(args)

    assert code == 0


@pytest.mark.fab_test
def test_explain_json_payload_shape(tmp_path, capsys):
    """The JSON payload has the documented keys and a real command list."""
    from fab_test.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)

    args = _ExplainArgs("bpa", artifact_dir, tmp_path / "results")
    code = fab_test_module._explain_analyzer(args)
    captured = capsys.readouterr()

    assert code == 0
    payload = json.loads(captured.out)
    for key in ("analyzer", "artifact", "command", "tool_path", "rules_path", "output_path"):
        assert key in payload, f"{key} missing from explain payload"
    assert payload["analyzer"] == "bpa"
    assert isinstance(payload["command"], list)
    assert any("invoke_tabular_editor_bpa" in part for part in payload["command"])


@pytest.mark.fab_test
def test_explain_text_format_shows_command(tmp_path, capsys):
    """--format text (default) prints a human-readable command breakdown."""
    from fab_test.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)

    args = _ExplainArgs("bpa", artifact_dir, tmp_path / "results", output_format="text")
    code = fab_test_module._explain_analyzer(args)
    captured = capsys.readouterr()

    assert code == 0
    assert "bpa" in captured.out
    assert "invoke_tabular_editor_bpa" in captured.out


@pytest.mark.fab_test
def test_explain_unknown_analyzer_exits_2_and_lists_valid_names():
    """An unrecognized analyzer name exits 2 and lists the valid choices."""
    result = subprocess.run(
        ["fab-test", "explain", "not-a-real-analyzer"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "not-a-real-analyzer" in result.stderr
    assert "bpa" in result.stderr


@pytest.mark.fab_test
def test_explain_rules_path_falls_back_to_default_when_not_overridden(tmp_path, capsys):
    """rules_path reports the real default the command uses, not null."""
    from fab_test.scripts import fab_test_admin

    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "SampleModel.SemanticModel").mkdir(parents=True)

    args = _ExplainArgs("bpa", artifact_dir, tmp_path / "results")
    fab_test_admin._explain_analyzer(args)
    captured = capsys.readouterr()

    payload = json.loads(captured.out)
    assert payload["rules_path"] == fab_test_admin._DEFAULT_BPA_RULES
    assert payload["rules_path"] in payload["command"]


@pytest.mark.fab_test
def test_explain_falls_back_to_placeholder_when_no_artifact_matches(tmp_path):
    """With no matching artifact, explain still shows an illustrative command."""
    from fab_test.scripts import fab_test as fab_test_module

    artifact_dir = tmp_path / "empty"
    artifact_dir.mkdir()

    args = _ExplainArgs("bpa", artifact_dir, tmp_path / "results")
    code = fab_test_module._explain_analyzer(args)

    assert code == 0


# --------------------------------------------------------------------------- #
# An all-zero table explains itself (Empty Discovery Diagnostics §3)
# --------------------------------------------------------------------------- #


def _checkout(parent, name):
    """A directory the scan refuses to walk into, as a real repository is."""
    checkout = parent / name
    (checkout / ".git").mkdir(parents=True)
    return checkout


@pytest.mark.fab_test
def test_list_explains_a_table_of_zeroes(tmp_path):
    """Given a root whose every candidate was pruned, `list` reports 0 for
    each analyzer, which reads as "this tool can do nothing here" when the
    truth is that it never looked inside the repositories below.
    """
    _checkout(tmp_path, "project-a")
    _checkout(tmp_path, "project-b")

    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "2 git checkouts" in result.stdout
    assert "--artifact-dir" in result.stdout


@pytest.mark.fab_test
def test_list_says_nothing_when_a_scan_pruned_nothing(tmp_path):
    """Given an ordinary empty directory, a zero count is the whole truth."""
    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "checkout" not in result.stdout


@pytest.mark.fab_test
def test_list_says_nothing_when_an_analyzer_matched_something(tmp_path):
    """Given a partial result, there is no confusing absence to explain."""
    _checkout(tmp_path, "project-a")
    (tmp_path / "Sales.SemanticModel" / "definition").mkdir(parents=True)

    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "checkout" not in result.stdout


@pytest.mark.fab_test
def test_list_json_carries_the_skipped_checkouts(tmp_path):
    """The agent caller reads the payload, not the table."""
    checkout = _checkout(tmp_path, "project-a")

    result = subprocess.run(
        ["fab-test", "list", "--artifact-dir", str(tmp_path), "--format", "json"],
        capture_output=True, text=True, check=False,
    )

    payload = json.loads(result.stdout)
    assert payload["skipped_checkouts"] == [str(checkout)]
    assert "--artifact-dir" in payload["remediation"]


@pytest.mark.fab_test
def test_print_list_json_payload_shape(tmp_path, capsys):
    """Given the JSON list payload, the checkout keys travel with the rows.

    Exercised in-process because every other `list` test shells out, which
    leaves this branch uncovered however green the suite looks.
    """
    from fab_test.scripts.fab_test_summary import _print_list

    row = {
        "analyzer": "bpa",
        "aliases": [],
        "glob": "*.SemanticModel",
        "matched_artifacts": 0,
        "required_tool": "Tabular Editor",
        "scopes": ["path"],
    }

    assert _print_list([row], "json", skipped_checkouts=[tmp_path / "repo"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["analyzers"] == [row]
    assert payload["skipped_checkouts"] == [str(tmp_path / "repo")]
    assert "--artifact-dir" in payload["remediation"]


@pytest.mark.fab_test
def test_print_list_json_payload_omits_remediation_when_nothing_was_pruned(capsys):
    """Given nothing was pruned, there is nothing to remediate."""
    from fab_test.scripts.fab_test_summary import _print_list

    assert _print_list([], "json") == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["skipped_checkouts"] == []
    assert "remediation" not in payload
