"""Unit tests for scripts/invoke_prompt_lint.py."""

import json
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.prompt_lint, pytest.mark.analyzers]


from fabric_ci_cd_dataops.scripts.invoke_prompt_lint import main, run_prompt_lint, validate_path


class TestValidatePath:
    def test_missing_path_exits(self, tmp_path: Path):
        missing = tmp_path / "missing"
        with pytest.raises(SystemExit) as exc_info:
            validate_path(str(missing), "Artifact path")
        assert exc_info.value.code == 1


class TestRunPromptLint:
    def test_passes_for_valid_prompt(self, tmp_path: Path):
        artifact = tmp_path / "prompt.txt"
        artifact.write_text("Use the tool carefully.", encoding="utf-8")
        output = tmp_path / "out.json"

        class Args:
            artifact_path = str(artifact)
            output_path = str(output)

        exit_code = run_prompt_lint(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"

    def test_fails_for_empty_prompt(self, tmp_path: Path):
        artifact = tmp_path / "prompt.txt"
        artifact.write_text("", encoding="utf-8")
        output = tmp_path / "out.json"

        class Args:
            artifact_path = str(artifact)
            output_path = str(output)

        exit_code = run_prompt_lint(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"


class TestMain:
    def test_main_invokes_runner(self, tmp_path: Path, monkeypatch):
        artifact = tmp_path / "prompt.txt"
        artifact.write_text("Simple prompt", encoding="utf-8")
        output = tmp_path / "out.json"
        monkeypatch.setattr(sys, "argv", ["invoke_prompt_lint.py", "--artifact-path", str(artifact), "--output-path", str(output)])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
