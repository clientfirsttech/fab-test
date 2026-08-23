"""Contract tests for who and where in the telemetry payload.

Scope
-----
Two findings from inspecting real ingested rows:

* `actor` was a sha256 of the git email — unusable for the attribution the
  Telemetry Context epic said it was for.
* The username leaked anyway, in plaintext, through absolute paths inside the
  embedded `results` envelope (`C:\\Users\\jkers\\...`). `_redact_pii` only
  ever guarded `actor`, and nobody looked at the envelope.

So telemetry was identifying people by accident and failing to identify them
on purpose. These tests pin the correction.

    pytest -m telemetry tests/test_telemetry_identity.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fabric_ci_cd_dataops.scripts.fab_test import _build_telemetry_payload, _relativize_paths

# --------------------------------------------------------------------------
# Paths carry no username
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_absolute_paths_under_the_repository_become_relative():
    """Given a path inside the repository, should record it relative to the root.

    `C:\\Users\\jkers\\Git\\fab-test\\...` names the person who ran it. The
    part that carries meaning downstream is everything after the root.
    """
    root = Path("/repo").resolve()
    payload = {"artifact_path": str(root / "artifacts" / "Sales.SemanticModel")}

    cleaned = _relativize_paths(payload, root)

    assert cleaned["artifact_path"] == str(Path("artifacts/Sales.SemanticModel"))


@pytest.mark.telemetry
def test_paths_nested_inside_the_results_envelope_are_relativized_too():
    """Given paths inside the embedded envelope, should rewrite those as well.

    This is where the leak actually lived: the whole envelope is embedded as
    `results`, and every envelope carries `artifact_path` and `rules_file`.
    """
    root = Path("/repo").resolve()
    payload = {
        "results": {
            "artifact_path": str(root / "artifacts" / "Sales.Report"),
            "rules_file": str(root / ".github" / "metadata" / "rules" / "BPARules.json"),
            "findings": [{"file": str(root / "artifacts" / "Sales.Report" / "definition.pbir")}],
        }
    }

    cleaned = _relativize_paths(payload, root)

    blob = json.dumps(cleaned)
    assert str(root) not in blob
    assert "Sales.Report" in blob, "the useful part of the path must survive"


@pytest.mark.telemetry
def test_a_path_outside_the_repository_is_not_rewritten_into_a_traversal():
    """Given a path elsewhere on the machine, should not emit `../../..`.

    A relative path climbing out of the repository leaks the depth of the
    home directory and means nothing to a reader of the table.
    """
    root = Path("/repo").resolve()
    outside = str(Path("/opt/tools/TabularEditor.exe").resolve())
    payload = {"tool_path": outside}

    cleaned = _relativize_paths(payload, root)

    assert ".." not in cleaned["tool_path"]


@pytest.mark.telemetry
def test_values_that_are_not_paths_are_left_alone():
    """Given ordinary strings and numbers, should pass them through untouched."""
    root = Path("/repo").resolve()
    payload = {"analyzer": "bpa", "error_count": 3, "status": "passed", "branch": "dev"}

    assert _relativize_paths(payload, root) == payload


@pytest.mark.telemetry
def test_the_built_payload_carries_no_absolute_path(tmp_path, monkeypatch):
    """Given a real payload build, should contain no absolute filesystem path.

    The end-to-end guard: the individual rewrites above are only useful if
    the payload builder actually applies them.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "REPO_ROOT", tmp_path)
    artifact = tmp_path / "artifacts" / "Sales.SemanticModel"
    artifact.mkdir(parents=True)
    envelope = {
        "status": "passed",
        "findings": [],
        "artifact_path": str(artifact),
        "rules_file": str(tmp_path / ".github" / "metadata" / "rules" / "BPARules.json"),
    }

    payload = _build_telemetry_payload("bpa", artifact, envelope, "DEV")

    assert str(tmp_path) not in json.dumps(payload)


# --------------------------------------------------------------------------
# The actor is identifiable on purpose
# --------------------------------------------------------------------------


@pytest.mark.telemetry
def test_the_actor_is_recorded_as_given_not_hashed(tmp_path, monkeypatch):
    """Given a git email, should record it as-is.

    A sha256 answers "was this the same person as last time" and nothing
    else. The repository already stores this address in plaintext on every
    commit, and the Eventhouse belongs to the same organisation, so hashing
    it bought no privacy and cost the attribution the field exists for.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        fab_test_module,
        "_git_context",
        lambda: {"actor": "john@kerski.net", "branch": "dev", "commit": "abc123"},
    )
    artifact = tmp_path / "Sales.SemanticModel"
    artifact.mkdir(parents=True)

    payload = _build_telemetry_payload("bpa", artifact, {"status": "passed", "findings": []}, "DEV")

    assert payload["actor"] == "john@kerski.net"
    assert not payload["actor"].startswith("sha256:")


@pytest.mark.telemetry
def test_a_non_email_actor_still_passes_through(tmp_path, monkeypatch):
    """Given a CI actor name rather than an email, should record it unchanged."""
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fab_test_module, "_git_context", lambda: {"actor": "github-actions[bot]"})
    artifact = tmp_path / "Sales.SemanticModel"
    artifact.mkdir(parents=True)

    payload = _build_telemetry_payload("bpa", artifact, {"status": "passed", "findings": []}, "")

    assert payload["actor"] == "github-actions[bot]"


@pytest.mark.telemetry
def test_an_absent_actor_is_empty_rather_than_a_hash_of_nothing(tmp_path, monkeypatch):
    """Given no resolvable identity, should record an empty string.

    Hashing "" produced a stable token that looked like a real person and
    was the same for everyone who had no git config.
    """
    from fabric_ci_cd_dataops.scripts import fab_test as fab_test_module

    monkeypatch.setattr(fab_test_module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(fab_test_module, "_git_context", dict)
    artifact = tmp_path / "Sales.SemanticModel"
    artifact.mkdir(parents=True)

    payload = _build_telemetry_payload("bpa", artifact, {"status": "passed", "findings": []}, "")

    assert payload["actor"] == ""
