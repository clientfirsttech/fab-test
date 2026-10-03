"""Contract tests for reporting the resolved target (Artifact Targeting and Auth §5).

Scope
-----
What `fab-test` decided about a target has to be visible, otherwise the
grammar is only half a contract: a caller can state a scope but cannot
confirm it was honored. Covers `explain`, `--dry-run`, and `run.json`.

The target is reported as a structured object, never an interpolated
string, so a consumer branches on ``scope`` rather than parsing prose.
Always passes on any machine.
"""

import json
import os
import subprocess
import sys

import pytest

from fab_test.scripts._run_manifest import RunManifest
from fab_test.scripts._target import parse_target

_GUID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def artifact_tree(tmp_path):
    for folder in ("Sales.SemanticModel", "Sales.Report"):
        (tmp_path / folder).mkdir()
    return tmp_path


def _run_cli(*argv, env=None):
    return subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
        check=False,
    )


# --------------------------------------------------------------------------- #
# The serialized shape
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_as_dict_is_structured_not_interpolated():
    """Every field is separately addressable, so no consumer parses prose."""
    payload = parse_target("Sales Dev.Workspace/Sales.SemanticModel").as_dict(_GUID)

    assert payload["scope"] == "workspace"
    assert payload["workspace"] == "Sales Dev"
    assert payload["workspace_id"] == _GUID
    assert payload["name"] == "Sales"
    assert payload["type"] == "SemanticModel"
    assert payload["raw"] == "Sales Dev.Workspace/Sales.SemanticModel"


@pytest.mark.fab_test
def test_as_dict_is_json_serializable_including_paths():
    """A Path would not survive json.dumps, so it is stringified up front."""
    payload = parse_target("./src/Sales.SemanticModel").as_dict()

    json.dumps(payload)
    assert isinstance(payload["path"], str)


@pytest.mark.fab_test
def test_unresolved_workspace_id_is_none_not_empty_string():
    """Absent means null in JSON, so a consumer can test one thing."""
    assert parse_target("local/Sales").as_dict()["workspace_id"] is None


# --------------------------------------------------------------------------- #
# run.json
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_manifest_records_the_resolved_target(tmp_path):
    """A finished run says whether it read files, Desktop, or a workspace."""
    target = parse_target("local/Sales").as_dict()
    manifest = RunManifest("1.0.0", ["fab-test", "pql-test", "local/Sales"], target=target)

    written = json.loads(manifest.write(tmp_path, 0).read_text(encoding="utf-8"))

    assert written["target"]["scope"] == "desktop"
    assert written["target"]["name"] == "Sales"


@pytest.mark.fab_test
def test_manifest_target_is_null_when_nothing_was_targeted(tmp_path):
    """Discovery runs stay distinguishable from targeted ones."""
    manifest = RunManifest("1.0.0", ["fab-test", "bpa"])

    written = json.loads(manifest.write(tmp_path, 0).read_text(encoding="utf-8"))

    assert written["target"] is None


@pytest.mark.fab_test
def test_manifest_target_carries_no_secret(tmp_path):
    """A workspace ID names a workspace; it does not grant access to one."""
    target = parse_target(f"{_GUID}.Workspace/Sales.SemanticModel").as_dict(_GUID)
    manifest = RunManifest("1.0.0", ["fab-test"], target=target)

    written = manifest.write(tmp_path, 0).read_text(encoding="utf-8")

    for forbidden in ("SECRET", "secret", "token", "password"):
        assert forbidden not in written


@pytest.mark.fab_test
def test_run_json_records_the_target_end_to_end(artifact_tree):
    """The real CLI writes the target it resolved, not just the flags it got."""
    output_dir = artifact_tree / "results"
    result = _run_cli(
        "pql-lint",
        "Sales.SemanticModel",
        "--artifact-dir",
        str(artifact_tree),
        "--output-dir",
        str(output_dir),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    written = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert written["target"]["name"] == "Sales"
    assert written["target"]["type"] == "SemanticModel"
    assert written["target"]["scope"] == "path"


# --------------------------------------------------------------------------- #
# explain and --dry-run
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_explain_reports_the_resolved_target(artifact_tree):
    """`explain pql-test local/Sales` shows the scope alongside the command."""
    result = _run_cli(
        "explain",
        "pql_test",
        "local/Sales",
        "--artifact-dir",
        str(artifact_tree),
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["target"]["scope"] == "desktop"
    assert payload["target"]["name"] == "Sales"
    assert payload["command"], "explain must still show the command"


@pytest.mark.fab_test
def test_explain_without_a_target_reports_none(artifact_tree):
    """The no-target case stays valid and explicit rather than absent."""
    result = _run_cli(
        "explain", "bpa", "--artifact-dir", str(artifact_tree), "--format", "json"
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["target"] is None


@pytest.mark.fab_test
def test_explain_refuses_a_scope_the_analyzer_cannot_honor(artifact_tree):
    """Explaining an impossible command would be explaining a lie."""
    result = _run_cli(
        "explain",
        "pql_lint",
        "Sales Dev.Workspace/Sales.SemanticModel",
        "--artifact-dir",
        str(artifact_tree),
    )

    assert result.returncode == 2
    assert "pql_lint" in result.stderr


@pytest.mark.fab_test
def test_dry_run_prints_the_resolved_target_in_text_mode(artifact_tree):
    """A human sees what was resolved before anything runs."""
    result = _run_cli(
        "bpa", "local/Sales", "--artifact-dir", str(artifact_tree), "--dry-run"
    )

    assert result.returncode == 0, result.stderr
    assert "scope desktop" in result.stdout


@pytest.mark.fab_test
def test_dry_run_json_carries_the_target_object(artifact_tree):
    """The agent-facing shape matches the human one."""
    result = _run_cli(
        "bpa",
        "Sales.SemanticModel",
        "--artifact-dir",
        str(artifact_tree),
        "--dry-run",
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["target"]["type"] == "SemanticModel"
