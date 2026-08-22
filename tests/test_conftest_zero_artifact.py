"""Tests for zero-artifact session failure in conftest.py."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"


@pytest.mark.integration
@pytest.mark.skipif(
    not (REPO_ROOT / ".fabric" / "artifacts").exists(),
    reason="Requires .fabric/artifacts directory to exist",
)
def test_zero_semantic_model_artifacts_fails_bpa(tmp_path: Path, monkeypatch):
    """Given no *.SemanticModel artifacts, pytest -m bpa must exit non-zero."""
    artifacts_dir = REPO_ROOT / ".fabric" / "artifacts"
    backups: list[tuple[Path, Path]] = []

    # Temporarily move all .SemanticModel artifacts out of the repo.
    semantic_models = list(artifacts_dir.glob("*.SemanticModel"))
    for src in semantic_models:
        dst = tmp_path / src.name
        shutil.move(str(src), str(dst))
        backups.append((dst, src))

    monkeypatch.setenv("ANALYZER_ARTIFACTS", "")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "bpa", "--tb=short"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        # The session must fail even though the contract tests themselves pass.
        assert result.returncode != 0, (
            f"Expected non-zero exit when no artifacts exist.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "No artifacts matched '*.SemanticModel'" in result.stderr, (
            f"Expected clear zero-artifact message. stderr:\n{result.stderr}"
        )
    finally:
        for dst, src in backups:
            shutil.move(str(dst), str(src))
