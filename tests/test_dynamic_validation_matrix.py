"""Contract tests for dynamic-validation.yml matrix builder.

These tests mirror the Python logic embedded in the
``Build pql_test matrix`` step. They verify that the builder reads the
artifact-matrix ``matrix.json`` artifact, carries the environment and
workspace_id into the pql-test matrix, and falls back to repo discovery on
manual dispatch.
"""

import json
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.fab_test, pytest.mark.pql_test]

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "dynamic-validation.yml"


def _build_pql_matrix(downloaded_matrix_dir: Path) -> dict:
    """Reproduce the matrix builder logic from dynamic-validation.yml.

    Keeping this in sync with the inline Python script avoids needing to ship
    a separate CLI for a single CI step.
    """

    def _fallback_env():
        branch = os.environ.get("GITHUB_REF_NAME", "")
        if branch == "main":
            return "prod"
        if branch == "develop":
            return "dev"
        return "dev"

    matrix_path = downloaded_matrix_dir / "matrix.json"
    if not matrix_path.exists():
        env = _fallback_env()
        artifacts_root = REPO_ROOT / ".fabric" / "artifacts"
        if artifacts_root.is_dir():
            artifacts = [
                {
                    "name": p,
                    "type": "SemanticModel",
                    "path": str(artifacts_root / p),
                    "environment": env,
                    "workspace_id": "",
                }
                for p in os.listdir(artifacts_root)
                if p.endswith(".SemanticModel") and (artifacts_root / p).is_dir()
            ]
        else:
            artifacts = []
    else:
        with matrix_path.open() as f:
            data = json.load(f)
        artifacts = [
            {
                "name": item["name"],
                "type": item["type"],
                "path": item["path"],
                "environment": item.get("environment", ""),
                "workspace_id": item.get("workspace_id", ""),
            }
            for item in data.get("include", [])
            if item.get("type") == "SemanticModel"
        ]

    items = [
        {
            "artifact": a["name"],
            "path": a["path"],
            "environment": a.get("environment", ""),
            "workspace_id": a.get("workspace_id", ""),
        }
        for a in artifacts
    ]
    return {"include": items}


def test_build_pql_matrix_reads_include_and_carries_workspace_id(tmp_path: Path):
    """Matrix builder uses data.get('include', []) and carries workspace_id."""
    matrix = {
        "include": [
            {
                "name": "ModelA",
                "type": "SemanticModel",
                "path": ".fabric/artifacts/ModelA.SemanticModel",
                "environment": "dev",
                "workspace_id": "ws-dev-123",
            },
            {
                "name": "ReportB",
                "type": "Report",
                "path": ".fabric/artifacts/ReportB.Report",
                "environment": "dev",
                "workspace_id": "ws-dev-123",
            },
        ]
    }
    (tmp_path / "matrix.json").write_text(json.dumps(matrix))
    result = _build_pql_matrix(tmp_path)

    assert "include" in result
    assert len(result["include"]) == 1
    item = result["include"][0]
    assert item["artifact"] == "ModelA"
    assert item["environment"] == "dev"
    assert item["workspace_id"] == "ws-dev-123"
    assert item["path"] == ".fabric/artifacts/ModelA.SemanticModel"


def test_build_pql_matrix_maps_environment_correctly(tmp_path: Path):
    """The environment label in the artifact matrix is preserved in the pql matrix."""
    matrix = {
        "include": [
            {
                "name": "ModelA",
                "type": "SemanticModel",
                "path": ".fabric/artifacts/ModelA.SemanticModel",
                "environment": "testbed",
                "workspace_id": "ws-testbed-456",
            }
        ]
    }
    (tmp_path / "matrix.json").write_text(json.dumps(matrix))
    result = _build_pql_matrix(tmp_path)

    assert result["include"][0]["environment"] == "testbed"
    assert result["include"][0]["workspace_id"] == "ws-testbed-456"


def test_build_pql_matrix_fallback_develop_defaults_to_dev(
    tmp_path: Path, monkeypatch
):
    """workflow_dispatch fallback on develop defaults to dev environment."""
    monkeypatch.setenv("GITHUB_REF_NAME", "develop")
    result = _build_pql_matrix(tmp_path)
    if REPO_ROOT.joinpath(".fabric", "artifacts").is_dir():
        for item in result["include"]:
            assert item["environment"] == "dev"
            assert item["workspace_id"] == ""
    else:
        assert result["include"] == []
