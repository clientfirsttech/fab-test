"""Policy tests for artifact-runner.yml job dependencies.

These tests validate that the artifact-runner workflow does not re-introduce
a hard dependency that causes static analysis (and therefore Tabular Editor BPA)
to be skipped when security scanning is temporarily disabled.
"""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def artifact_runner_path(repo_root: Path) -> Path:
    """Path to artifact-runner.yml."""
    return repo_root / ".github" / "workflows" / "artifact-runner.yml"


class TestStaticAnalysisDependencies:
    """Static analysis must run independently of the disabled security-scan job."""

    def test_static_analysis_does_not_need_security_scan(
        self, artifact_runner_path: Path
    ):
        """Given security-scan is temporarily disabled, static analysis jobs must not need it."""
        workflow = yaml.safe_load(artifact_runner_path.read_text(encoding="utf-8"))
        for job_name in ("static-linux", "static-windows"):
            static_analysis = workflow["jobs"][job_name]
            needs = static_analysis.get("needs", [])

            assert "security-scan" not in needs, (
                f"{job_name} must not depend on security-scan while security-scan is disabled, "
                "or analyzers will be skipped for artifact changes"
            )

    def test_static_analysis_runs_when_static_analyzers_exist(
        self, artifact_runner_path: Path
    ):
        """Given static analyzers are discovered, static analysis jobs should run."""
        workflow = yaml.safe_load(artifact_runner_path.read_text(encoding="utf-8"))

        linux = workflow["jobs"]["static-linux"]
        linux_condition = linux.get("if", "")
        assert "needs.prepare-matrix.outputs.has_pbir == 'true'" in linux_condition
        assert "inputs.run_static == true" in linux_condition

        windows = workflow["jobs"]["static-windows"]
        windows_condition = windows.get("if", "")
        assert "needs.prepare-matrix.outputs.has_bpa == 'true'" in windows_condition
        assert "inputs.run_static == true" in windows_condition
