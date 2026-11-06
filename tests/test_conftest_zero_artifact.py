"""Tests for zero-artifact session failure in conftest.py."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"


@pytest.mark.integration
def test_zero_semantic_model_artifacts_fails_bpa(tmp_path: Path, monkeypatch):
    """Given no *.SemanticModel artifacts, pytest -m bpa must exit non-zero.

    Runs the real ``conftest.py`` in a sandbox with an empty ``fabric-artifacts``.
    It used to move the repository's own semantic models away for the duration,
    which made any test scanning the repo fail whenever xdist scheduled it
    alongside this one.
    """
    sandbox_tests = tmp_path / "tests"
    sandbox_tests.mkdir()
    (tmp_path / "fabric-artifacts").mkdir()
    shutil.copy(TESTS_DIR / "conftest.py", sandbox_tests / "conftest.py")
    shutil.copy(REPO_ROOT / "pytest.ini", tmp_path / "pytest.ini")
    (sandbox_tests / "test_probe.py").write_text(
        "import pytest\n\n\n@pytest.mark.bpa\ndef test_contract():\n    pass\n", encoding="utf-8"
    )

    monkeypatch.setenv("ANALYZER_ARTIFACTS", "")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "bpa", "--tb=short", "-p", "no:cacheprovider"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    # The session must fail even though the contract test itself passes.
    assert result.returncode != 0, (
        f"Expected non-zero exit when no artifacts exist.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "No artifacts matched '*.SemanticModel'" in result.stderr, (
        f"Expected clear zero-artifact message. stderr:\n{result.stderr}"
    )
